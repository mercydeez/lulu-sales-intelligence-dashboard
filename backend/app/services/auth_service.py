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
ALGORITHM = "HS256"
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
    permissions: Dict[str, Any] = {}
    exp: datetime


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

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access", "jti": secrets.token_hex(8)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


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
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenData(
            user_id=payload.get("user_id"),
            email=payload.get("email"),
            role=payload.get("role"),
            permissions=payload.get("permissions", {}),
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
        )
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
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
    """Check the Redis blacklist. Returns False when Redis is unavailable (fail-open)."""
    try:
        from app.services.redis_client import redis_client
        if redis_client:
            return bool(await redis_client.get(f"blacklisted_token:{_token_hash(token)}"))
    except Exception as e:
        logger.warning(f"Failed to check token blacklist in Redis: {e}")
    return False


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
                    SELECT id, email, password_hash, first_name, last_name, role, status,
                           job_title, department, failed_login_attempts, locked_until,
                           two_factor_enabled, two_factor_secret
                    FROM users WHERE email = :email
                """),
                {"email": email.lower()}
            )
            user_row = result.fetchone()
            
            if not user_row:
                logger.warning(f"Login attempt for non-existent user: {email}")
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
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'])
            
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
                "permissions": permissions
            }
            
            return user_data, None
    
    @staticmethod
    async def _get_user_permissions(session: AsyncSession, user_id: int, role: str) -> Dict:
        """Get user permissions including accessible stores and regions"""
        from sqlalchemy import text
        
        # Super admin has access to everything
        if role == 'super_admin':
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
        # Keep JWT payload minimal — permissions are looked up from DB on each request
        token_data = {
            "user_id": user_data["id"],
            "email": user_data["email"],
            "role": user_data["role"],
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
        token_data = decode_token(refresh_token)
        if not token_data:
            return None

        # Verify it's a refresh token
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None

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
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'])

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
                           job_title, department, last_login_at, created_at
                    FROM users WHERE id = :id
                """),
                {"id": user_id}
            )
            user_row = result.fetchone()
            
            if not user_row:
                return None
            
            user = dict(user_row._mapping)
            permissions = await AuthService._get_user_permissions(session, user['id'], user['role'])
            
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
            
            return True, "Password changed successfully"
    
    @staticmethod
    async def get_all_users(page: int = 1, limit: int = 50) -> Dict:
        """Get users (admin only), paginated to bound the result set."""
        page = max(1, page)
        limit = max(1, min(limit, 200))
        offset = (page - 1) * limit
        async with async_session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    SELECT id, email, first_name, last_name, role, status,
                           job_title, department, last_login_at, created_at
                    FROM users
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"limit": limit, "offset": offset},
            )
            users = [dict(row._mapping) for row in result.fetchall()]
            total = (await session.execute(text("SELECT COUNT(*) FROM users"))).scalar() or 0
            return {
                "users": users,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": max(1, (total + limit - 1) // limit),
            }
