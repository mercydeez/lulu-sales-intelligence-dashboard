"""Platform Console — per-tenant customization routes (the bespoke knobs).

Mounted at /api/admin/dev/customizations. These are CROSS-TENANT control-plane
endpoints: every route is gated by `require_platform_developer` (fail-closed —
tenant super_admins are refused, see services/platform_access.py) and every query
runs on the OWNER session (`async_session`), never `get_db` — get_db binds the
caller's tenant GUC, so RLS would hide every other tenant's rows.

The engine itself lives in services/customization.py (pinned catalog + layered
resolution: catalog default -> plan floor -> tenant override). Routes here only
verify the tenant, translate ValueError -> 422, and commit.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.services.database import async_session
from app.services.platform_access import require_platform_developer
from app.services import customization

router = APIRouter(tags=["Customizations"])


class OverrideBody(BaseModel):
    value: Any = Field(..., description="The new override value (any JSON scalar matching the catalog type)")


async def _tenant_row(db, tenant_id: int):
    """Owner-session lookup: (id, name, plan) or None."""
    return (await db.execute(
        text("SELECT id, name, plan FROM tenants WHERE id = CAST(:t AS integer)"),
        {"t": tenant_id},
    )).fetchone()


@router.get("/dev/customizations/catalog")
async def get_catalog(user: dict = Depends(require_platform_developer)):
    """The pinned flag catalog — every knob, its type, plan floor, and (honestly)
    what enforces it ('planned' = not enforced anywhere yet)."""
    return {"catalog": customization.catalog()}


@router.get("/dev/customizations/{tenant_id}")
async def get_tenant_customizations(tenant_id: int,
                                    user: dict = Depends(require_platform_developer)):
    """One tenant's raw overrides plus the fully layered effective config."""
    async with async_session() as db:
        row = await _tenant_row(db, tenant_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        effective = await customization.resolve_effective(db, tenant_id)
        overrides = await customization.get_overrides(db, tenant_id)
    return {
        "tenant_id": tenant_id,
        "tenant_name": row[1],
        "plan": row[2],
        "effective": effective,
        "overrides": overrides,
    }


@router.put("/dev/customizations/{tenant_id}/{key}")
async def put_override(tenant_id: int, key: str, body: OverrideBody,
                       user: dict = Depends(require_platform_developer)):
    """Set one bespoke override (validated against the catalog, plan-gated)."""
    async with async_session() as db:
        row = await _tenant_row(db, tenant_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        try:
            effective = await customization.set_override(
                db, tenant_id, key, body.value,
                actor=user.get("email") or "platform_developer")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        await db.commit()
    return {"key": key, "value": body.value, "effective": effective}


@router.delete("/dev/customizations/{tenant_id}/{key}")
async def delete_override(tenant_id: int, key: str,
                          user: dict = Depends(require_platform_developer)):
    """Remove one override — the tenant reverts to plan/default for that key."""
    async with async_session() as db:
        try:
            await customization.clear_override(
                db, tenant_id, key,
                actor=user.get("email") or "platform_developer")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        await db.commit()
    return {"key": key, "reverted": True}
