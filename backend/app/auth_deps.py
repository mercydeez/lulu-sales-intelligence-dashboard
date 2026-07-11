"""
Authentication & authorization dependency layer.

WHY THIS MODULE EXISTS (dependency direction):
`get_current_user` / `require_role` / `require_permission` and the store-scope
helpers are cross-cutting infrastructure consumed by ~40 route modules, the SSE
stream, and platform services. They used to live in `app.routes.auth`, which
made every router (and even some services) import another *route module* —
the web layer depending on itself sideways. They now live here, below the
routes: everything imports `app.auth_deps`, and `app.routes.auth` re-exports
every name so the pre-split import path keeps working (backwards compatible —
that path is exercised by the test suite on purpose).

Module-level imports stay minimal (config + auth_service, exactly as before);
optional/heavier collaborators are imported function-scope, mirroring the
original code, so importing this module never drags in the web layer.
"""
from fastapi import HTTPException, Depends, Request, Response, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime, timezone

from app.services.auth_service import AuthService, decode_token
from app.config import get_settings

security = HTTPBearer(auto_error=False)


class CurrentUser(TypedDict, total=False):
    """Shape of the authenticated principal returned by `get_current_user`
    (see AuthService.get_user_by_id + the aggregated `permissions` dict).

    It IS a plain dict at runtime, so the many existing `current_user: dict`
    annotations stay correct; new code should prefer this type.
    """
    id: int
    email: str
    role: str
    status: str
    first_name: Optional[str]
    last_name: Optional[str]
    job_title: Optional[str]
    department: Optional[str]
    tenant_id: Optional[int]
    email_verified: bool
    is_platform_developer: bool
    last_login_at: Optional[datetime]
    created_at: Optional[datetime]
    permissions: Dict[str, Any]


class LoginResponse(BaseModel):
    """Token response contract shared by the password login and SSO callback."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


# =============================================================================
# httpOnly COOKIE AUTH
# -----------------------------------------------------------------------------
# Tokens are returned in the JSON body (legacy Bearer flow, unchanged) AND set
# as httpOnly cookies. The cookies let the browser authenticate without exposing
# the token to JS — closing the "tokens in localStorage are XSS-exfiltratable"
# gap. Cookies ignore port, so a cookie set by the API (:8000) is also sent to
# the web app (:3000) on the same host. Since E0-5 the browser uses the cookie as
# its ONLY transport (no localStorage tokens), so state-changing browser requests
# go through the double-submit CSRF path (X-CSRF-Token header); API clients using
# the Authorization: Bearer header remain CSRF-exempt (see CSRFMiddleware).
# =============================================================================

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
_REFRESH_MAX_AGE = 7 * 24 * 60 * 60  # 7 days (matches REFRESH_TOKEN_EXPIRE_DAYS)


def _cookie_kwargs() -> dict:
    """Shared cookie security attributes, environment-aware."""
    settings = get_settings()
    is_prod = settings.environment.lower() in ("production", "prod", "staging")
    return {
        "httponly": True,
        "secure": is_prod,           # require HTTPS in prod; allow http on localhost
        "samesite": "lax",           # sent on top-level nav + same-site fetches
        "path": "/",
    }


def set_auth_cookies(response: Response, tokens) -> None:
    """Write access + refresh tokens as httpOnly cookies on the response."""
    kw = _cookie_kwargs()
    response.set_cookie(ACCESS_COOKIE, tokens.access_token, max_age=tokens.expires_in, **kw)
    response.set_cookie(REFRESH_COOKIE, tokens.refresh_token, max_age=_REFRESH_MAX_AGE, **kw)


def clear_auth_cookies(response: Response) -> None:
    """Remove both auth cookies (logout)."""
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


# =============================================================================
# DEPENDENCY - Get Current User
# =============================================================================

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    """Dependency to get current authenticated user.

    Accepts the access token from the `Authorization: Bearer` header (API /
    legacy clients) OR the httpOnly `access_token` cookie (browser / SSR).
    """
    token = credentials.credentials if credentials else request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_data = decode_token(token)
    if not token_data:
        from app.services.security_events import record_event
        await record_event("token_invalid", request=request,
                           detail="Rejected an invalid, expired, or wrong-type token")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check token expiration
    if token_data.exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Token has expired")

    # Session revocation epoch: a password reset (or admin action) invalidates all
    # access tokens issued before the cutoff. Reject anything older.
    if token_data.iat is not None:
        from app.services.auth_service import tokens_revoked_before
        cutoff = await tokens_revoked_before(token_data.user_id)
        if cutoff is not None and token_data.iat < cutoff:
            raise HTTPException(status_code=401, detail="Session has been revoked")

    # Get fresh user data
    user = await AuthService.get_user_by_id(token_data.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user['status'] != 'active':
        raise HTTPException(status_code=401, detail="Account is not active")

    # Token tenant tampering: a token claiming a different tenant than the user's
    # real one is a critical signal (stolen/forged/stale token). Reject it.
    if token_data.tenant_id is not None and user.get('tenant_id') is not None \
            and token_data.tenant_id != user['tenant_id']:
        from app.services.security_events import record_event
        await record_event("token_tenant_mismatch", request=request,
                           tenant_id=user['tenant_id'], actor_user_id=user['id'],
                           actor_email=user.get('email'),
                           detail=f"Token tenant claim {token_data.tenant_id} != user tenant {user['tenant_id']}",
                           evidence={"token_tenant": token_data.tenant_id, "user_tenant": user['tenant_id']})
        raise HTTPException(status_code=401, detail="Invalid token")

    # Bind the active tenant for this request (drives the RLS GUC, B2).
    try:
        from app.services.database import tenant_context
        tenant_context.set(user.get('tenant_id') or 1)
    except Exception:
        pass

    # Tenant lifecycle gate (Phase 2): a suspended/cancelled/deleted tenant is
    # blocked from product/API. Super-admins bypass so operators can still manage
    # the tenant (e.g. reactivate it). Fails OPEN on lookup error — never lock
    # everyone out because of a transient DB hiccup.
    if user.get('role') != 'super_admin':
        try:
            from app.services.database import async_session
            from app.services.tenant_lifecycle import get_tenant_status, is_access_allowed
            async with async_session() as _s:
                _status = await get_tenant_status(_s, user.get('tenant_id') or 1)
            if not is_access_allowed(_status):
                raise HTTPException(
                    status_code=403,
                    detail=f"Tenant access is {_status}. Contact support.")
        except HTTPException:
            raise
        except Exception:
            pass

    # Surface tenant/user ids in structured logs (numeric ids only — no secrets).
    try:
        from app.config import log_tenant_ctx, log_user_ctx
        log_tenant_ctx.set(str(user.get('tenant_id') or '-'))
        log_user_ctx.set(str(user.get('id') or '-'))
    except Exception:
        pass

    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[CurrentUser]:
    """Optional user authentication (Bearer header or httpOnly cookie)."""
    token = credentials.credentials if credentials else request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None

    token_data = decode_token(token)
    if not token_data or token_data.exp < datetime.now(timezone.utc):
        return None

    return await AuthService.get_user_by_id(token_data.user_id)


def require_role(*roles: str):
    """Dependency factory to require specific roles"""
    async def role_checker(request: Request, user: dict = Depends(get_current_user)) -> CurrentUser:
        if user['role'] not in roles:
            from app.services.security_events import record_event
            await record_event("role_denied", request=request,
                               tenant_id=user.get('tenant_id'), actor_user_id=user.get('id'),
                               actor_email=user.get('email'),
                               detail=f"{user.get('email')} (role {user['role']}) was denied {request.url.path} — requires {', '.join(roles)}",
                               evidence={"have_role": user['role'], "need_roles": list(roles)})
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(roles)}"
            )
        return user
    return role_checker


def require_permission(permission: str):
    """Dependency factory to require specific permission"""
    async def permission_checker(request: Request, user: dict = Depends(get_current_user)) -> CurrentUser:
        if not user.get('permissions', {}).get(permission):
            from app.services.security_events import record_event
            await record_event("permission_denied", request=request,
                               tenant_id=user.get('tenant_id'), actor_user_id=user.get('id'),
                               actor_email=user.get('email'),
                               detail=f"{user.get('email')} was denied {request.url.path} — missing '{permission}'",
                               evidence={"missing_permission": permission})
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Missing permission: {permission}"
            )
        return user
    return permission_checker


# =============================================================================
# STORE-SCOPE HELPERS
# =============================================================================

def filter_by_user_stores(user: dict) -> List[int]:
    """Helper to get store IDs user can access"""
    return user.get('permissions', {}).get('accessible_stores', [])


def can_access_store(user: dict, store_id: int) -> bool:
    """Check if user can access a specific store"""
    if user['role'] == 'super_admin':
        return True
    accessible = user.get('permissions', {}).get('accessible_stores', [])
    return store_id in accessible


def get_accessible_store_ids(user: dict) -> List[int]:
    """Get list of store IDs the user has access to. Returns empty list for super_admin (meaning all)."""
    if user['role'] == 'super_admin':
        return []  # empty = no filter needed (all stores)
    return user.get('permissions', {}).get('accessible_stores', [])


# =============================================================================
# SSE STREAM TICKET DEPENDENCY (short-lived token for EventSource connections)
# =============================================================================

async def get_current_user_from_ticket(
    ticket: Optional[str] = Query(None, description="Short-lived SSE stream ticket")
) -> CurrentUser:
    """Dependency to validate the short-lived ticket for SSE streams"""
    if not ticket:
        raise HTTPException(status_code=401, detail="Missing stream ticket")

    # Verify that it's a valid ticket token (RS256/HS256 via the key provider —
    # E5-6; no direct symmetric-secret decode here).
    from jose import JWTError
    from app.services.jwt_keys import get_key_provider

    try:
        payload = get_key_provider().verify(ticket)
        if not payload.get("ticket"):
            raise HTTPException(status_code=401, detail="Invalid stream ticket")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired stream ticket")

    token_data = decode_token(ticket)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid stream ticket")

    if token_data.exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Stream ticket expired")

    user = await AuthService.get_user_by_id(token_data.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user['status'] != 'active':
        raise HTTPException(status_code=401, detail="Account is not active")

    return user
