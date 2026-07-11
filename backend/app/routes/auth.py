"""
Authentication Routes - Login, Logout, Token Management

The reusable dependency layer (get_current_user, require_role/permission, the
store-scope helpers, cookie transport, and the SSE ticket dependency) lives in
`app.auth_deps` — this module keeps only the HTTP endpoints and re-exports
every moved name so the pre-split import path (`app.routes.auth`) stays valid.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional

from app.services.auth_service import AuthService, PasswordChange
from app.config import logger, get_settings
from app.auth_deps import (  # noqa: F401 — re-exported for backwards compatibility
    ACCESS_COOKIE, REFRESH_COOKIE, _REFRESH_MAX_AGE, _cookie_kwargs,
    security, CurrentUser, LoginResponse,
    set_auth_cookies, clear_auth_cookies,
    get_current_user, get_current_user_optional,
    require_role, require_permission,
    filter_by_user_stores, can_access_store, get_accessible_store_ids,
    get_current_user_from_ticket,
)

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# (LoginResponse — shared with the SSO callback — lives in app.auth_deps.)
# =============================================================================

class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    email: EmailStr
    password: str
    remember_me: bool = False


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

    # E10-2: refuse to open a session for a tenant whose isolation tier is not
    # actually provisioned/active. Checked once, here — no session means no access.
    # `shared` needs no provisioning (fast path, no query); a dedicated tenant is
    # served only when the provisioning control plane records it active.
    _iso_tier = user_data.get("isolation_tier") or "shared"
    if _iso_tier != "shared":
        from app.services import isolation
        from app.services.database import async_session
        async with async_session() as _iso_db:
            await isolation.enforce_tenant_isolation(_iso_db, user_data.get("tenant_id") or 1)

    # Enforce 2FA for privileged roles when REQUIRE_MFA_FOR_ADMINS is on. Enable
    # this only after admins have enrolled (see docs/product/ACCOUNT_LIFECYCLE.md);
    # toggling it off is the break-glass for initial enrollment.
    _ADMIN_ROLES = {"super_admin", "admin", "owner"}
    if get_settings().require_mfa_for_admins and not user_data.get("two_factor_enabled") \
            and (user_data.get("role") or "").lower() in _ADMIN_ROLES:
        from app.services.security_events import record_event
        await record_event("mfa_required_admin", severity="medium", category="auth",
                           request=request, actor_user_id=user_data["id"],
                           actor_email=user_data["email"],
                           detail=f"Admin {user_data['email']} blocked at login — 2FA required but not enabled")
        raise HTTPException(
            status_code=403,
            detail="Two-factor authentication is required for administrator accounts. "
                   "Contact an administrator to enroll 2FA before signing in.",
        )

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
async def invite(body: InviteRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """Invite a teammate into the caller's tenant (admin only). Creates the user
    and returns a single-use, expiring invite link (7 days) so the invitee sets
    their own password. The temporary password is also returned for back-compat."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required to invite users")
    from app.services.tenant_provisioning import invite_user

    tenant_id = current_user.get("tenant_id") or 1
    result, error = await invite_user(
        tenant_id=tenant_id,
        email=body.email, first_name=body.first_name,
        last_name=body.last_name, role=body.role,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Issue a single-use invite token bound to the new user + tenant + role.
    import secrets as _secrets
    from app.services.token_store import issue_token
    invite_tok = _secrets.token_urlsafe(32)
    await issue_token("invite", invite_tok, ttl_minutes=7 * 24 * 60,
                      user_id=result["user_id"], tenant_id=tenant_id,
                      email=body.email, role=body.role, invited_by=current_user.get("id"))
    frontend = (get_settings().cors_origins.split(",")[0] or "http://localhost:3000").strip()
    result["accept_link"] = f"{frontend}/accept-invite?token={invite_tok}"

    from app.services.security_events import record_event
    await record_event("user_invited", severity="low", category="audit", request=request,
                       tenant_id=tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"Invited {body.email} as {body.role} into tenant {tenant_id}")
    return result


class AcceptInviteRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


@router.post("/accept-invite", response_model=MessageResponse)
async def accept_invite(body: AcceptInviteRequest, request: Request):
    """Consume a single-use invite token and set the invitee's password."""
    from app.services.token_store import consume_token
    from sqlalchemy import text
    from app.services.database import async_session

    claims = await consume_token("invite", body.token)
    if not claims or not claims.get("user_id"):
        raise HTTPException(status_code=400, detail="This invite link is invalid, already used, or has expired")

    ok, msg = await AuthService.reset_password(claims["user_id"], body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    # Activate the account: clear the temp-password flag and mark the email verified
    # (clicking the emailed invite proves control of the inbox).
    async with async_session() as s:
        await s.execute(text(
            "UPDATE users SET must_change_password = FALSE, email_verified = TRUE WHERE id = :id"
        ), {"id": claims["user_id"]})
        await s.commit()

    from app.services.security_events import record_event
    await record_event("invite_accepted", severity="low", category="audit", request=request,
                       tenant_id=claims.get("tenant_id"), actor_user_id=claims["user_id"],
                       actor_email=claims.get("email"),
                       detail=f"Invite accepted by {claims.get('email')}")
    return MessageResponse(message="Invite accepted. You can now sign in.")


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
        # Company profile counts as set once a legal name + emirate exist.
        profile_done = bool((await session.execute(text(
            "SELECT 1 FROM tenant_billing_profile WHERE tenant_id = :t "
            "AND legal_name IS NOT NULL AND emirate IS NOT NULL"), {"t": tenant_id})).fetchone())
        # The value screen has something to show once inventory exists.
        inventory = (await session.execute(text(
            "SELECT COUNT(*) FROM inventory i JOIN items it ON it.id=i.item_id "
            "WHERE it.tenant_id = :t"), {"t": tenant_id})).scalar() or 0

    has_data = sales > 0 or inventory > 0
    has_team = users > 1
    steps = [
        {"key": "create_account", "label": "Create your workspace", "done": True, "href": None},
        {"key": "company_profile", "label": "Set up your UAE company profile",
         "done": profile_done, "href": "/settings/company"},
        {"key": "load_data", "label": "Import your sales & inventory",
         "done": has_data, "href": "/imports"},
        {"key": "review_value", "label": "See your value in AED",
         "done": has_data and inventory > 0, "href": "/value"},
        {"key": "invite_team", "label": "Invite a teammate",
         "done": has_team, "href": "/settings/team"},
    ]
    done = sum(1 for s in steps if s["done"])
    return {
        "tenant_id": tenant_id,
        "stores": stores, "users": users, "sales_records": sales, "inventory_records": inventory,
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
        # Platform-operator boundary (Platform Console). The frontend gates the
        # console page + sidebar nav on this; it must ride the profile or a
        # platform developer sees an empty page even though the API authorizes them.
        "is_platform_developer": bool(user.get('is_platform_developer')),
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
        # Record the token so it can be enforced single-use + expiring at the DB.
        from app.services.token_store import issue_token
        await issue_token("pwd_reset", token, ttl_minutes=30, user_id=user_id)
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
    """Validate the reset token (signature + single-use) and set a new password."""
    from app.services.auth_service import decode_password_reset_token, revoke_user_sessions
    from app.services.token_store import consume_token
    # 1) JWT must be valid (signature/expiry/type).
    user_id = decode_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    # 2) Atomically consume the single-use record — replays/expired match nothing.
    consumed = await consume_token("pwd_reset", body.token)
    if not consumed:
        raise HTTPException(status_code=400, detail="This reset link has already been used or has expired")
    ok, msg = await AuthService.reset_password(user_id, body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    # 3) Revoke all existing sessions so a stolen token can't outlive the reset.
    await revoke_user_sessions(user_id)
    from app.services.security_events import record_event
    await record_event("password_changed", severity="medium", category="audit", request=request,
                       actor_user_id=user_id, detail="Password changed via reset link; sessions revoked")
    return MessageResponse(message=msg)


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================

class VerifyEmailRequest(BaseModel):
    token: str


async def _verify_link(user_id: int) -> str:
    from app.services.auth_service import create_email_verify_token
    from app.services.token_store import issue_token
    token = create_email_verify_token(user_id)
    # Single-use + expiring at the DB (3 days = 4320 minutes). Issuing a new link
    # does not invalidate prior unused ones until they are consumed or expire.
    await issue_token("email_verify", token, ttl_minutes=4320, user_id=user_id)
    frontend = (get_settings().cors_origins.split(",")[0] or "http://localhost:3000").strip()
    return f"{frontend}/verify-email?token={token}"


async def send_verification_email(user_id: int, email: str) -> None:
    from app.services.security_notify import send_email
    link = await _verify_link(user_id)
    await send_email(
        email, f"Verify your {get_settings().product_name} email",
        f"Welcome! Confirm your email to finish setting up your account:\n\n{link}\n\n"
        f"This link is valid for 3 days.",
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(body: VerifyEmailRequest):
    from app.services.auth_service import decode_email_verify_token
    from app.services.token_store import consume_token
    user_id = decode_email_verify_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    # Single-use: a replayed link matches no row.
    if not await consume_token("email_verify", body.token):
        raise HTTPException(status_code=400, detail="This verification link has already been used or has expired")
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
            # Carry tenant_id like every other access token: resolve_request_tenant
            # reads it from a ?ticket= to bind the RLS GUC. Without it the ticket
            # branch there resolves to the default tenant — harmless today (no
            # ticket-authed route opens an RLS DB session) but a defense-in-depth
            # gap the moment one does. Keep the ticket consistent with the contract.
            "tenant_id": user.get('tenant_id'),
            "ticket": True,  # marks this as a stream ticket
        },
        expires_delta=timedelta(seconds=60)
    )
    return {"ticket": ticket, "expires_in": 60}


