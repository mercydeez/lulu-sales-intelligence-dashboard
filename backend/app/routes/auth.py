"""
Authentication Routes - Login, Logout, Token Management
"""
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional, List
from datetime import datetime

from app.services.auth_service import (
    AuthService, UserLogin, Token, UserResponse, 
    PasswordChange, decode_token, UserCreate
)
from app.config import logger

router = APIRouter()
security = HTTPBearer(auto_error=False)


# =============================================================================
# DEPENDENCY - Get Current User
# =============================================================================

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """Dependency to get current authenticated user"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token_data = decode_token(credentials.credentials)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Check token expiration
    if token_data.exp < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token has expired")
    
    # Get fresh user data
    user = await AuthService.get_user_by_id(token_data.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if user['status'] != 'active':
        raise HTTPException(status_code=401, detail="Account is not active")
    
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[dict]:
    """Optional user authentication"""
    if not credentials:
        return None
    
    token_data = decode_token(credentials.credentials)
    if not token_data or token_data.exp < datetime.utcnow():
        return None
    
    return await AuthService.get_user_by_id(token_data.user_id)


def require_role(*roles: str):
    """Dependency factory to require specific roles"""
    async def role_checker(user: dict = Depends(get_current_user)) -> dict:
        if user['role'] not in roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. Required role: {', '.join(roles)}"
            )
        return user
    return role_checker


def require_permission(permission: str):
    """Dependency factory to require specific permission"""
    async def permission_checker(user: dict = Depends(get_current_user)) -> dict:
        if not user.get('permissions', {}).get(permission):
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


class MessageResponse(BaseModel):
    message: str
    success: bool = True


# =============================================================================
# ROUTES
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(request: Request, login_data: LoginRequest):
    """
    Authenticate user and return JWT tokens
    
    - **email**: User's email address
    - **password**: User's password
    - **remember_me**: If true, token expires in 7 days instead of 30 minutes
    """
    # Get client IP
    ip_address = request.client.host if request.client else None
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
    
    # Create tokens
    tokens = await AuthService.create_tokens(user_data, login_data.remember_me)
    
    logger.info(f"User logged in: {user_data['email']} (role: {user_data['role']})")
    
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(refresh_data: RefreshRequest):
    """
    Refresh access token using refresh token
    """
    tokens = await AuthService.refresh_access_token(refresh_data.refresh_token)
    
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        user=tokens.user
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """
    Logout current user and invalidate token
    """
    ip_address = request.client.host if request.client else None
    
    # Extract token from Authorization header to blacklist it
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    
    await AuthService.logout(user['id'], ip_address, token=token)
    
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


@router.get("/users", response_model=List[dict])
async def list_users(user: dict = Depends(require_role('super_admin'))):
    """
    List all users (Super Admin only)
    """
    users = await AuthService.get_all_users()
    return users


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
