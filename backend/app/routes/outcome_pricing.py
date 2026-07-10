"""
Outcome-based pricing API. Mounted at /api/outcome-pricing.

Tenant admins configure the plan and confirm realised value; an operator can turn a
statement into a draft VAT invoice via the existing billing layer. Tenant-scoped.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, async_session
from app.services import outcome_pricing as svc
from app.routes.auth import get_current_user

router = APIRouter(tags=["Outcome Pricing"])


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")


class PlanUpdate(BaseModel):
    base_fee_aed: float = Field(0, ge=0)
    value_share_pct: float = Field(0, ge=0, le=100)
    savings_guarantee_multiple: float = Field(0, ge=0)
    active: bool = False


class RealizationUpdate(BaseModel):
    confirmed_value_aed: Optional[float] = Field(None, ge=0)
    status: str = "confirmed"
    note: Optional[str] = None


class DisputeRequest(BaseModel):
    # A dispute nobody can read is a dispute nobody can resolve.
    reason: str = Field(..., min_length=3, max_length=2000)


class DisputeResolution(BaseModel):
    # About the DISPUTE, not the value: accepted => the customer was right.
    resolution: str = Field(..., pattern="^(accepted|rejected)$")
    note: Optional[str] = None


@router.get("/plan")
async def get_plan(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    return await svc.get_plan(db, user.get("tenant_id") or 1)


@router.put("/plan")
async def put_plan(body: PlanUpdate, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    plan = await svc.upsert_plan(db, user.get("tenant_id") or 1,
                                 base_fee_aed=body.base_fee_aed, value_share_pct=body.value_share_pct,
                                 savings_guarantee_multiple=body.savings_guarantee_multiple,
                                 active=body.active)
    from app.services.security_events import record_event
    await record_event("outcome_plan_updated", category="audit", severity="low",
                       tenant_id=user.get("tenant_id") or 1, actor_user_id=user.get("id"),
                       actor_email=user.get("email"), detail="Outcome pricing plan updated")
    return plan


@router.get("/realizations")
async def list_realizations(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    return {"realizations": await svc.list_realizations(db, user.get("tenant_id") or 1)}


@router.post("/realizations/{realization_id}")
async def set_realization(realization_id: int, body: RealizationUpdate,
                          user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    if body.status == "confirmed" and (body.confirmed_value_aed is None):
        raise HTTPException(status_code=422, detail="A confirmed value (AED) is required to confirm")
    if body.status == "disputed":
        # A dispute needs a reason and a state machine; it is not a status you set.
        raise HTTPException(
            status_code=422,
            detail="Use POST /realizations/{id}/dispute to contest a confirmed value")
    row = await svc.set_realization(db, user.get("tenant_id") or 1, realization_id,
                                    confirmed_value_aed=body.confirmed_value_aed,
                                    status=body.status, note=body.note,
                                    user=user.get("email") or "operator")
    if row is None:
        raise HTTPException(status_code=404, detail="Realization not found")
    from app.services.security_events import record_event
    await record_event("value_realization_set", category="audit", severity="low",
                       tenant_id=user.get("tenant_id") or 1, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Realization {realization_id} {body.status}",
                       evidence={"value_aed": body.confirmed_value_aed})
    return row


@router.post("/realizations/{realization_id}/dispute")
async def dispute_realization(realization_id: int, body: DisputeRequest,
                              user: dict = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """E8-5: contest a confirmed value. Raised by the party being billed.

    Succeeds only from `confirmed` — a pending or dismissed line was never billed,
    so there is nothing to contest, and we return 409 rather than silently doing
    nothing. The disputed amount leaves the billable total immediately.
    """
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    row = await svc.dispute_realization(db, tenant_id, realization_id,
                                        reason=body.reason,
                                        user=user.get("email") or "operator")
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="Only a confirmed realization can be disputed (it may already be "
                   "disputed, dismissed, or still pending)")
    from app.services.security_events import record_event
    await record_event("value_realization_disputed", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Realization {realization_id} disputed",
                       evidence={"reason": body.reason,
                                 "value_aed": row.get("confirmed_value_aed")})
    return row


@router.post("/realizations/{realization_id}/resolve-dispute")
async def resolve_dispute(realization_id: int, body: DisputeResolution,
                          user: dict = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Close a dispute. Vendor-side only.

    The tenant admin raises a dispute against their own invoice; the operator who
    issues that invoice resolves it. Letting the billed party also decide the
    outcome would make the dispute state decorative.
    """
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    tenant_id = user.get("tenant_id") or 1
    row = await svc.resolve_dispute(db, tenant_id, realization_id,
                                    resolution=body.resolution, note=body.note,
                                    user=user.get("email") or "operator")
    if row is None:
        raise HTTPException(status_code=409, detail="No open dispute on this realization")
    from app.services.security_events import record_event
    await record_event("value_realization_dispute_resolved", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Realization {realization_id} dispute {body.resolution}",
                       evidence={"resolution": body.resolution,
                                 "resulting_status": row.get("status")})
    return row


@router.get("/statement")
async def get_statement(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    return await svc.statement(db, user.get("tenant_id") or 1)


@router.post("/invoice")
async def invoice_from_statement(user: dict = Depends(get_current_user)):
    """Turn the current outcome statement into a draft VAT invoice (operator only)."""
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    tenant_id = user.get("tenant_id") or 1
    from app.services import billing as billing_svc
    async with async_session() as session:
        stmt = await svc.statement(session, tenant_id)
        lines = [{"description": "Outcome pricing — base fee",
                  "quantity": 1, "unit_price_aed": stmt["base_fee_aed"]}]
        if stmt["variable_fee_aed"] > 0:
            lines.append({"description": f"Outcome pricing — {stmt['value_share_pct']}% of "
                                         f"AED {stmt['confirmed_value_aed']:,.0f} confirmed value",
                          "quantity": 1, "unit_price_aed": stmt["variable_fee_aed"]})
        result = await billing_svc.create_invoice(
            session, tenant_id, lines=lines, billing_provider="manual",
            payment_terms="Net 30",
            payment_instructions="Outcome-based fee — value-share billed on operator-confirmed savings.")
        await session.commit()
    return {**result, "statement": stmt,
            "note": "Draft invoice from confirmed outcomes. VAT/legal review required."}
