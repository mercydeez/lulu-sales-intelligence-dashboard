"""
Tenant management API (multi-tenancy foundation).

Mounted at /api/tenants by main.py. Super-admin only for now; once tenant-scoped
auth lands, tenant admins will manage their own tenant here.
"""
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.services.database import async_session
from app.routes.auth import get_current_user
from app.config import logger

router = APIRouter(tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    plan: str = "free"
    brand_name: Optional[str] = None
    accent_color: Optional[str] = None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:63] or "tenant"


def _row_to_tenant(row) -> dict:
    return {
        "id": row[0],
        "slug": row[1],
        "name": row[2],
        "plan": row[3],
        "status": row[4],
        "brand_name": row[5],
        "accent_color": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
        "user_count": row[8],
    }


@router.get("")
async def list_tenants(current_user: dict = Depends(get_current_user)):
    """List all tenants (super-admin only)."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    async with async_session() as session:
        try:
            result = await session.execute(text("""
                SELECT t.id, t.slug, t.name, t.plan, t.status,
                       t.brand_name, t.accent_color, t.created_at,
                       (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) AS user_count
                FROM tenants t
                ORDER BY t.id
            """))
            tenants = [_row_to_tenant(r) for r in result.fetchall()]
            return {"tenants": tenants, "total": len(tenants)}
        except Exception as e:
            logger.error(f"List tenants error: {e}")
            return {"tenants": [], "total": 0}


@router.post("", status_code=201)
async def create_tenant(payload: TenantCreate, current_user: dict = Depends(get_current_user)):
    """Create a new tenant (super-admin only)."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tenant name is required")
    slug = _slugify(payload.slug or name)
    plan = payload.plan if payload.plan in {"free", "starter", "growth", "enterprise"} else "free"

    async with async_session() as session:
        try:
            exists = await session.execute(
                text("SELECT 1 FROM tenants WHERE slug = :slug"), {"slug": slug}
            )
            if exists.fetchone():
                raise HTTPException(status_code=409, detail=f"A tenant with slug '{slug}' already exists")

            result = await session.execute(
                text("""
                    INSERT INTO tenants (slug, name, plan, status, brand_name, accent_color)
                    VALUES (:slug, :name, :plan, 'active', :brand_name, :accent_color)
                    RETURNING id, slug, name, plan, status, brand_name, accent_color, created_at, 0
                """),
                {
                    "slug": slug,
                    "name": name,
                    "plan": plan,
                    "brand_name": payload.brand_name or name,
                    "accent_color": payload.accent_color or "#0f766e",
                },
            )
            row = result.fetchone()
            await session.commit()
            logger.info(f"Super-admin {current_user.get('email')} created tenant '{slug}'")
            return _row_to_tenant(row)
        except HTTPException:
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Create tenant error: {e}")
            raise HTTPException(status_code=500, detail="Failed to create tenant")
