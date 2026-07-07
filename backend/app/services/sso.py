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
    """Public-safe provider metadata (NO client_secret_env unless admin). The
    `login_type` label is honest: 'oidc' or 'managed_saml_bridge' (never claims
    native SAML)."""
    out = {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "provider_type": provider.get("provider_type"),
        "login_type": login_type_label(provider.get("provider_type")),
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


# E5-1b: which provider_types can drive the OIDC login flow. A managed SAML bridge
# (workos_saml) speaks OIDC to us, so it reuses the OIDC flow when enabled. Native
# `saml` is NEVER login-usable (fail-closed).
MANAGED_BRIDGE_TYPES = {"workos_saml"}
NATIVE_SAML_TYPES = {"saml"}


def oidc_compatible_types(settings=None) -> List[str]:
    """Provider types that may complete the OIDC authorization-code flow."""
    s = settings or get_settings()
    types = ["oidc"]
    if s.sso_managed_saml_bridge_enabled:
        types.append("workos_saml")
    return types


def is_managed_bridge(provider_type: Optional[str]) -> bool:
    return (provider_type or "") in MANAGED_BRIDGE_TYPES


def login_type_label(provider_type: Optional[str]) -> str:
    """Honest label for public metadata."""
    if provider_type in MANAGED_BRIDGE_TYPES:
        return "managed_saml_bridge"
    if provider_type in NATIVE_SAML_TYPES:
        return "native_saml_unsupported"
    return "oidc"


def classify_login_provider(provider_type: Optional[str], settings=None) -> str:
    """How a provider_type resolves for LOGIN:
    'oidc_ok' | 'bridge_ok' | 'bridge_disabled' | 'native_saml' | 'unsupported'."""
    s = settings or get_settings()
    if provider_type == "oidc":
        return "oidc_ok"
    if provider_type in MANAGED_BRIDGE_TYPES:
        return "bridge_ok" if s.sso_managed_saml_bridge_enabled else "bridge_disabled"
    if provider_type in NATIVE_SAML_TYPES:
        return "native_saml"
    return "unsupported"


async def get_oidc_provider(
    session: AsyncSession,
    *,
    tenant_id: Optional[int] = None,
    tenant_slug: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load one ENABLED, OIDC-compatible provider (oidc, or managed bridge when
    enabled), scoped to a tenant. Native SAML is never returned here."""
    types = oidc_compatible_types()
    where = ["p.enabled = true", "p.provider_type = ANY(:types)"]
    params: Dict[str, Any] = {"types": types}
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
    """Load an ENABLED, OIDC-compatible provider by id (callback via the state row)."""
    row = (await session.execute(text(
        "SELECT * FROM tenant_sso_providers WHERE id = :id AND enabled = true "
        "AND provider_type = ANY(:types)"
    ), {"id": provider_id, "types": oidc_compatible_types()})).mappings().first()
    return dict(row) if row else None


async def get_enabled_provider(session: AsyncSession, *, tenant_id: Optional[int] = None,
                               tenant_slug: Optional[str] = None,
                               provider_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load ANY enabled provider (any type) — used to give a precise login error
    (native SAML rejected / bridge disabled) when get_oidc_provider returns None."""
    where = ["p.enabled = true"]
    params: Dict[str, Any] = {}
    if tenant_id is not None:
        where.append("p.tenant_id = :tid"); params["tid"] = tenant_id
    elif tenant_slug is not None:
        where.append("p.tenant_id = (SELECT id FROM tenants WHERE slug = :slug)"); params["slug"] = tenant_slug
    else:
        return None
    if provider_name:
        where.append("p.name = :pname"); params["pname"] = provider_name
    sql = "SELECT p.* FROM tenant_sso_providers p WHERE " + " AND ".join(where) + " ORDER BY p.id LIMIT 1"
    row = (await session.execute(text(sql), params)).mappings().first()
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
    # Only OFFER providers that can actually complete a login: OIDC, or a managed
    # bridge when enabled. Native SAML / disabled bridges are never offered.
    usable = {t for t in oidc_compatible_types()}
    return [public_provider_view(dict(r)) for r in rows if r["provider_type"] in usable]


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


# ===========================================================================
# E5-1b — Provider validation + tenant-admin provider operations.
# ===========================================================================
import re as _re

_ENV_NAME_RE = _re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def is_env_var_name(value) -> bool:
    """True if `value` looks like an ENV VAR NAME (e.g. SSO_AZURE_CLIENT_SECRET),
    not a secret value."""
    return bool(value) and bool(_ENV_NAME_RE.match(str(value)))


def looks_like_secret_value(value) -> bool:
    """Heuristic: does `value` look like an actual secret / URL / JWT / long token
    rather than an env var name? Used to reject a secret pasted into
    client_secret_env."""
    if not value:
        return False
    s = str(value)
    if "://" in s:
        return True                      # a URL
    if s.count(".") >= 2 and len(s) > 30:
        return True                      # JWT-ish
    if len(s) >= 24 and not is_env_var_name(s):
        return True                      # long random token, not an env name
    return False


def validate_provider_configuration(provider: Dict[str, Any], settings=None, *, live: bool = False) -> Dict[str, Any]:
    """Validate a provider config. Pure (no network) — `live` only checks that the
    secret ENV VAR exists via os.environ. Returns safe diagnostics (NO secrets)."""
    s = settings or get_settings()
    errors: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {}

    ptype = provider.get("provider_type")
    checks["provider_type"] = ptype
    cl = classify_login_provider(ptype, s)
    if cl == "native_saml":
        errors.append("native_saml_not_implemented")
    elif cl == "unsupported":
        errors.append(f"unsupported_provider_type:{ptype}")
    elif cl == "bridge_disabled":
        warnings.append("managed_saml_bridge_disabled")  # valid draft; login stays off until enabled

    for f in ("name", "issuer", "authorization_endpoint", "token_endpoint", "jwks_uri", "client_id"):
        if not provider.get(f):
            errors.append(f"missing:{f}")
        else:
            checks[f] = "present"

    cse = provider.get("client_secret_env")
    if not cse:
        errors.append("missing:client_secret_env")
    elif looks_like_secret_value(cse) or not is_env_var_name(cse):
        errors.append("client_secret_env_must_be_env_name")  # never store a raw secret
    else:
        checks["client_secret_env"] = "env_name_ok"

    scopes = (provider.get("scopes") or "")
    if "openid" not in str(scopes).split():
        errors.append("scopes_missing_openid")

    ad = provider.get("allowed_domains")
    if ad is not None and not isinstance(ad, list):
        errors.append("allowed_domains_not_list")
    if provider.get("jit_provisioning_enabled") and not ad:
        errors.append("jit_requires_allowed_domains")

    role = provider.get("default_role") or "analyst"
    if clamp_jit_role(role) != str(role).lower():
        errors.append("privileged_default_role")
    else:
        checks["default_role"] = "safe"

    prod = s.environment in ("production", "staging")
    for f in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
        u = provider.get(f)
        if not u:
            continue
        if prod and not str(u).startswith("https://"):
            errors.append(f"insecure_url:{f}")
        elif not prod and not (str(u).startswith("https://") or str(u).startswith("http://localhost")
                               or str(u).startswith("http://127.0.0.1")):
            warnings.append(f"nonstandard_url:{f}")

    if live and cse and is_env_var_name(cse) and not os.environ.get(cse):
        errors.append("secret_env_missing")

    return {
        "ok": len(errors) == 0,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "provider_type": ptype,
        "managed_bridge": is_managed_bridge(ptype),
    }


def admin_provider_view(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Admin-safe provider view. NEVER returns client_secret_env's value/name —
    only whether it is configured."""
    meta = provider.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "provider_type": provider.get("provider_type"),
        "login_type": login_type_label(provider.get("provider_type")),
        "managed_bridge": is_managed_bridge(provider.get("provider_type")),
        "enabled": provider.get("enabled"),
        "status": meta.get("status", "draft"),
        "issuer": provider.get("issuer"),
        "client_id": provider.get("client_id"),
        "scopes": provider.get("scopes"),
        "allowed_domains": provider.get("allowed_domains"),
        "jit_provisioning_enabled": provider.get("jit_provisioning_enabled"),
        "default_role": provider.get("default_role"),
        "trust_idp_mfa": provider.get("trust_idp_mfa"),
        "client_secret_env_configured": bool(provider.get("client_secret_env")),
        "last_validated_at": meta.get("last_validated_at"),
        "last_validation_error": meta.get("last_validation_error"),
    }


import json  # noqa: E402  (used by admin_provider_view + metadata writes)

# safe provider_types the admin API may CREATE (native saml is never login-usable)
_CREATABLE_TYPES = {"oidc", "workos_saml"}


async def admin_list_providers(session: AsyncSession, tenant_id: int) -> List[Dict[str, Any]]:
    rows = (await session.execute(text(
        "SELECT * FROM tenant_sso_providers WHERE tenant_id = :tid ORDER BY id"
    ), {"tid": tenant_id})).mappings().all()
    return [admin_provider_view(dict(r)) for r in rows]


async def admin_get_provider(session: AsyncSession, tenant_id: int, provider_id: int) -> Optional[Dict[str, Any]]:
    r = (await session.execute(text(
        "SELECT * FROM tenant_sso_providers WHERE id = :id AND tenant_id = :tid"
    ), {"id": provider_id, "tid": tenant_id})).mappings().first()
    return dict(r) if r else None


async def _write_metadata(session, tenant_id, provider_id, updates: Dict[str, Any]) -> None:
    cur = await admin_get_provider(session, tenant_id, provider_id)
    meta = cur.get("metadata") if cur else {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = {**(meta or {}), **updates}
    await session.execute(text(
        "UPDATE tenant_sso_providers SET metadata = CAST(:m AS jsonb), updated_at = now() "
        "WHERE id = :id AND tenant_id = :tid"), {"m": json.dumps(meta), "id": provider_id, "tid": tenant_id})


async def admin_create_provider(session: AsyncSession, tenant_id: int, body: Dict[str, Any],
                                created_by: int) -> Dict[str, Any]:
    ptype = body.get("provider_type")
    if ptype not in _CREATABLE_TYPES:
        if ptype in NATIVE_SAML_TYPES:
            raise SsoError("native_saml_not_supported", 400,
                           "Native SAML login is not implemented. Configure a managed "
                           "SAML/OIDC bridge provider (provider_type='workos_saml') instead.")
        raise SsoError("unsupported_provider_type", 400)

    name = (body.get("name") or "").strip()
    if not name:
        raise SsoError("missing_name", 400)
    dup = (await session.execute(text(
        "SELECT id FROM tenant_sso_providers WHERE tenant_id = :tid AND name = :n"
    ), {"tid": tenant_id, "n": name})).mappings().first()
    if dup:
        raise SsoError("duplicate_provider_name", 409)

    role = clamp_jit_role(body.get("default_role") or "analyst")
    if (body.get("default_role") or "analyst").lower() in _ADMIN_ROLES:
        raise SsoError("privileged_default_role", 400,
                       "default_role cannot be a privileged/admin role")

    draft = {
        "provider_type": ptype, "name": name, "issuer": body.get("issuer"),
        "authorization_endpoint": body.get("authorization_endpoint"),
        "token_endpoint": body.get("token_endpoint"), "jwks_uri": body.get("jwks_uri"),
        "client_id": body.get("client_id"), "client_secret_env": body.get("client_secret_env"),
        "scopes": body.get("scopes") or "openid email profile",
        "allowed_domains": body.get("allowed_domains") or [],
        "jit_provisioning_enabled": bool(body.get("jit_provisioning_enabled")),
        "default_role": role, "trust_idp_mfa": bool(body.get("trust_idp_mfa")),
    }
    # Validate config up front — reject unsafe URLs / secret-in-env-name / etc.
    diag = validate_provider_configuration(draft, get_settings(), live=False)
    # A disabled managed bridge is a valid DRAFT (warning only); block only on errors.
    if diag["errors"]:
        raise SsoError("invalid_provider_config", 400, "; ".join(diag["errors"]))

    row = (await session.execute(text("""
        INSERT INTO tenant_sso_providers
            (tenant_id, provider_type, name, enabled, issuer, authorization_endpoint,
             token_endpoint, jwks_uri, client_id, client_secret_env, scopes, allowed_domains,
             jit_provisioning_enabled, default_role, trust_idp_mfa, metadata)
        VALUES (:tid, :pt, :name, false, :iss, :auth, :tok, :jwks, :cid, :cse, :scopes,
                CAST(:ad AS jsonb), :jit, CAST(:role AS user_role), :mfa, CAST(:meta AS jsonb))
        RETURNING id
    """), {
        "tid": tenant_id, "pt": ptype, "name": name, "iss": draft["issuer"],
        "auth": draft["authorization_endpoint"], "tok": draft["token_endpoint"], "jwks": draft["jwks_uri"],
        "cid": draft["client_id"], "cse": draft["client_secret_env"], "scopes": draft["scopes"],
        "ad": json.dumps(draft["allowed_domains"]), "jit": draft["jit_provisioning_enabled"],
        "role": role, "mfa": draft["trust_idp_mfa"],
        "meta": json.dumps({"status": "draft", "created_by": created_by}),
    })).mappings().first()
    await session.commit()
    return admin_provider_view(await admin_get_provider(session, tenant_id, row["id"]))


_UPDATABLE_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri",
                     "client_id", "client_secret_env", "scopes", "jit_provisioning_enabled",
                     "trust_idp_mfa")


async def admin_update_provider(session: AsyncSession, tenant_id: int, provider_id: int,
                                body: Dict[str, Any], updated_by: int) -> Dict[str, Any]:
    prov = await admin_get_provider(session, tenant_id, provider_id)
    if not prov:
        raise SsoError("provider_not_found", 404)

    sets, params = [], {"id": provider_id, "tid": tenant_id}
    for f in _UPDATABLE_FIELDS:
        if f in body:
            sets.append(f"{f} = :{f}")
            params[f] = body[f]
    if "allowed_domains" in body:
        if not isinstance(body["allowed_domains"], list):
            raise SsoError("allowed_domains_not_list", 400)
        sets.append("allowed_domains = CAST(:ad AS jsonb)")
        params["ad"] = json.dumps(body["allowed_domains"])
    if "default_role" in body:
        if (body["default_role"] or "").lower() in _ADMIN_ROLES:
            raise SsoError("privileged_default_role", 400)
        sets.append("default_role = CAST(:role AS user_role)")
        params["role"] = clamp_jit_role(body["default_role"])
    # tenant_id and provider_type are NOT updatable.
    if not sets:
        return prov
    await session.execute(text(
        f"UPDATE tenant_sso_providers SET {', '.join(sets)}, updated_at = now() "
        f"WHERE id = :id AND tenant_id = :tid"), params)
    # config changed -> require re-validation before it can be (re)enabled
    await _write_metadata(session, tenant_id, provider_id, {"status": "draft", "updated_by": updated_by})
    await session.commit()
    return admin_provider_view(await admin_get_provider(session, tenant_id, provider_id))


async def admin_validate_provider(session: AsyncSession, tenant_id: int, provider_id: int,
                                  *, live: Optional[bool] = None) -> Dict[str, Any]:
    prov = await admin_get_provider(session, tenant_id, provider_id)
    if not prov:
        raise SsoError("provider_not_found", 404)
    s = get_settings()
    do_live = s.sso_live_provider_validation_enabled if live is None else live
    diag = validate_provider_configuration(prov, s, live=do_live)
    from datetime import datetime as _dt, timezone as _tz
    await _write_metadata(session, tenant_id, provider_id, {
        "status": "valid" if diag["ok"] else "invalid",
        "last_validated_at": _dt.now(_tz.utc).isoformat(),
        "last_validation_error": None if diag["ok"] else "; ".join(diag["errors"]),
    })
    await session.commit()
    return diag


async def admin_enable_provider(session: AsyncSession, tenant_id: int, provider_id: int) -> Dict[str, Any]:
    prov = await admin_get_provider(session, tenant_id, provider_id)
    if not prov:
        raise SsoError("provider_not_found", 404)
    # Re-validate now; only a VALID config may be enabled.
    diag = validate_provider_configuration(prov, get_settings(), live=False)
    if not diag["ok"]:
        raise SsoError("cannot_enable_invalid_provider", 400, "; ".join(diag["errors"]))
    await session.execute(text(
        "UPDATE tenant_sso_providers SET enabled = true, updated_at = now() WHERE id = :id AND tenant_id = :tid"),
        {"id": provider_id, "tid": tenant_id})
    await _write_metadata(session, tenant_id, provider_id, {"status": "valid"})
    await session.commit()
    return admin_provider_view(await admin_get_provider(session, tenant_id, provider_id))


async def admin_disable_provider(session: AsyncSession, tenant_id: int, provider_id: int,
                                 disabled_by: int) -> Dict[str, Any]:
    prov = await admin_get_provider(session, tenant_id, provider_id)
    if not prov:
        raise SsoError("provider_not_found", 404)
    from datetime import datetime as _dt, timezone as _tz
    await session.execute(text(
        "UPDATE tenant_sso_providers SET enabled = false, updated_at = now() WHERE id = :id AND tenant_id = :tid"),
        {"id": provider_id, "tid": tenant_id})
    await _write_metadata(session, tenant_id, provider_id,
                          {"status": "disabled", "disabled_at": _dt.now(_tz.utc).isoformat(),
                           "disabled_by": disabled_by})
    await session.commit()
    return admin_provider_view(await admin_get_provider(session, tenant_id, provider_id))
