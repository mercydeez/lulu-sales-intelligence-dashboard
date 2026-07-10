"""
Authentication Service - JWT & Session Management
Handles user authentication, authorization, and session management
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import async_session
from app.config import get_settings, logger

settings = get_settings()

# =============================================================================
# CONFIGURATION
# =============================================================================

SECRET_KEY = settings.jwt_secret_key
# ALGORITHM is the *active* signing algorithm (HS256 by default, RS256 when
# JWT_ALGORITHM=RS256). Kept as a module constant for backward compatibility with
# callers/tests that import it; all real signing/verification goes through the key
# provider (services/jwt_keys.py), which also accepts legacy HS256 tokens during a
# rotation window. See E5-6 / docs/runbooks/JWT_KEY_ROTATION.md.
ALGORITHM = (getattr(settings, "jwt_algorithm", "HS256") or "HS256").upper()
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS = 30
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TokenData(BaseModel):
    user_id: int
    email: str
    role: str
    tenant_id: Optional[int] = None
    permissions: Dict[str, Any] = {}
    exp: datetime
    iat: Optional[datetime] = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]


class UserLogin(BaseModel):
    model_config = ConfigDict(strict=True)
    email: EmailStr
    password: str
    remember_me: bool = False


class UserCreate(BaseModel):
    model_config = ConfigDict(strict=True)
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    role: str = "analyst"
    job_title: Optional[str] = None
    department: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    status: str
    job_title: Optional[str]
    department: Optional[str]
    last_login_at: Optional[datetime]
    permissions: Dict[str, Any]
    accessible_stores: List[int]
    accessible_regions: List[str]


class PasswordChange(BaseModel):
    model_config = ConfigDict(strict=True)
    current_password: str
    new_password: str


# =============================================================================
# PASSWORD UTILITIES
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets complexity requirements:
    - Minimum 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters"
    if len(password) > 128:
        return False, "Password must be at most 128 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?~`" for c in password):
        return False, "Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?~`)"
    # Check for common weak patterns
    common_patterns = ['password', '12345678', 'qwerty', 'letmein', 'admin']
    lower_pwd = password.lower()
    for pattern in common_patterns:
        if pattern in lower_pwd:
            return False, f"Password must not contain common pattern: '{pattern}'"
    return True, "Password is valid"


# =============================================================================
# JWT TOKEN UTILITIES
# =============================================================================

def _sign(claims: dict) -> str:
    """Sign claims with the active key (RS256 with a `kid` header, or legacy
    HS256). Single choke point so every token issued shares one policy."""
    from app.services.jwt_keys import get_key_provider
    return get_key_provider().sign(claims)


def _verify(token: str) -> dict:
    """Verify a token against the current keyset (RS256 by `kid`, or legacy
    HS256 while the fallback is enabled). Raises JWTError on any failure."""
    from app.services.jwt_keys import get_key_provider
    return get_key_provider().verify(token)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token. Carries `iat` so a password reset can revoke all
    access tokens issued before the reset (see revoke_user_sessions)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now, "type": "access", "jti": secrets.token_hex(8)})
    return _sign(to_encode)


def create_refresh_token(data: dict, remember_me: bool = False) -> str:
    """Create JWT refresh token. remember_me extends lifetime from 7 to 30 days."""
    to_encode = data.copy()
    days = REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS if remember_me else REFRESH_TOKEN_EXPIRE_DAYS
    expire = datetime.now(timezone.utc) + timedelta(days=days)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_hex(8),
        "remember_me": remember_me,
    })
    return _sign(to_encode)


def decode_token(token: str, expected_type: Optional[str] = "access") -> Optional[TokenData]:
    """Decode and validate a JWT.

    `expected_type` pins the token's `type` claim (default "access") so a
    long-lived refresh token can't be replayed as a Bearer access token (token
    type confusion). Pass `expected_type="refresh"` on the refresh path, or
    `None` to skip the check.
    """
    try:
        payload = _verify(token)
        if expected_type is not None and payload.get("type") != expected_type:
            logger.warning(
                f"Rejected token: expected type '{expected_type}', got '{payload.get('type')}'"
            )
            return None
        return TokenData(
            user_id=payload.get("user_id"),
            email=payload.get("email"),
            role=payload.get("role"),
            tenant_id=payload.get("tenant_id"),
            permissions=payload.get("permissions", {}),
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
            iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc) if payload.get("iat") else None,
        )
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        return None


# =============================================================================
# 2FA LOGIN CHALLENGE — a short-lived token issued after a correct password when
# the account has 2FA on. It is NOT an access token (distinct `type`), so it can't
# be used to call the API; /2fa/verify exchanges it + a TOTP code for real tokens.
# =============================================================================

def create_mfa_challenge(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return _sign({"user_id": user_id, "type": "mfa_challenge", "exp": expire})


def decode_mfa_challenge(token: str) -> Optional[int]:
    try:
        payload = _verify(token)
        if payload.get("type") != "mfa_challenge":
            return None
        return payload.get("user_id")
    except JWTError:
        return None


def create_password_reset_token(user_id: int) -> str:
    """Short-lived (30 min) single-purpose reset token. Distinct `type` so it can't
    be used as an access token; bound to the user."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    return _sign(
        {"user_id": user_id, "type": "pwd_reset", "exp": expire, "jti": secrets.token_hex(8)}
    )


def decode_password_reset_token(token: str) -> Optional[int]:
    try:
        payload = _verify(token)
        if payload.get("type") != "pwd_reset":
            return None
        return payload.get("user_id")
    except JWTError:
        return None


def create_email_verify_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=3)
    return _sign({"user_id": user_id, "type": "email_verify", "exp": expire})


def decode_email_verify_token(token: str) -> Optional[int]:
    try:
        payload = _verify(token)
        if payload.get("type") != "email_verify":
            return None
        return payload.get("user_id")
    except JWTError:
        return None


# =============================================================================
# TOKEN BLACKLIST (Redis-backed; fails open when Redis is down,
# consistent with SessionInvalidationMiddleware)
# =============================================================================

def _token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


async def blacklist_token(token: str, ttl_seconds: int) -> None:
    """Mark a token as unusable for ttl_seconds (idempotent, best-effort)."""
    try:
        from app.services.redis_client import redis_client
        if redis_client:
            await redis_client.set(
                f"blacklisted_token:{_token_hash(token)}", "1", ex=max(ttl_seconds, 1)
            )
    except Exception as e:
        logger.warning(f"Failed to blacklist token in Redis: {e}")


async def is_token_blacklisted(token: str) -> bool:
    """Check the Redis JWT blacklist.

    Fails CLOSED by default (returns True => treat as revoked) when Redis is
    unreachable, so a logged-out / rotated token can't be honored during an
    outage. Operators can opt into fail-open via AUTH_FAIL_OPEN_ON_REDIS_DOWN.
    """
    try:
        from app.services.redis_client import redis_client
        if redis_client:
            return bool(await redis_client.get(f"blacklisted_token:{_token_hash(token)}"))
        # Redis not initialized — can't verify revocation.
        raise RuntimeError("redis_client unavailable")
    except Exception as e:
        fail_open = get_settings().auth_fail_open_on_redis_down
        logger.warning(
            f"Token blacklist check failed ({e}); "
            f"{'allowing (fail-open)' if fail_open else 'REJECTING (fail-closed)'}"
        )
        return not fail_open


# =============================================================================
# PER-USER SESSION REVOCATION EPOCH (Redis-backed)
# -----------------------------------------------------------------------------
# We don't persist sessions (auth is stateless JWT + per-token blacklist), so to
# revoke ALL of a user's outstanding access tokens at once (e.g. after a password
# reset) we record a cutoff timestamp. Any access token whose `iat` predates the
# cutoff is rejected by get_current_user.
# =============================================================================

def _revoke_key(user_id: int) -> str:
    return f"auth:revoke_before:{user_id}"


async def revoke_user_sessions(user_id: int) -> None:
    """Invalidate every access token issued for this user up to now."""
    try:
        from app.services.redis_client import redis_client
        if redis_client:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            # TTL slightly beyond the max access-token lifetime is enough.
            await redis_client.set(_revoke_key(user_id), str(now_ts),
                                   ex=max(ACCESS_TOKEN_EXPIRE_MINUTES * 60 * 2, 3600))
    except Exception as e:
        logger.warning(f"Failed to set session revocation epoch for user {user_id}: {e}")


async def tokens_revoked_before(user_id: int) -> Optional[datetime]:
    """Return the revocation cutoff for a user, or None if none is set."""
    try:
        from app.services.redis_client import redis_client
        if redis_client:
            raw = await redis_client.get(_revoke_key(user_id))
            if raw:
                return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except Exception as e:
        logger.warning(f"Failed to read session revocation epoch for user {user_id}: {e}")
    return None


# =============================================================================
# AUTHENTICATION SERVICE CLASS
# =============================================================================

class AuthService:
    """Authentication service handling login, logout, and session management"""
    
    @staticmethod
    async def authenticate_user(email: str, password: str, ip_address: str = None) -> tuple[Optional[Dict], Optional[str]]:
        """
        Authenticate user with email and password
        Returns: (user_dict, error_message)
        """
        async with async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    SELECT u.id, u.email, u.password_hash, u.first_name, u.last_name, u.role,
                           u.status, u.job_title, u.department, u.failed_login_attempts,
                           u.locked_until, u.two_factor_enabled, u.two_factor_secret,
                           u.tenant_id, u.email_verified,
                           -- E10-2: carried out of this query so /login can check the
                           -- tenant's isolation tier without a second round-trip.
                           COALESCE(t.isolation_tier, 'shared') AS isolation_tier
                    FROM users u
                    LEFT JOIN tenants t ON t.id = u.tenant_id
                    WHERE u.email = :email
                """),
                {"email": email.lower()}
            )
            user_row = result.fetchone()
            
            if not user_row:
                logger.warning(f"Login attempt for non-existent user: {email}")
                from app.services.security_events import record_event
                await record_event("login_failed", actor_email=email, ip_address=ip_address,
                                    detail=f"Login attempt for unknown account {email}",
                                    evidence={"reason": "unknown_user"})
                return None, "Invalid email or password"
            
            user = dict(user_row._mapping)
            
            # Check if account is locked
            if user['locked_until'] and user['locked_until'] > datetime.now(timezone.utc):
                remaining = (user['locked_until'] - datetime.now(timezone.utc)).seconds // 60
                logger.warning(f"Login attempt for locked account: {email}")
                return None, f"Account is locked. Try again in {remaining} minutes"
            
            # Check account status
            if user['status'] != 'active':
                logger.warning(f"Login attempt for inactive account: {email} (status: {user['status']})")
                return None, f"Account is {user['status']}. Please contact administrator"
            
            # Verify password
            if not verify_password(password, user['password_hash']):
                # Increment failed attempts
                new_attempts = user['failed_login_attempts'] + 1
                locked_until = None
                
                if new_attempts >= MAX_LOGIN_ATTEMPTS:
                    locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                    logger.warning(f"Account locked due to failed attempts: {email}")
                
                await session.execute(
                    text("""
                        UPDATE users 
                        SET failed_login_attempts = :attempts, locked_until = :locked_until
                        WHERE id = :id
                    """),
                    {"attempts": new_attempts, "locked_until": locked_until, "id": user['id']}
                )
                await session.commit()

                # Log failed attempt
                await AuthService._log_audit(
                    session, user['id'], 'login_failed',
                    f"Failed login attempt ({new_attempts}/{MAX_LOGIN_ATTEMPTS})",
                    ip_address
                )

                from app.services.security_events import record_event
                await record_event(
                    "account_locked" if locked_until else "login_failed",
                    tenant_id=user.get('tenant_id'), actor_user_id=user['id'],
                    actor_email=email, ip_address=ip_address,
                    detail=(f"Account {email} locked after {new_attempts} failed attempts"
                            if locked_until else
                            f"Failed login for {email} ({new_attempts}/{MAX_LOGIN_ATTEMPTS})"),
                    evidence={"attempts": new_attempts, "max": MAX_LOGIN_ATTEMPTS},
                )

                if locked_until:
                    return None, f"Too many failed attempts. Account locked for {LOCKOUT_DURATION_MINUTES} minutes"
                return None, "Invalid email or password"
            
            # Successful login - reset failed attempts and update last login
            await session.execute(
                text("""
                    UPDATE users 
                    SET failed_login_attempts = 0, 
                        locked_until = NULL,
                        last_login_at = :login_time,
                        last_login_ip = :ip,
                        last_activity_at = :login_time
                    WHERE id = :id
                """),
                {"login_time": datetime.now(timezone.utc), "ip": ip_address, "id": user['id']}
            )
            
            # Get user permissions
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'], user.get('tenant_id'))
            
            # Log successful login
            await AuthService._log_audit(
                session, user['id'], 'login', 
                "Successful login",
                ip_address
            )
            
            await session.commit()
            
            # Build user response
            user_data = {
                "id": user['id'],
                "email": user['email'],
                "first_name": user['first_name'],
                "last_name": user['last_name'],
                "role": user['role'],
                "status": user['status'],
                "job_title": user['job_title'],
                "department": user['department'],
                "tenant_id": user.get('tenant_id'),
                "two_factor_enabled": bool(user.get('two_factor_enabled')),
                "email_verified": bool(user.get('email_verified')),
                # E10-2: /login refuses a tenant whose isolation tier this
                # deployment cannot deliver. Omitting it here makes that check read
                # None -> 'shared' and silently pass, which is the exact failure the
                # tier exists to prevent.
                "isolation_tier": user.get('isolation_tier') or 'shared',
                "permissions": permissions
            }

            return user_data, None
    
    @staticmethod
    async def _get_user_permissions(session: AsyncSession, user_id: int, role: str,
                                    tenant_id: Optional[int] = None) -> Dict:
        """Get user permissions including accessible stores and regions.

        A super_admin sees everything WITHIN THEIR TENANT — when tenant_id is
        provided, the accessible-stores list is scoped to that tenant so one
        tenant's owner never sees another tenant's store IDs (B2)."""
        from sqlalchemy import text

        # Super admin has access to everything (within their tenant when known)
        if role == 'super_admin':
            if tenant_id is not None:
                stores_result = await session.execute(
                    text("SELECT id FROM stores WHERE tenant_id = :tid"), {"tid": tenant_id})
            else:
                stores_result = await session.execute(text("SELECT id FROM stores"))
            regions_result = await session.execute(text("SELECT code FROM regions"))
            return {
                "accessible_stores": [r[0] for r in stores_result.fetchall()],
                "accessible_regions": [r[0] for r in regions_result.fetchall()],
                "can_view": True,
                "can_edit": True,
                "can_delete": True,
                "can_export": True,
                "can_manage_users": True,
                "can_manage_inventory": True,
                "can_manage_promotions": True,
                "can_view_financials": True,
                "can_approve_transfers": True
            }
        
        # Get permissions from user_permissions table
        result = await session.execute(
            text("""
                SELECT up.*, r.code as region_code, s.id as store_id
                FROM user_permissions up
                LEFT JOIN regions r ON up.region_id = r.id
                LEFT JOIN stores s ON up.store_id = s.id OR s.region_id = up.region_id
                WHERE up.user_id = :user_id
                AND (up.valid_until IS NULL OR up.valid_until >= CURRENT_DATE)
            """),
            {"user_id": user_id}
        )
        
        permissions_rows = result.fetchall()
        
        accessible_stores = set()
        accessible_regions = set()
        aggregated_permissions = {
            "can_view": False,
            "can_edit": False,
            "can_delete": False,
            "can_export": False,
            "can_manage_users": False,
            "can_manage_inventory": False,
            "can_manage_promotions": False,
            "can_view_financials": False,
            "can_approve_transfers": False
        }
        
        for row in permissions_rows:
            row_dict = dict(row._mapping)
            
            if row_dict.get('store_id'):
                accessible_stores.add(row_dict['store_id'])
            if row_dict.get('region_code'):
                accessible_regions.add(row_dict['region_code'])
            
            # Aggregate boolean permissions (OR logic)
            for key in aggregated_permissions:
                if row_dict.get(key):
                    aggregated_permissions[key] = True
        
        # If regional permission, get all stores in that region
        if accessible_regions:
            stores_result = await session.execute(
                text("""
                    SELECT s.id FROM stores s
                    JOIN regions r ON s.region_id = r.id
                    WHERE r.code = ANY(:regions)
                """),
                {"regions": list(accessible_regions)}
            )
            for row in stores_result.fetchall():
                accessible_stores.add(row[0])
        
        return {
            "accessible_stores": list(accessible_stores),
            "accessible_regions": list(accessible_regions),
            **aggregated_permissions
        }
    
    @staticmethod
    async def _log_audit(session: AsyncSession, user_id: int, action: str, description: str, ip_address: str = None):
        """Log audit event"""
        from sqlalchemy import text
        await session.execute(
            text("""
                INSERT INTO audit_log (user_id, action, description, ip_address, created_at)
                VALUES (:user_id, :action, :description, :ip, :created_at)
            """),
            {
                "user_id": user_id,
                "action": action,
                "description": description,
                "ip": ip_address,
                "created_at": datetime.now(timezone.utc)
            }
        )
    
    @staticmethod
    async def create_tokens(user_data: Dict, remember_me: bool = False) -> Token:
        """Create access and refresh tokens for user"""
        # Keep JWT payload minimal — permissions are looked up from DB on each request.
        # tenant_id IS embedded so the request path can bind the RLS tenant GUC
        # before the DB session opens (services/database.resolve_request_tenant),
        # independent of dependency-resolution order.
        token_data = {
            "user_id": user_data["id"],
            "email": user_data["email"],
            "role": user_data["role"],
            "tenant_id": user_data.get("tenant_id"),
        }
        
        # Access token is always short-lived. remember_me only extends the refresh token.
        access_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(token_data, access_delta)
        refresh_token = create_refresh_token(token_data, remember_me=remember_me)
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(access_delta.total_seconds()),
            user=user_data
        )
    
    @staticmethod
    async def refresh_access_token(refresh_token: str) -> Optional[Token]:
        """Refresh access token using refresh token.

        Refresh tokens are single-use: the presented token is blacklisted for
        its remaining lifetime and a new pair is issued (rotation). A replayed
        refresh token is rejected.
        """
        token_data = decode_token(refresh_token, expected_type="refresh")
        if not token_data:
            return None

        # Already validated as a refresh token above; decode again only to read
        # the remember_me claim used to preserve the rotated token's lifetime.
        payload = _verify(refresh_token)

        # Reject already-used (rotated) or logged-out refresh tokens
        if await is_token_blacklisted(refresh_token):
            logger.warning(f"Replay of rotated refresh token for user_id={token_data.user_id}")
            return None

        # Get fresh user data
        async with async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    SELECT id, email, first_name, last_name, role, status, job_title, department
                    FROM users WHERE id = :id AND status = 'active'
                """),
                {"id": token_data.user_id}
            )
            user_row = result.fetchone()

            if not user_row:
                return None

            user = dict(user_row._mapping)
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'], user.get('tenant_id'))

            user_data = {**user, "permissions": permissions}

        # Rotate: retire the used refresh token for its remaining lifetime,
        # then issue a new pair preserving the original remember_me duration.
        remaining = int((token_data.exp - datetime.now(timezone.utc)).total_seconds())
        await blacklist_token(refresh_token, remaining)

        return await AuthService.create_tokens(
            user_data, remember_me=bool(payload.get("remember_me"))
        )
    
    @staticmethod
    async def logout(user_id: int, ip_address: str = None, token: str = None):
        """Log user logout and blacklist the token in Redis."""
        # Blacklist the token so SessionInvalidationMiddleware rejects it,
        # covering the max token lifetime (30-day remember_me refresh tokens)
        if token:
            await blacklist_token(
                token, REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            )

        async with async_session() as session:
            await AuthService._log_audit(session, user_id, 'logout', "User logged out", ip_address)
            await session.commit()
    
    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[Dict]:
        """Get user by ID with permissions"""
        async with async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    SELECT id, email, first_name, last_name, role, status,
                           job_title, department, last_login_at, created_at,
                           tenant_id, email_verified
                    FROM users WHERE id = :id
                """),
                {"id": user_id}
            )
            user_row = result.fetchone()
            
            if not user_row:
                return None
            
            user = dict(user_row._mapping)
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'], user.get('tenant_id'))
            
            return {**user, "permissions": permissions}
    
    @staticmethod
    async def change_password(user_id: int, current_password: str, new_password: str) -> tuple[bool, str]:
        """Change user password"""
        # Validate new password strength
        is_valid, message = validate_password_strength(new_password)
        if not is_valid:
            return False, message
        
        async with async_session() as session:
            from sqlalchemy import text
            
            # Get current password hash
            result = await session.execute(
                text("SELECT password_hash FROM users WHERE id = :id"),
                {"id": user_id}
            )
            user_row = result.fetchone()
            
            if not user_row:
                return False, "User not found"
            
            # Verify current password
            if not verify_password(current_password, user_row[0]):
                return False, "Current password is incorrect"
            
            # Update password
            new_hash = get_password_hash(new_password)
            await session.execute(
                text("""
                    UPDATE users 
                    SET password_hash = :hash, 
                        password_changed_at = :now,
                        must_change_password = FALSE
                    WHERE id = :id
                """),
                {"hash": new_hash, "now": datetime.now(timezone.utc), "id": user_id}
            )
            
            await AuthService._log_audit(session, user_id, 'change_password', "Password changed")
            await session.commit()

            from app.services.security_events import record_event
            await record_event("password_changed", actor_user_id=user_id,
                               detail="Account password was changed")

            return True, "Password changed successfully"
    
    @staticmethod
    async def mark_email_verified(user_id: int) -> bool:
        async with async_session() as session:
            from sqlalchemy import text
            res = await session.execute(
                text("UPDATE users SET email_verified = TRUE WHERE id = :id"), {"id": user_id})
            await session.commit()
            return (res.rowcount or 0) > 0

    @staticmethod
    async def get_user_id_by_email(email: str) -> Optional[int]:
        async with async_session() as session:
            from sqlalchemy import text
            row = (await session.execute(
                text("SELECT id FROM users WHERE email = :e AND status = 'active'"),
                {"e": email.lower()})).fetchone()
            return row.id if row else None

    @staticmethod
    async def reset_password(user_id: int, new_password: str) -> tuple[bool, str]:
        """Set a new password WITHOUT the current one (post reset-token validation)."""
        is_valid, message = validate_password_strength(new_password)
        if not is_valid:
            return False, message
        async with async_session() as session:
            from sqlalchemy import text
            res = await session.execute(text("""
                UPDATE users SET password_hash = :h, password_changed_at = :now,
                    must_change_password = FALSE, failed_login_attempts = 0, locked_until = NULL
                WHERE id = :id
            """), {"h": get_password_hash(new_password), "now": datetime.now(timezone.utc), "id": user_id})
            if (res.rowcount or 0) == 0:
                return False, "User not found"
            await AuthService._log_audit(session, user_id, 'password_reset', "Password reset via email token")
            await session.commit()
            return True, "Password has been reset"

    # =========================================================================
    # TWO-FACTOR AUTHENTICATION (TOTP)
    # =========================================================================

    @staticmethod
    async def start_2fa_setup(user_id: int) -> Dict:
        """Generate (or replace) a pending TOTP secret and return enrollment data.
        The secret is stored but two_factor_enabled stays FALSE until confirmed."""
        from app.services import totp
        from app.config import get_settings
        async with async_session() as session:
            from sqlalchemy import text
            row = (await session.execute(
                text("SELECT email FROM users WHERE id = :id"), {"id": user_id})).fetchone()
            if not row:
                return {}
            secret = totp.generate_secret()
            await session.execute(text("""
                UPDATE users SET two_factor_secret = :s, two_factor_enabled = FALSE
                WHERE id = :id
            """), {"s": secret, "id": user_id})
            await session.commit()
            issuer = get_settings().product_name
            return {
                "secret": secret,
                "otpauth_uri": totp.provisioning_uri(secret, row.email, issuer),
                "issuer": issuer,
                "account": row.email,
            }

    @staticmethod
    async def _get_2fa_secret(session, user_id: int):
        from sqlalchemy import text
        row = (await session.execute(text(
            "SELECT two_factor_secret, two_factor_enabled FROM users WHERE id = :id"),
            {"id": user_id})).fetchone()
        return row

    @staticmethod
    async def confirm_2fa(user_id: int, code: str) -> tuple[bool, str, list]:
        """Verify the first code against the pending secret, enable 2FA, and mint
        one-time backup/recovery codes (returned ONCE for the user to save)."""
        import json as _json
        from app.services import totp
        async with async_session() as session:
            from sqlalchemy import text
            row = await AuthService._get_2fa_secret(session, user_id)
            if not row or not row.two_factor_secret:
                return False, "Start 2FA setup first", []
            if not totp.verify(row.two_factor_secret, code):
                return False, "Invalid code — check your authenticator app", []
            codes = totp.generate_backup_codes()
            hashes = [totp.hash_backup_code(c) for c in codes]
            await session.execute(text(
                "UPDATE users SET two_factor_enabled = TRUE, "
                "two_factor_backup_codes = CAST(:codes AS jsonb) WHERE id = :id"),
                {"codes": _json.dumps(hashes), "id": user_id})
            await session.commit()
            return True, "Two-factor authentication enabled", codes

    @staticmethod
    async def disable_2fa(user_id: int, code: str) -> tuple[bool, str]:
        """Disable 2FA after verifying a current code (so a hijacked session can't)."""
        from app.services import totp
        async with async_session() as session:
            from sqlalchemy import text
            row = await AuthService._get_2fa_secret(session, user_id)
            if not row or not row.two_factor_enabled:
                return False, "2FA is not enabled"
            if not totp.verify(row.two_factor_secret or "", code):
                return False, "Invalid code"
            await session.execute(text(
                "UPDATE users SET two_factor_enabled = FALSE, two_factor_secret = NULL, "
                "two_factor_backup_codes = '[]'::jsonb WHERE id = :id"),
                {"id": user_id})
            await session.commit()
            return True, "Two-factor authentication disabled"

    @staticmethod
    async def verify_2fa(user_id: int, code: str) -> bool:
        """Verify a login-time code: TOTP first, then a one-time backup code
        (consumed on use)."""
        import json as _json
        from sqlalchemy import text
        from app.services import totp
        async with async_session() as session:
            row = (await session.execute(text(
                "SELECT two_factor_secret, two_factor_enabled, two_factor_backup_codes "
                "FROM users WHERE id = :id"), {"id": user_id})).fetchone()
            if not row or not row.two_factor_enabled or not row.two_factor_secret:
                return False
            if totp.verify(row.two_factor_secret, code):
                return True
            # One-time backup code: consume it on a match.
            stored = row.two_factor_backup_codes or []
            if isinstance(stored, str):
                stored = _json.loads(stored)
            h = totp.hash_backup_code(code)
            if h in stored:
                remaining = [c for c in stored if c != h]
                await session.execute(text(
                    "UPDATE users SET two_factor_backup_codes = CAST(:c AS jsonb) WHERE id = :id"),
                    {"c": _json.dumps(remaining), "id": user_id})
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_all_users(page: int = 1, limit: int = 50, tenant_id: Optional[int] = None) -> Dict:
        """List users for ONE tenant (admin only), paginated to bound the result set.

        Scoped to `tenant_id` so a per-tenant super_admin (every self-signup owner
        is one) can never enumerate another tenant's users. A platform-wide
        operator view must use a separate privileged role — not this endpoint.
        Callers must pass tenant_id; `None` would list across tenants and is only
        for trusted internal/platform use.
        """
        page = max(1, page)
        limit = max(1, min(limit, 200))
        offset = (page - 1) * limit
        where = "" if tenant_id is None else "WHERE tenant_id = :tenant_id"
        async with async_session() as session:
            from sqlalchemy import text
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if tenant_id is not None:
                params["tenant_id"] = tenant_id
            result = await session.execute(
                text(f"""
                    SELECT id, email, first_name, last_name, role, status,
                           job_title, department, last_login_at, created_at
                    FROM users
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            users = [dict(row._mapping) for row in result.fetchall()]
            total = (await session.execute(
                text(f"SELECT COUNT(*) FROM users {where}"),
                {"tenant_id": tenant_id} if tenant_id is not None else {},
            )).scalar() or 0
            return {
                "users": users,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": max(1, (total + limit - 1) // limit),
            }
