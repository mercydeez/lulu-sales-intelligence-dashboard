"""
API-key management (B4). Authenticated, tenant-scoped CRUD for the per-tenant
keys that authorize the public API. A tenant admin manages only their own
tenant's keys; the plaintext key is returned exactly once, at creation.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import api_key_service as keys
from app.auth_deps import get_current_user

router = APIRouter()


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: Optional[List[str]] = None
    # Optional finite lifetime (1..3650 days). Omit for a non-expiring key.
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)


def _require_admin(user: dict) -> None:
    # Demo (2026-07-08): regional_manager opened alongside admin so the Developers
    # tab works for them (see role_experience full-nav change). Revert to
    # ("super_admin", "admin") to restore the stricter default.
    if user.get("role") not in ("super_admin", "admin", "regional_manager"):
        raise HTTPException(status_code=403, detail="Admin role required to manage API keys")


@router.post("")
async def create_api_key(
    body: CreateKeyRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    allowed_scopes = {"read", "write", "*"}
    scopes = body.scopes or ["read"]
    bad = [s for s in scopes if s not in allowed_scopes]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown scopes: {bad}")
    created = await keys.create_key(db, tenant_id, body.name, scopes, created_by=user.get("id"),
                                    expires_in_days=body.expires_in_days)
    from app.services.security_events import record_event
    await record_event("api_key_created", tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"API key '{body.name}' created (scopes: {', '.join(scopes)})",
                       evidence={"key_prefix": created.get("key_prefix"), "scopes": scopes,
                                 "expires_at": created.get("expires_at")})
    return created


@router.get("")
async def list_api_keys(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    return {"keys": await keys.list_keys(db, tenant_id)}


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    ok = await keys.revoke_key(db, tenant_id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    from app.services.security_events import record_event
    await record_event("api_key_revoked", tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"), detail=f"API key #{key_id} revoked",
                       evidence={"key_id": key_id})
    return {"success": True, "key_id": key_id, "revoked": True}
