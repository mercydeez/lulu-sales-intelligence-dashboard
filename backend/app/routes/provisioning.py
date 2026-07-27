"""E10-2 — tenant isolation-tier provisioning (platform control plane).

Mounted at /api/admin/provisioning. This is cross-tenant infrastructure control,
so every route is platform-developer only (`require_platform_developer`) — NEVER
role-gated: `super_admin` is a tenant role every self-signup owner holds, so a
role check here would let any customer drive other tenants' provisioning. It
governs the lifecycle that isolation.py enforces: a dedicated tier is served
only once it is provisioned `active` here.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, async_session
from app.services.platform_access import require_platform_developer
from app.services import provisioning as prov
from app.config import logger

router = APIRouter(tags=["Provisioning"])


class TierRequest(BaseModel):
    tenant_id: int
    tier: str = Field(..., pattern="^(shared|dedicated_schema|dedicated_db)$")


@router.get("/provisioning")
async def list_provisioning(user: dict = Depends(require_platform_developer), db: AsyncSession = Depends(get_db)):
    """Every tenant's provisioning state."""
    from sqlalchemy import text
    rows = (await db.execute(text("""
        SELECT tenant_id, tier, status, schema_name, db_ref, error,
               requested_by, requested_at, activated_at, deprovisioned_at
          FROM tenant_provisioning ORDER BY tenant_id
    """))).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("requested_at", "activated_at", "deprovisioned_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        out.append(d)
    return {"provisioning": out,
            "provisionable_tiers": list(prov.get_settings().supported_isolation_tiers)}


@router.get("/provisioning/{tenant_id}")
async def get_one(tenant_id: int, user: dict = Depends(require_platform_developer), db: AsyncSession = Depends(get_db)):
    rec = await prov.get_provisioning(db, tenant_id)
    if not rec:
        return {"tenant_id": tenant_id, "tier": "shared", "status": "none",
                "message": "No provisioning record — this tenant is on the default shared tier."}
    return rec


@router.post("/provisioning/request")
async def request_tier(body: TierRequest, user: dict = Depends(require_platform_developer),
                       db: AsyncSession = Depends(get_db)):
    """Record intent to move a tenant onto `tier`. Does not provision yet."""
    try:
        rec = await prov.request_tier(db, body.tenant_id, body.tier, actor=user.get("email") or "platform_developer")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    from app.services.security_events import record_event
    await record_event("tenant_tier_requested", category="audit", severity="medium",
                       tenant_id=body.tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Tenant {body.tenant_id} tier requested: {body.tier}")
    return rec


@router.post("/provisioning/{tenant_id}/provision")
async def provision(tenant_id: int, user: dict = Depends(require_platform_developer)):
    """Execute the data-plane provisioning for the tenant's requested tier.

    dedicated_schema is provisioned in full here (schema + isolated core tables).
    dedicated_db returns the operator runbook step, recorded as `provisioning`.
    """
    async with async_session() as db:
        try:
            rec = await prov.provision(db, tenant_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.error(f"Provisioning failed for tenant {tenant_id}: {e}")
            raise HTTPException(status_code=500,
                                detail={"error": "provisioning_failed", "message": str(e)})
    from app.services.security_events import record_event
    await record_event("tenant_provisioned", category="audit", severity="high",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Tenant {tenant_id} provisioned: {rec.get('tier')} -> {rec.get('status')}")
    return rec


@router.post("/provisioning/{tenant_id}/deprovision")
async def deprovision(tenant_id: int, force: bool = False, user: dict = Depends(require_platform_developer)):
    """Tear down a tenant's dedicated infrastructure and return them to shared."""
    async with async_session() as db:
        try:
            rec = await prov.deprovision(db, tenant_id, force=force)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    from app.services.security_events import record_event
    await record_event("tenant_deprovisioned", category="audit", severity="high",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Tenant {tenant_id} deprovisioned back to shared")
    return rec
