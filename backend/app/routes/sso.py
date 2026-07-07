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
        # Give a precise, safe error: native SAML is rejected; a disabled managed
        # bridge is reported as such; otherwise not-found.
        any_prov = await sso_service.get_enabled_provider(
            db, tenant_id=body.tenant_id, tenant_slug=body.tenant_slug, provider_name=body.provider_name)
        if any_prov:
            cls = sso_service.classify_login_provider(any_prov["provider_type"], s)
            if cls == "native_saml":
                await _event("sso_native_saml_rejected", request, severity="medium", category="auth",
                             tenant_id=any_prov["tenant_id"],
                             detail=f"Native SAML login rejected for provider '{any_prov['name']}'")
                raise HTTPException(
                    status_code=400,
                    detail="Native SAML login is not implemented. Configure a managed "
                           "SAML/OIDC bridge provider instead.")
            if cls == "bridge_disabled":
                raise HTTPException(status_code=400, detail="managed_saml_bridge_disabled")
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
    # Managed SAML bridge reuses the OIDC flow — label the event honestly.
    if sso_service.is_managed_bridge(provider["provider_type"]):
        await _event("sso_managed_saml_bridge_started", request, severity="low", category="audit",
                     tenant_id=provider["tenant_id"],
                     detail=f"Managed SAML bridge login started for provider '{provider['name']}'")
    else:
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


# ===========================================================================
# E5-1b — Tenant-admin SSO provider operations (/api/sso/admin/providers).
# Local JWT auth, admin-level role, tenant-scoped. Never returns secrets.
# ===========================================================================
from fastapi import Body  # noqa: E402
from app.routes.auth import require_role  # noqa: E402

_SSO_ADMIN = require_role("super_admin", "admin", "owner")


def _sso_admin_guard():
    if not get_settings().sso_admin_config_enabled:
        raise HTTPException(status_code=404, detail="sso_admin_config_disabled")


def _map_sso_error(e: SsoError):
    raise HTTPException(status_code=e.status, detail=e.message)


class ProviderCreate(BaseModel):
    name: str
    provider_type: str = "oidc"
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    client_id: Optional[str] = None
    client_secret_env: Optional[str] = None
    scopes: Optional[str] = None
    allowed_domains: Optional[list] = None
    jit_provisioning_enabled: Optional[bool] = False
    default_role: Optional[str] = "analyst"
    trust_idp_mfa: Optional[bool] = False


class ProviderUpdate(BaseModel):
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    client_id: Optional[str] = None
    client_secret_env: Optional[str] = None
    scopes: Optional[str] = None
    allowed_domains: Optional[list] = None
    jit_provisioning_enabled: Optional[bool] = None
    default_role: Optional[str] = None
    trust_idp_mfa: Optional[bool] = None


@router.get("/admin/providers")
async def admin_list_providers(request: Request, db: AsyncSession = Depends(get_db),
                               user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    return {"providers": await sso_service.admin_list_providers(db, tenant_id)}


@router.post("/admin/providers", status_code=201)
async def admin_create_provider(body: ProviderCreate, request: Request,
                                db: AsyncSession = Depends(get_db), user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    try:
        view = await sso_service.admin_create_provider(db, tenant_id, body.model_dump(), user["id"])
    except SsoError as e:
        _map_sso_error(e)
    await _event("sso_provider_created", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SSO provider '{body.name}' ({body.provider_type}) created (id={view['id']})")
    return view


@router.patch("/admin/providers/{provider_id}")
async def admin_update_provider(provider_id: int, body: ProviderUpdate, request: Request,
                                db: AsyncSession = Depends(get_db), user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        view = await sso_service.admin_update_provider(db, tenant_id, provider_id, updates, user["id"])
    except SsoError as e:
        _map_sso_error(e)
    await _event("sso_provider_updated", request, severity="low", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SSO provider {provider_id} updated")
    return view


@router.post("/admin/providers/{provider_id}/validate")
async def admin_validate_provider(provider_id: int, request: Request,
                                  db: AsyncSession = Depends(get_db), user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    try:
        diag = await sso_service.admin_validate_provider(db, tenant_id, provider_id)
    except SsoError as e:
        _map_sso_error(e)
    evt = "sso_provider_validated" if diag["ok"] else "sso_provider_validation_failed"
    sev = "low" if diag["ok"] else "medium"
    await _event(evt, request, severity=sev, category="audit", tenant_id=tenant_id,
                 actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SSO provider {provider_id} validation: {'ok' if diag['ok'] else 'failed'}")
    return diag  # safe diagnostics (no secrets)


@router.post("/admin/providers/{provider_id}/enable")
async def admin_enable_provider(provider_id: int, request: Request,
                                db: AsyncSession = Depends(get_db), user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    try:
        view = await sso_service.admin_enable_provider(db, tenant_id, provider_id)
    except SsoError as e:
        _map_sso_error(e)
    await _event("sso_provider_enabled", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SSO provider {provider_id} enabled")
    return view


@router.post("/admin/providers/{provider_id}/disable")
async def admin_disable_provider(provider_id: int, request: Request,
                                 db: AsyncSession = Depends(get_db), user: dict = Depends(_SSO_ADMIN)):
    _sso_admin_guard()
    tenant_id = user.get("tenant_id") or 1
    try:
        view = await sso_service.admin_disable_provider(db, tenant_id, provider_id, user["id"])
    except SsoError as e:
        _map_sso_error(e)
    await _event("sso_provider_disabled", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SSO provider {provider_id} disabled")
    return view
