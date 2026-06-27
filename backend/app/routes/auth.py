"""
Authentication Routes - Login, Logout, Token Management
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, List
from datetime import datetime, timezone

from app.services.auth_service import (
    AuthService, UserLogin, Token, UserResponse, 
    PasswordChange, decode_token, UserCreate
)
from app.config import logger, get_settings

router = APIRouter()
security = HTTPBearer(auto_error=False)


# =============================================================================
# httpOnly COOKIE AUTH
# -----------------------------------------------------------------------------
# Tokens are returned in the JSON body (legacy Bearer flow, unchanged) AND set
# as httpOnly cookies. The cookies let the browser authenticate without exposing
# the token to JS — closing the "tokens in localStorage are XSS-exfiltratable"
# gap. Cookies ignore port, so a cookie set by the API (:8000) is also sent to
# the web app (:3000) on the same host. State-changing browser requests still
# carry the Bearer header, so they stay CSRF-exempt (see CSRFMiddleware); a
# cookie-only POST without the header is subject to double-submit CSRF.
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
) -> dict:
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

    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[dict]:
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
    async def role_checker(request: Request, user: dict = Depends(get_current_user)) -> dict:
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
    async def permission_checker(request: Request, user: dict = Depends(get_current_user)) -> dict:
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
# REQUEST/RESPONSE MODELS
# =============================================================================

class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    email: EmailStr
    password: str
    remember_me: bool = False


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RefreshRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    refresh_token: str


class SignupRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    seed_sample_data: bool = True


class InviteRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: str = "analyst"


class MessageResponse(BaseModel):
    message: str
    success: bool = True


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class TwoFactorCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class TwoFactorVerifyRequest(BaseModel):
    mfa_token: str
    # 6-digit TOTP OR a backup/recovery code like 'a1b2-c3d4'.
    code: str = Field(..., min_length=6, max_length=16)


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/login")
async def login(request: Request, response: Response, login_data: LoginRequest):
    """
    Authenticate user and return JWT tokens
    
    - **email**: User's email address
    - **password**: User's password
    - **remember_me**: If true, token expires in 7 days instead of 30 minutes
    """
    # Get client IP. Only trust X-Forwarded-For behind a known proxy, else it's
    # spoofable and would poison the audit log's recorded login IP.
    ip_address = request.client.host if request.client else None
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip_address = forwarded.split(",")[0].strip()
    
    # Authenticate
    user_data, error = await AuthService.authenticate_user(
        login_data.email, 
        login_data.password,
        ip_address
    )
    
    if error:
        logger.warning(f"Login failed for {login_data.email}: {error}")
        raise HTTPException(status_code=401, detail=error)

    # If the account has 2FA enabled, password alone is not enough: issue a
    # short-lived challenge and require a TOTP code at /2fa/verify.
    if user_data.get("two_factor_enabled"):
        from app.services.auth_service import create_mfa_challenge
        logger.info(f"2FA challenge issued: {user_data['email']}")
        return {
            "requires_2fa": True,
            "mfa_token": create_mfa_challenge(user_data["id"]),
            "email": user_data["email"],
        }

    # Create tokens
    tokens = await AuthService.create_tokens(user_data, login_data.remember_me)

    # Also set httpOnly cookies (browser path) alongside the JSON body.
    set_auth_cookies(response, tokens)

    logger.info(f"User logged in: {user_data['email']} (role: {user_data['role']})")

    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    response: Response,
    refresh_data: Optional[RefreshRequest] = None,
):
    """
    Refresh access token. The refresh token may come from the JSON body
    (API clients) or the httpOnly `refresh_token` cookie (browser).
    """
    token = (refresh_data.refresh_token if refresh_data else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    tokens = await AuthService.refresh_access_token(token)

    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Rotate the cookies too.
    set_auth_cookies(response, tokens)

    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user
    )


@router.post("/signup", response_model=LoginResponse, status_code=201)
async def signup(request: Request, response: Response, body: SignupRequest):
    """Self-serve signup (go-to-market onboarding): create an isolated tenant
    workspace + its owner account, optionally pre-loaded with sample data so the
    dashboard shows value immediately, and return tokens (auto-login). No billing
    — new tenants start on a free trial."""
    from app.services.tenant_provisioning import create_tenant_with_owner

    user_id, error = await create_tenant_with_owner(
        company=body.company_name, email=body.email, password=body.password,
        first_name=body.first_name, last_name=body.last_name,
        seed_demo=body.seed_sample_data,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)

    user_data = await AuthService.get_user_by_id(user_id)
    tokens = await AuthService.create_tokens(user_data)
    set_auth_cookies(response, tokens)
    logger.info(f"New tenant signup: {body.email} (tenant {user_data.get('tenant_id')})")
    from app.services.security_events import record_event
    await record_event("signup", request=request, tenant_id=user_data.get('tenant_id'),
                       actor_user_id=user_id, actor_email=body.email,
                       detail=f"New tenant workspace created for {body.email}")
    await send_verification_email(user_id, body.email)
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user,
    )


@router.post("/invite", status_code=201)
async def invite(body: InviteRequest, current_user: dict = Depends(get_current_user)):
    """Invite a teammate into the caller's tenant (admin only). Returns a
    one-time temporary password the invitee must change on first login."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required to invite users")
    from app.services.tenant_provisioning import invite_user

    result, error = await invite_user(
        tenant_id=current_user.get("tenant_id") or 1,
        email=body.email, first_name=body.first_name,
        last_name=body.last_name, role=body.role,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return result


@router.get("/onboarding")
async def onboarding_status(current_user: dict = Depends(get_current_user)):
    """Onboarding checklist for the caller's tenant — drives a 'getting started'
    UI so a new customer knows the next step to value."""
    from sqlalchemy import text
    from app.services.database import async_session

    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        stores = (await session.execute(
            text("SELECT COUNT(*) FROM stores WHERE tenant_id = :t"), {"t": tenant_id})).scalar() or 0
        users = (await session.execute(
            text("SELECT COUNT(*) FROM users WHERE tenant_id = :t"), {"t": tenant_id})).scalar() or 0
        sales = (await session.execute(
            text("SELECT COUNT(*) FROM sales_fact_view WHERE tenant_id = :t"), {"t": tenant_id})).scalar() or 0

    has_data = sales > 0
    has_team = users > 1
    steps = [
        {"key": "create_account", "label": "Create your workspace", "done": True},
        {"key": "load_data", "label": "Load sales data", "done": has_data},
        {"key": "invite_team", "label": "Invite a teammate", "done": has_team},
    ]
    done = sum(1 for s in steps if s["done"])
    return {
        "tenant_id": tenant_id,
        "stores": stores, "users": users, "sales_records": sales,
        "steps": steps,
        "progress_pct": round(done / len(steps) * 100),
        "complete": done == len(steps),
    }


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response, user: dict = Depends(get_current_user)):
    """
    Logout current user and invalidate token
    """
    ip_address = request.client.host if request.client else None

    # Extract token from Authorization header or cookie to blacklist it
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token:
        token = request.cookies.get(ACCESS_COOKIE)

    await AuthService.logout(user['id'], ip_address, token=token)

    # Clear the httpOnly cookies as well.
    clear_auth_cookies(response)

    logger.info(f"User logged out: {user['email']}")

    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=dict)
async def get_current_user_info(user: dict = Depends(get_current_user)):
    """
    Get current user information and permissions
    """
    return {
        "id": user['id'],
        "email": user['email'],
        "first_name": user['first_name'],
        "last_name": user['last_name'],
        "full_name": f"{user['first_name']} {user['last_name']}",
        "role": user['role'],
        "role_display": user['role'].replace('_', ' ').title(),
        "status": user['status'],
        "email_verified": bool(user.get('email_verified', True)),
        "job_title": user.get('job_title'),
        "department": user.get('department'),
        "last_login_at": user.get('last_login_at'),
        "permissions": user.get('permissions', {}),
        "accessible_stores": user.get('permissions', {}).get('accessible_stores', []),
        "accessible_regions": user.get('permissions', {}).get('accessible_regions', [])
    }


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    password_data: PasswordChange,
    user: dict = Depends(get_current_user)
):
    """
    Change current user's password
    """
    success, message = await AuthService.change_password(
        user['id'],
        password_data.current_password,
        password_data.new_password
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    logger.info(f"Password changed for user: {user['email']}")
    
    return MessageResponse(message=message)


# =============================================================================
# PASSWORD RESET (email token)
# =============================================================================

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Email a single-use reset link. Always returns the same message — never
    reveals whether an account exists (prevents user enumeration)."""
    from app.services.auth_service import create_password_reset_token
    user_id = await AuthService.get_user_id_by_email(body.email)
    if user_id:
        token = create_password_reset_token(user_id)
        frontend = (get_settings().cors_origins.split(",")[0] or "http://localhost:3000").strip()
        link = f"{frontend}/reset-password?token={token}"
        from app.services.security_notify import send_email
        await send_email(
            body.email, f"Reset your {get_settings().product_name} password",
            f"We received a request to reset your password.\n\n"
            f"Reset link (valid 30 minutes): {link}\n\n"
            f"If you didn't request this, you can ignore this email — your password is unchanged.",
        )
        from app.services.security_events import record_event
        await record_event("password_reset_requested", severity="low", category="audit",
                           request=request, actor_user_id=user_id, actor_email=body.email,
                           detail=f"Password reset requested for {body.email}")
        logger.info(f"Password reset requested: {body.email}")
    return MessageResponse(message="If that account exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest, request: Request):
    """Validate the reset token and set a new password."""
    from app.services.auth_service import decode_password_reset_token
    user_id = decode_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    ok, msg = await AuthService.reset_password(user_id, body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    from app.services.security_events import record_event
    await record_event("password_changed", severity="medium", category="audit", request=request,
                       actor_user_id=user_id, detail="Password changed via reset link")
    return MessageResponse(message=msg)


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================

class VerifyEmailRequest(BaseModel):
    token: str


def _verify_link(user_id: int) -> str:
    from app.services.auth_service import create_email_verify_token
    frontend = (get_settings().cors_origins.split(",")[0] or "http://localhost:3000").strip()
    return f"{frontend}/verify-email?token={create_email_verify_token(user_id)}"


async def send_verification_email(user_id: int, email: str) -> None:
    from app.services.security_notify import send_email
    await send_email(
        email, f"Verify your {get_settings().product_name} email",
        f"Welcome! Confirm your email to finish setting up your account:\n\n{_verify_link(user_id)}\n\n"
        f"This link is valid for 3 days.",
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(body: VerifyEmailRequest):
    from app.services.auth_service import decode_email_verify_token
    user_id = decode_email_verify_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    await AuthService.mark_email_verified(user_id)
    return MessageResponse(message="Email verified")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(user: dict = Depends(get_current_user)):
    if user.get("email_verified"):
        return MessageResponse(message="Your email is already verified")
    await send_verification_email(user["id"], user["email"])
    return MessageResponse(message="Verification email sent")


# =============================================================================
# TWO-FACTOR AUTHENTICATION (TOTP / "2-step verification")
# =============================================================================

@router.post("/2fa/setup")
async def setup_2fa(user: dict = Depends(get_current_user)):
    """Begin 2FA enrollment: returns a secret + otpauth URI to add to an
    authenticator app. 2FA is not active until confirmed at /2fa/enable."""
    data = await AuthService.start_2fa_setup(user['id'])
    if not data:
        raise HTTPException(status_code=400, detail="Could not start 2FA setup")
    return data


@router.post("/2fa/enable")
async def enable_2fa(body: TwoFactorCodeRequest, request: Request,
                     user: dict = Depends(get_current_user)):
    """Confirm enrollment by verifying the first code, then turn 2FA on. Returns
    one-time backup codes (shown ONCE — the user must save them)."""
    ok, msg, backup_codes = await AuthService.confirm_2fa(user['id'], body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    from app.services.security_events import record_event
    await record_event("2fa_enabled", severity="low", category="audit", request=request,
                       tenant_id=user.get('tenant_id'), actor_user_id=user['id'],
                       actor_email=user.get('email'),
                       detail=f"2-step verification enabled for {user.get('email')}")
    return {"success": True, "message": msg, "backup_codes": backup_codes}


@router.post("/2fa/disable", response_model=MessageResponse)
async def disable_2fa(body: TwoFactorCodeRequest, request: Request,
                      user: dict = Depends(get_current_user)):
    """Disable 2FA (requires a current code so a hijacked session can't turn it off)."""
    ok, msg = await AuthService.disable_2fa(user['id'], body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    from app.services.security_events import record_event
    await record_event("2fa_disabled", severity="medium", category="audit", request=request,
                       tenant_id=user.get('tenant_id'), actor_user_id=user['id'],
                       actor_email=user.get('email'),
                       detail=f"2-step verification DISABLED for {user.get('email')}")
    return MessageResponse(message=msg)


@router.post("/2fa/verify")
async def verify_2fa(body: TwoFactorVerifyRequest, request: Request, response: Response):
    """Exchange a login 2FA challenge + TOTP code for real access/refresh tokens."""
    from app.services.auth_service import decode_mfa_challenge
    user_id = decode_mfa_challenge(body.mfa_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA challenge")

    if not await AuthService.verify_2fa(user_id, body.code):
        from app.services.security_events import record_event
        await record_event("2fa_failed", request=request, actor_user_id=user_id,
                           detail="Incorrect 2FA code at login")
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    user_data = await AuthService.get_user_by_id(user_id)
    if not user_data or user_data.get('status') != 'active':
        raise HTTPException(status_code=401, detail="Account is not active")
    tokens = await AuthService.create_tokens(user_data)
    set_auth_cookies(response, tokens)
    logger.info(f"2FA login completed: {user_data['email']}")
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user,
    )


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_role('super_admin')),
):
    """
    List users in the caller's tenant (Super Admin only), paginated.
    Returns {users, total, page, limit, pages}.
    """
    return await AuthService.get_all_users(
        page=page, limit=limit, tenant_id=user.get('tenant_id')
    )


@router.get("/validate")
async def validate_token(user: dict = Depends(get_current_user)):
    """
    Validate current token and return basic user info
    Used by frontend to check if user is still authenticated
    """
    return {
        "valid": True,
        "user_id": user['id'],
        "email": user['email'],
        "role": user['role']
    }


# =============================================================================
# STORE ACCESS HELPERS
# =============================================================================

@router.get("/accessible-stores")
async def get_accessible_stores(user: dict = Depends(get_current_user)):
    """
    Get list of stores the current user can access
    """
    return {
        "stores": user.get('permissions', {}).get('accessible_stores', []),
        "regions": user.get('permissions', {}).get('accessible_regions', []),
        "role": user['role']
    }


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
# SSE STREAM TICKET (short-lived token for EventSource connections)
# =============================================================================

@router.post("/stream-ticket")
async def issue_stream_ticket(user: dict = Depends(get_current_user)):
    """
    Issue a short-lived ticket for SSE stream authentication.
    
    EventSource API cannot send custom headers, so the frontend first
    obtains a stream ticket via this authenticated endpoint, then connects
    to /stream/sales?ticket=<token>.
    
    The ticket expires in 60 seconds and is single-use.
    """
    from app.services.auth_service import create_access_token
    from datetime import timedelta
    
    ticket = create_access_token(
        data={
            "user_id": user['id'],
            "email": user['email'],
            "role": user['role'],
            "ticket": True,  # marks this as a stream ticket
        },
        expires_delta=timedelta(seconds=60)
    )
    return {"ticket": ticket, "expires_in": 60}


async def get_current_user_from_ticket(
    ticket: Optional[str] = Query(None, description="Short-lived SSE stream ticket")
) -> dict:
    """Dependency to validate the short-lived ticket for SSE streams"""
    if not ticket:
        raise HTTPException(status_code=401, detail="Missing stream ticket")
    
    # Verify that it's a valid ticket token
    from jose import jwt, JWTError
    from app.services.auth_service import SECRET_KEY, ALGORITHM
    
    try:
        payload = jwt.decode(ticket, SECRET_KEY, algorithms=[ALGORITHM])
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


