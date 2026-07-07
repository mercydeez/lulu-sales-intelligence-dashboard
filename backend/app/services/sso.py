"""
OIDC-first SSO service (E5-1a).

Security model (see docs/security/SSO.md):
  * SSO is OFF by default; OIDC must be explicitly enabled (settings.sso_enabled +
    sso_oidc_enabled) and a per-tenant provider row must be `enabled`.
  * Auth-flow state/nonce/PKCE-verifier are stored ONLY as hashes, single-use,
    TTL-bounded (CSRF + replay protection).
  * ID tokens are validated: signature (JWKS), issuer, audience, expiry, nonce,
    subject present, email present, email_verified (when required).
  * JIT provisioning can NEVER create admin/owner/super_admin and never links
    across tenants; email-domain allow-lists are enforced.
  * Admin MFA cannot be bypassed: an admin/owner/super_admin without local TOTP is
    blocked unless the provider explicitly `trust_idp_mfa` AND the token carries a
    strong MFA signal (default: fail-closed).
  * Secrets: the client secret is read from the env var NAMED by
    provider.client_secret_env — never stored in the DB, never logged.

The security-critical decisions are PURE functions (testable without DB/network);
the async functions orchestrate DB + provider HTTP.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, logger

_ADMIN_ROLES = {"super_admin", "admin", "owner"}
_SAFE_JIT_ROLES = {"analyst", "store_manager", "regional_manager"}
_STRONG_AMR = {"mfa", "otp", "hwk", "fido", "swk", "pop", "sms", "phr", "phn"}


class SsoError(Exception):
    """SSO failure with a machine code + HTTP status + safe (non-secret) message."""

    def __init__(self, code: str, status: int = 400, message: Optional[str] = None):
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message or code.replace("_", " ")


# ===========================================================================
# Pure helpers (no DB, no network) — the security-critical, unit-tested core.
# ===========================================================================
def gen_token(n_bytes: int = 32) -> str:
    return secrets.token_urlsafe(n_bytes)


def hash_value(value: str) -> str:
    """Stable hash for at-rest storage of state/nonce/verifier (never the raw value)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_pair() -> Tuple[str, str]:
    """(code_verifier, code_challenge) using S256."""
    verifier = gen_token(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def validate_return_to(return_to: Optional[str], allowed_hosts: str, max_len: int) -> bool:
    """A post-login return_to must be a safe same-origin path or an allow-listed host.
    Empty is fine. Protocol-relative (`//evil`) and unknown hosts are rejected."""
    if not return_to:
        return True
    if len(return_to) > max_len:
        return False
    if return_to.startswith("//"):
        return False
    parsed = urlparse(return_to)
    if not parsed.netloc:  # relative path
        return return_to.startswith("/")
    if parsed.scheme not in ("https", "http"):
        return False
    hosts = {h.strip().lower() for h in (allowed_hosts or "").split(",") if h.strip()}
    return bool(parsed.hostname) and parsed.hostname.lower() in hosts


def email_domain_allowed(email: str, allowed_domains: Optional[List[str]]) -> bool:
    """True when the email's domain is allowed. Empty/None list = no restriction."""
    if not allowed_domains:
        return True
    if "@" not in (email or ""):
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in {str(d).lower().lstrip("@") for d in allowed_domains}


def clamp_jit_role(requested_role: Optional[str]) -> str:
    """JIT provisioning must NEVER create a privileged account. Anything outside the
    safe set (incl. admin/owner/super_admin) collapses to analyst."""
    role = (requested_role or "analyst").lower()
    if role in _ADMIN_ROLES or role not in _SAFE_JIT_ROLES:
        return "analyst"
    return role


def build_authorization_url(
    provider: Dict[str, Any],
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: Optional[str] = None,
    scopes: Optional[str] = None,
) -> str:
    """Build the OIDC authorization-code request URL. Contains no client secret."""
    params = {
        "response_type": "code",
        "client_id": provider["client_id"],
        "redirect_uri": redirect_uri,
        "scope": scopes or provider.get("scopes") or "openid email profile",
        "state": state,
        "nonce": nonce,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{provider['authorization_endpoint']}?{urlencode(params)}"


def validate_id_claims(
    claims: Dict[str, Any],
    provider: Dict[str, Any],
    expected_nonce: Optional[str],
    require_verified_email: bool,
) -> None:
    """Validate the business claims of an ID token. Signature + expiry are checked
    by the JWT library before this; here we enforce issuer/audience/nonce/subject/
    email/email_verified. Raises SsoError on any failure."""
    iss = claims.get("iss")
    if not iss or (provider.get("issuer") and iss != provider["issuer"]):
        raise SsoError("invalid_issuer", 401)

    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if provider.get("client_id") and provider["client_id"] not in auds:
        raise SsoError("invalid_audience", 401)

    if not claims.get("sub"):
        raise SsoError("missing_subject", 401)

    if expected_nonce is not None and claims.get("nonce") != expected_nonce:
        raise SsoError("nonce_mismatch", 401)

    email = claims.get("email")
    if not email:
        raise SsoError("missing_email", 401)

    if require_verified_email and not bool(claims.get("email_verified", False)):
        raise SsoError("email_not_verified", 401)


def extract_mfa_signal(claims: Dict[str, Any]) -> bool:
    """True when the ID token carries a strong multi-factor signal (amr/acr).
    Azure AD/Entra sets amr and may set acr; we treat known-strong values only."""
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if any(str(a).lower() in _STRONG_AMR for a in amr):
        return True
    acr = str(claims.get("acr") or "").lower()
    return "mfa" in acr or "multipleauthn" in acr


def admin_mfa_block_reason(
    user_data: Dict[str, Any],
    provider: Dict[str, Any],
    claims: Dict[str, Any],
    require_mfa_for_admins: bool,
) -> Optional[str]:
    """Return a reason string if SSO must NOT issue tokens for this (admin) user
    because MFA policy isn't satisfied; None if issuance may proceed.

    Fail-closed: an admin without local TOTP is blocked unless the provider
    explicitly `trust_idp_mfa` AND the token has a strong MFA signal."""
    role = (user_data.get("role") or "").lower()
    if not require_mfa_for_admins or role not in _ADMIN_ROLES:
        return None
    if user_data.get("two_factor_enabled"):
        return None
    if bool(provider.get("trust_idp_mfa")) and extract_mfa_signal(claims):
        return None
    return "admin_mfa_required"


def public_provider_view(provider: Dict[str, Any], include_admin_fields: bool = False) -> Dict[str, Any]:
    """Public-safe provider metadata (NO client_secret_env unless admin)."""
    out = {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "provider_type": provider.get("provider_type"),
        "enabled": provider.get("enabled"),
        "issuer": provider.get("issuer"),
        "jit_provisioning_enabled": provider.get("jit_provisioning_enabled"),
    }
    if include_admin_fields:
        out["client_secret_env"] = provider.get("client_secret_env")
        out["allowed_domains"] = provider.get("allowed_domains")
        out["trust_idp_mfa"] = provider.get("trust_idp_mfa")
        out["default_role"] = provider.get("default_role")
    return out


# ===========================================================================
# In-memory discovery / JWKS cache (best-effort; tests inject instead).
# ===========================================================================
_DISCOVERY_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_JWKS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


async def _http_get_json(url: str, http_client=None, timeout: float = 5.0) -> Dict[str, Any]:
    if http_client is not None:
        resp = await http_client.get(url, timeout=timeout)
        return resp.json()
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def discover_oidc(issuer: str, http_client=None) -> Dict[str, Any]:
    """Fetch the OIDC discovery document (cached). Azure AD issuer:
    https://login.microsoftonline.com/<tenant-guid>/v2.0"""
    ttl = get_settings().sso_jwks_cache_ttl_seconds
    now = time.monotonic()
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and cached[0] > now:
        return cached[1]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    doc = await _http_get_json(url, http_client)
    _DISCOVERY_CACHE[issuer] = (now + ttl, doc)
    return doc


async def fetch_jwks(jwks_uri: str, http_client=None) -> Dict[str, Any]:
    ttl = get_settings().sso_jwks_cache_ttl_seconds
    now = time.monotonic()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and cached[0] > now:
        return cached[1]
    jwks = await _http_get_json(jwks_uri, http_client)
    _JWKS_CACHE[jwks_uri] = (now + ttl, jwks)
    return jwks


def decode_and_validate_id_token(
    id_token: str,
    provider: Dict[str, Any],
    jwks: Dict[str, Any],
    expected_nonce: Optional[str],
    require_verified_email: bool,
) -> Dict[str, Any]:
    """Verify signature/issuer/audience/expiry via python-jose, then the business
    claims. Never logs the token. Returns the validated claims."""
    from jose import jwt

    try:
        header = jwt.get_unverified_header(id_token)
    except Exception:
        raise SsoError("invalid_token", 401)
    kid = header.get("kid")
    keys = jwks.get("keys", []) if isinstance(jwks, dict) else []
    key_dict = next((k for k in keys if k.get("kid") == kid), None) or (keys[0] if keys else None)
    if not key_dict:
        raise SsoError("no_signing_key", 401)
    try:
        # python-jose accepts a JWK dict directly as the key.
        claims = jwt.decode(
            id_token,
            key_dict,
            algorithms=[header.get("alg", "RS256")],
            audience=provider.get("client_id"),
            issuer=provider.get("issuer"),
            options={"verify_at_hash": False},
        )
    except Exception:
        raise SsoError("token_verification_failed", 401)
    validate_id_claims(claims, provider, expected_nonce, require_verified_email)
    return claims


# ===========================================================================
# Async DB orchestration.
# ===========================================================================
def _ensure_oidc_enabled() -> None:
    s = get_settings()
    if not (s.sso_enabled and s.sso_oidc_enabled):
        raise SsoError("sso_disabled", 404)


async def get_oidc_provider(
    session: AsyncSession,
    *,
    tenant_id: Optional[int] = None,
    tenant_slug: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load one ENABLED oidc provider, scoped to a tenant (by id or slug)."""
    where = ["p.enabled = true", "p.provider_type = 'oidc'"]
    params: Dict[str, Any] = {}
    if tenant_id is not None:
        where.append("p.tenant_id = :tid")
        params["tid"] = tenant_id
    elif tenant_slug is not None:
        where.append("p.tenant_id = (SELECT id FROM tenants WHERE slug = :slug)")
        params["slug"] = tenant_slug
    else:
        return None
    if provider_name:
        where.append("p.name = :pname")
        params["pname"] = provider_name
    sql = "SELECT p.* FROM tenant_sso_providers p WHERE " + " AND ".join(where) + " ORDER BY p.id LIMIT 1"
    row = (await session.execute(text(sql), params)).mappings().first()
    return dict(row) if row else None


async def get_provider_by_id(session: AsyncSession, provider_id: int) -> Optional[Dict[str, Any]]:
    """Load an ENABLED oidc provider by id (used at callback via the state row)."""
    row = (await session.execute(text(
        "SELECT * FROM tenant_sso_providers WHERE id = :id AND enabled = true AND provider_type = 'oidc'"
    ), {"id": provider_id})).mappings().first()
    return dict(row) if row else None


async def list_providers_public(session: AsyncSession, *, tenant_slug: Optional[str] = None,
                                email_domain: Optional[str] = None) -> List[Dict[str, Any]]:
    where = ["p.enabled = true"]
    params: Dict[str, Any] = {}
    if tenant_slug:
        where.append("p.tenant_id = (SELECT id FROM tenants WHERE slug = :slug)")
        params["slug"] = tenant_slug
    elif email_domain:
        where.append("p.allowed_domains @> to_jsonb(:dom::text)")
        params["dom"] = email_domain.lower()
    else:
        return []
    sql = "SELECT p.* FROM tenant_sso_providers p WHERE " + " AND ".join(where) + " ORDER BY p.name"
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [public_provider_view(dict(r)) for r in rows]


async def create_auth_state(
    session: AsyncSession, provider: Dict[str, Any], redirect_uri: str,
    return_to: Optional[str], ip: Optional[str], ua: Optional[str],
) -> Tuple[str, str]:
    """Create a single-use state row (hashes only). Returns (state, nonce).

    This is the CONFIDENTIAL web-client flow: the client_secret secures the token
    exchange, and state+nonce give CSRF + replay protection. PKCE (pkce_pair()) is
    kept available for a future PUBLIC-client flow but is not wired here, because
    storing only the verifier HASH (per the at-rest rule) can't complete a PKCE
    exchange server-side. See docs/security/SSO.md."""
    s = get_settings()
    state = gen_token(32)
    nonce = gen_token(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=s.sso_state_ttl_seconds)
    await session.execute(text("""
        INSERT INTO sso_auth_states
            (state_hash, nonce_hash, tenant_id, provider_id, redirect_uri, return_to,
             expires_at, ip_address, user_agent)
        VALUES (:sh, :nh, :tid, :pid, :ruri, :rto, :exp, :ip, :ua)
    """), {
        "sh": hash_value(state), "nh": hash_value(nonce), "tid": provider["tenant_id"],
        "pid": provider["id"], "ruri": redirect_uri, "rto": return_to,
        "exp": expires, "ip": ip, "ua": (ua or "")[:400],
    })
    await session.commit()
    return state, nonce


async def consume_auth_state(session: AsyncSession, state: str) -> Dict[str, Any]:
    """Atomically consume a state exactly once. Raises on missing/expired/replayed."""
    sh = hash_value(state)
    row = (await session.execute(text(
        "SELECT * FROM sso_auth_states WHERE state_hash = :sh"), {"sh": sh})).mappings().first()
    if not row:
        raise SsoError("state_unknown", 400)
    if row["consumed_at"] is not None:
        raise SsoError("state_replayed", 400)
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise SsoError("state_expired", 400)
    # Mark consumed only if still unconsumed (single-use race guard).
    res = await session.execute(text(
        "UPDATE sso_auth_states SET consumed_at = now() WHERE state_hash = :sh AND consumed_at IS NULL"
    ), {"sh": sh})
    await session.commit()
    if res.rowcount != 1:
        raise SsoError("state_replayed", 400)
    return dict(row)


async def exchange_code(provider: Dict[str, Any], code: str, redirect_uri: str,
                        code_verifier: Optional[str], http_client=None) -> Dict[str, Any]:
    """Exchange the authorization code for tokens. Client secret comes from the env
    var NAMED by provider.client_secret_env. Never logs code/secret/tokens."""
    secret_env = provider.get("client_secret_env")
    client_secret = os.environ.get(secret_env) if secret_env else None
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider["client_id"],
    }
    if client_secret:
        data["client_secret"] = client_secret
    if code_verifier:
        data["code_verifier"] = code_verifier
    if http_client is not None:
        resp = await http_client.post(provider["token_endpoint"], data=data, timeout=8.0)
        return resp.json()
    import httpx
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.post(provider["token_endpoint"], data=data)
        resp.raise_for_status()
        return resp.json()


async def _load_user_data(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """Build the user_data dict AuthService.create_tokens expects (+ permissions)."""
    from app.services.auth_service import AuthService
    u = (await session.execute(text("""
        SELECT id, email, first_name, last_name, role, status, job_title, department,
               tenant_id, two_factor_enabled, email_verified
        FROM users WHERE id = :id
    """), {"id": user_id})).mappings().first()
    if not u:
        raise SsoError("user_load_failed", 500)
    perms = await AuthService._get_user_permissions(session, u["id"], u["role"], u.get("tenant_id"))
    return {
        "id": u["id"], "email": u["email"], "first_name": u["first_name"],
        "last_name": u["last_name"], "role": u["role"], "status": u["status"],
        "job_title": u["job_title"], "department": u["department"],
        "tenant_id": u.get("tenant_id"),
        "two_factor_enabled": bool(u.get("two_factor_enabled")),
        "email_verified": bool(u.get("email_verified")),
        "permissions": perms,
    }


async def resolve_or_provision_user(
    session: AsyncSession, provider: Dict[str, Any], claims: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """Link/JIT per the security model. Returns (user_data, action) where action is
    'existing' | 'linked' | 'jit'. Never creates admins; never crosses tenants."""
    tenant_id = provider["tenant_id"]
    provider_id = provider["id"]
    subject = str(claims["sub"])
    email = str(claims["email"]).lower()
    issuer = str(claims.get("iss") or provider.get("issuer") or "")
    verified = bool(claims.get("email_verified", False))

    # 1. Existing linked identity (by provider + subject).
    ident = (await session.execute(text(
        "SELECT user_id FROM external_identities WHERE provider_id = :pid AND subject = :sub"
    ), {"pid": provider_id, "sub": subject})).mappings().first()
    if ident:
        await session.execute(text(
            "UPDATE external_identities SET last_login_at = now(), updated_at = now() "
            "WHERE provider_id = :pid AND subject = :sub"), {"pid": provider_id, "sub": subject})
        await session.commit()
        return await _load_user_data(session, ident["user_id"]), "existing"

    # Domain allow-list is enforced before any link/create.
    if not email_domain_allowed(email, provider.get("allowed_domains") or []):
        raise SsoError("domain_not_allowed", 403)

    # 2. Existing local user in the SAME tenant, by email -> link.
    urow = (await session.execute(text(
        "SELECT id FROM users WHERE tenant_id = :tid AND lower(email) = :email"
    ), {"tid": tenant_id, "email": email})).mappings().first()
    if urow:
        await _insert_identity(session, tenant_id, urow["id"], provider_id, issuer, subject, email, verified, claims)
        return await _load_user_data(session, urow["id"]), "linked"

    # 3. JIT provisioning (if enabled) — analyst-only, unusable password.
    if not provider.get("jit_provisioning_enabled"):
        raise SsoError("user_not_provisioned", 403)
    from app.services.auth_service import get_password_hash
    role = clamp_jit_role(provider.get("default_role"))
    given = str(claims.get("given_name") or (claims.get("name") or email).split(" ")[0] or "SSO")[:100]
    family = str(claims.get("family_name") or "User")[:100]
    unusable_pw = get_password_hash("sso-no-password-" + gen_token(24))
    new = (await session.execute(text("""
        INSERT INTO users (email, password_hash, first_name, last_name, role, status,
                           tenant_id, email_verified)
        VALUES (:email, :pw, :fn, :ln, CAST(:role AS user_role), 'active', :tid, :ev)
        RETURNING id
    """), {"email": email, "pw": unusable_pw, "fn": given, "ln": family,
           "role": role, "tid": tenant_id, "ev": verified})).mappings().first()
    await _insert_identity(session, tenant_id, new["id"], provider_id, issuer, subject, email, verified, claims)
    return await _load_user_data(session, new["id"]), "jit"


async def _insert_identity(session, tenant_id, user_id, provider_id, issuer, subject, email, verified, claims):
    import json
    # Only store non-sensitive claim subset (never tokens).
    safe_claims = {k: claims.get(k) for k in ("iss", "sub", "aud", "email", "email_verified",
                                              "name", "given_name", "family_name", "amr", "acr")
                   if k in claims}
    await session.execute(text("""
        INSERT INTO external_identities
            (tenant_id, user_id, provider_id, issuer, subject, email, email_verified, last_login_at, claims)
        VALUES (:tid, :uid, :pid, :iss, :sub, :email, :ev, now(), CAST(:claims AS jsonb))
        ON CONFLICT (provider_id, subject) DO UPDATE SET last_login_at = now(), updated_at = now()
    """), {"tid": tenant_id, "uid": user_id, "pid": provider_id, "iss": issuer,
           "sub": subject, "email": email, "ev": verified, "claims": json.dumps(safe_claims)})
    await session.commit()
