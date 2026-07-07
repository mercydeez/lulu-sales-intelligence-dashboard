"""
SSO API routes (E5-1a) — OIDC-first enterprise login. Mounted at /api/sso.

Endpoints:
  GET  /api/sso/providers      — public-safe enabled providers for a tenant/domain
  POST /api/sso/oidc/start     — begin the OIDC authorization-code flow (no login)
  GET  /api/sso/oidc/callback  — IdP redirect target; issues local tokens on success

Provider CONFIG is created via SQL/admin (see docs/security/SSO.md) — no public
write endpoints here. All token/secret material is handled in services/sso.py and
never logged. Admin MFA policy is enforced here on the same footing as local login.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, logger
from app.services.database import get_db
from app.services import sso as sso_service
from app.services.sso import SsoError

router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    ip = request.client.host if request.client else None
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            ip = fwd.split(",")[0].strip()
    return ip


def _callback_redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/sso/oidc/callback"


async def _event(event_type, request, **kw):
    from app.services.security_events import record_event
    try:
        await record_event(event_type, request=request, **kw)
    except Exception:  # audit must never break the auth flow
        logger.debug("sso event record failed (non-fatal)")


# ---------------------------------------------------------------------------
class StartRequest(BaseModel):
    tenant_slug: Optional[str] = None
    tenant_id: Optional[int] = None
    provider_name: Optional[str] = None
    return_to: Optional[str] = None


@router.get("/providers")
async def list_providers(
    tenant_slug: Optional[str] = None,
    email_domain: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Public-safe list of enabled SSO providers for a tenant slug or email domain.
    Returns NO secrets (never client_secret_env)."""
    s = get_settings()
    if not (s.sso_enabled and s.sso_oidc_enabled):
        return {"sso_enabled": False, "providers": []}
    if not tenant_slug and not email_domain:
        raise HTTPException(status_code=400, detail="tenant_slug or email_domain is required")
    providers = await sso_service.list_providers_public(db, tenant_slug=tenant_slug, email_domain=email_domain)
    return {"sso_enabled": True, "providers": providers}


@router.post("/oidc/start")
async def oidc_start(body: StartRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Begin OIDC login: returns an authorization_url to redirect the browser to.
    Does not require an existing session."""
    s = get_settings()
    if not (s.sso_enabled and s.sso_oidc_enabled):
        raise HTTPException(status_code=404, detail="sso_disabled")

    if not sso_service.validate_return_to(body.return_to, s.sso_allowed_redirect_hosts, s.sso_max_return_to_length):
        raise HTTPException(status_code=400, detail="invalid_return_to")

    provider = await sso_service.get_oidc_provider(
        db, tenant_id=body.tenant_id, tenant_slug=body.tenant_slug, provider_name=body.provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="provider_not_found")

    redirect_uri = _callback_redirect_uri(request)
    try:
        state, nonce = await sso_service.create_auth_state(
            db, provider, redirect_uri, body.return_to, _client_ip(request),
            request.headers.get("User-Agent"))
    except Exception:
        logger.error("sso start failed to persist state")
        raise HTTPException(status_code=500, detail="sso_start_failed")

    url = sso_service.build_authorization_url(provider, redirect_uri, state, nonce)
    await _event("sso_login_started", request, severity="low", category="audit",
                 tenant_id=provider["tenant_id"],
                 detail=f"OIDC login started for provider '{provider['name']}'")
    # NOTE: url contains state/nonce (not secrets) — do not log it.
    return {"authorization_url": url, "expires_in": s.sso_state_ttl_seconds}


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,  # noqa: ARG001 (accepted, not echoed)
    db: AsyncSession = Depends(get_db),
):
    """IdP redirect target. Validates state + ID token, resolves/provisions the
    user, enforces admin MFA, and returns local tokens (same shape as /auth/login)."""
    s = get_settings()
    if not (s.sso_enabled and s.sso_oidc_enabled):
        raise HTTPException(status_code=404, detail="sso_disabled")

    if error:
        await _event("sso_login_failed", request, severity="medium", category="auth",
                     detail=f"IdP returned error: {str(error)[:64]}")
        raise HTTPException(status_code=400, detail="idp_error")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing_code_or_state")

    try:
        # 1. Single-use state.
        st = await sso_service.consume_auth_state(db, state)
        provider = await sso_service.get_provider_by_id(db, st["provider_id"])
        if not provider:
            raise SsoError("provider_not_found", 404)

        # 2. JWKS (from provider.jwks_uri, else discovery).
        jwks_uri = provider.get("jwks_uri")
        if not jwks_uri and provider.get("issuer"):
            disc = await sso_service.discover_oidc(provider["issuer"])
            jwks_uri = disc.get("jwks_uri")
        if not jwks_uri:
            raise SsoError("no_jwks_uri", 500)
        jwks = await sso_service.fetch_jwks(jwks_uri)

        # 3. Exchange code -> tokens, validate the ID token (never logged).
        tokens = await sso_service.exchange_code(provider, code, st["redirect_uri"], None)
        id_token = tokens.get("id_token")
        if not id_token:
            raise SsoError("no_id_token", 401)
        claims = sso_service.decode_and_validate_id_token(
            id_token, provider, jwks, expected_nonce=None,
            require_verified_email=s.sso_require_verified_email)

        # 4. Nonce is stored as a HASH; compare the claim's nonce hash.
        if sso_service.hash_value(str(claims.get("nonce") or "")) != st["nonce_hash"]:
            raise SsoError("nonce_mismatch", 401)

        # 5. Link / JIT.
        user_data, action = await sso_service.resolve_or_provision_user(db, provider, claims)
        if action == "jit":
            await _event("sso_jit_user_created", request, severity="low", category="audit",
                         tenant_id=provider["tenant_id"], actor_user_id=user_data["id"],
                         actor_email=user_data["email"],
                         detail=f"JIT-provisioned '{user_data['role']}' via '{provider['name']}'")
        elif action == "linked":
            await _event("sso_identity_linked", request, severity="low", category="audit",
                         tenant_id=provider["tenant_id"], actor_user_id=user_data["id"],
                         actor_email=user_data["email"],
                         detail=f"Linked identity via '{provider['name']}'")

        # 6. Admin MFA policy — SSO must NOT bypass it (fail-closed).
        block = sso_service.admin_mfa_block_reason(user_data, provider, claims, s.require_mfa_for_admins)
        if block:
            await _event("sso_admin_mfa_required", request, severity="high", category="auth",
                         tenant_id=provider["tenant_id"], actor_user_id=user_data["id"],
                         actor_email=user_data["email"],
                         detail="Admin blocked at SSO login — local MFA required and not enabled")
            raise HTTPException(
                status_code=403,
                detail="Two-factor authentication is required for administrator accounts. "
                       "Enroll local 2FA before signing in via SSO.")

        # 7. Issue local tokens (reuses the standard token/permission path).
        from app.services.auth_service import AuthService
        from app.routes.auth import set_auth_cookies, LoginResponse
        issued = await AuthService.create_tokens(user_data, remember_me=False)
        set_auth_cookies(response, issued)
        await _event("sso_login_succeeded", request, severity="low", category="audit",
                     tenant_id=provider["tenant_id"], actor_user_id=user_data["id"],
                     actor_email=user_data["email"],
                     detail=f"SSO login via '{provider['name']}' (action={action})")
        logger.info(f"SSO login: user={user_data['email']} role={user_data['role']} action={action}")
        return LoginResponse(
            access_token=issued.access_token, refresh_token=issued.refresh_token,
            token_type=issued.token_type, expires_in=issued.expires_in, user=issued.user)

    except HTTPException:
        raise
    except SsoError as e:
        etype = "sso_state_invalid" if e.code.startswith("state_") else "sso_login_failed"
        await _event(etype, request, severity="medium", category="auth",
                     detail=f"SSO callback failed: {e.code}")
        raise HTTPException(status_code=e.status, detail=e.code)
    except Exception:
        logger.error("SSO callback unexpected error")
        await _event("sso_login_failed", request, severity="medium", category="auth",
                     detail="SSO callback failed: internal_error")
        raise HTTPException(status_code=500, detail="sso_callback_failed")
