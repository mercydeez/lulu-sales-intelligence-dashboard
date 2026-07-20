"""
Retention & Commercial Orchestration API — campaign lifecycle, real-time
decisioning and idempotent redemption. Tenant-scoped; store access follows the
existing region/store model; marketing mutations need can_manage_promotions;
approval needs an approver role (finance stand-in in the current role set).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import retention_service as ret
from app.auth_deps import (get_current_user, get_accessible_store_ids,
                           can_access_store, require_role)

router = APIRouter()


def _tenant(user: dict) -> int:
    return user.get("tenant_id") or 1


def _require_marketing(user: dict) -> None:
    if user.get("role") in ("super_admin", "admin"):
        return
    if not user.get("permissions", {}).get("can_manage_promotions"):
        raise HTTPException(status_code=403, detail="Promotions/marketing role required")


def _require_store(user: dict, store_id: int) -> None:
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="No access to this store")


_OBJECTIVES = {"churn_retention", "lapsed_reactivation", "basket_growth",
               "new_product_trial", "traffic_generation", "seasonal_event",
               "supplier_funded", "excess_stock_clearance", "near_expiry_waste",
               "category_growth"}


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    objective: str = Field("churn_retention")
    store_id: int
    item_id: int
    starts_on: date
    ends_on: date
    discount_budget_aed: Decimal = Field(..., ge=0)
    max_discount_pct: Decimal = Field(Decimal("15"), ge=0, le=90)
    min_margin_pct: Decimal = Field(Decimal("10"), ge=0, le=95)
    control_pct: Decimal = Field(Decimal("10"), ge=0, le=50)
    churn_threshold: float = Field(0.5, ge=0, le=1)
    safety_stock_units: int = Field(20, ge=0)


class LifecycleRequest(BaseModel):
    reason: Optional[str] = None


class EvaluateRequest(BaseModel):
    customer_id: int
    store_id: int
    channel: str = "pos"


class RedeemRequest(BaseModel):
    offer_id: int
    idempotency_key: str = Field(..., min_length=8, max_length=80)


# --- Campaigns --------------------------------------------------------------

@router.post("/campaigns", status_code=201)
async def create_campaign(body: CampaignCreate, user: dict = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    _require_store(user, body.store_id)
    if body.ends_on < body.starts_on:
        raise HTTPException(status_code=422, detail="ends_on must be >= starts_on")
    if body.objective not in _OBJECTIVES:
        raise HTTPException(status_code=422, detail=f"Unknown objective: {body.objective}")
    return await ret.create_campaign(
        db, _tenant(user), name=body.name, objective=body.objective,
        store_id=body.store_id, item_id=body.item_id, starts_on=body.starts_on,
        ends_on=body.ends_on, discount_budget_aed=body.discount_budget_aed,
        max_discount_pct=body.max_discount_pct, min_margin_pct=body.min_margin_pct,
        control_pct=body.control_pct, churn_threshold=body.churn_threshold,
        safety_stock_units=body.safety_stock_units, created_by=user.get("id"))


@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    return {"campaigns": await ret.list_campaigns(
        db, _tenant(user), get_accessible_store_ids(user))}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, user: dict = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        camp = await ret.get_campaign(db, _tenant(user), campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _require_store(user, camp["store_id"])
    return camp


async def _lifecycle_call(fn, campaign_id: int, user: dict, db: AsyncSession, **kw):
    try:
        return await fn(db, _tenant(user), campaign_id, **kw)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/campaigns/{campaign_id}/audience")
async def build_audience(campaign_id: int, user: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.build_audience, campaign_id, user, db,
                                 actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/simulate")
async def simulate(campaign_id: int, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.simulate, campaign_id, user, db,
                                 actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/scenario")
async def scenario(campaign_id: int, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    """Build the commercial decision pack (baseline, low/expected/high scenarios
    across offer depths, category effects, inventory/shelf-life, procurement
    options, finance, recommendation, department views). Read + compute only —
    no financial or inventory side effect. Persists the pack for reproducibility."""
    _require_marketing(user)
    from app.services.campaign_scenario import run_scenario
    try:
        camp = await ret.get_campaign(db, _tenant(user), campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _require_store(user, camp["store_id"])
    pack = await run_scenario(db, _tenant(user), camp, user.get("id"), persist=True)
    await db.commit()
    return pack


@router.post("/campaigns/{campaign_id}/submit")
async def submit(campaign_id: int, user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.submit, campaign_id, user, db,
                                 actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/approve")
async def approve(campaign_id: int,
                  user: dict = Depends(require_role("super_admin", "regional_manager")),
                  db: AsyncSession = Depends(get_db)):
    return await _lifecycle_call(ret.approve, campaign_id, user, db,
                                 actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/activate")
async def activate(campaign_id: int, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.activate, campaign_id, user, db,
                                 actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/pause")
async def pause(campaign_id: int, body: LifecycleRequest,
                user: dict = Depends(get_current_user),
                db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.set_lifecycle, campaign_id, user, db,
                                 new_status="paused", actor=user.get("id"),
                                 reason=body.reason or "manual pause")


@router.post("/campaigns/{campaign_id}/resume")
async def resume(campaign_id: int, user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.set_lifecycle, campaign_id, user, db,
                                 new_status="active", actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/complete")
async def complete(campaign_id: int, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.set_lifecycle, campaign_id, user, db,
                                 new_status="completed", actor=user.get("id"))


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel(campaign_id: int, body: LifecycleRequest,
                 user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return await _lifecycle_call(ret.set_lifecycle, campaign_id, user, db,
                                 new_status="cancelled", actor=user.get("id"),
                                 reason=body.reason)


@router.get("/campaigns/{campaign_id}/offers")
async def offers(campaign_id: int, limit: int = Query(200, le=500),
                 user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_marketing(user)  # decision trace is for authorized users only
    return {"offers": await ret.list_offers(db, _tenant(user), campaign_id, limit)}


@router.get("/campaigns/{campaign_id}/outcomes")
async def outcomes(campaign_id: int, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return await _lifecycle_call(ret.outcomes, campaign_id, user, db)


# --- Real-time decision + redemption ---------------------------------------

@router.post("/evaluate")
async def evaluate(body: EvaluateRequest, user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    _require_store(user, body.store_id)
    return await ret.evaluate(db, _tenant(user), body.customer_id, body.store_id)


@router.post("/redeem")
async def redeem(body: RedeemRequest, user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    try:
        return await ret.redeem(db, _tenant(user), body.offer_id,
                                body.idempotency_key, actor=user.get("id"))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


# --- Customers + model card -------------------------------------------------

@router.get("/customers")
async def customers(limit: int = Query(200, le=500),
                    user: dict = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    _require_marketing(user)
    return {"customers": await ret.list_customers(
        db, _tenant(user), get_accessible_store_ids(user), limit),
        "synthetic_data": True}


@router.get("/model")
async def model(user: dict = Depends(get_current_user)):
    return ret.model_card()
