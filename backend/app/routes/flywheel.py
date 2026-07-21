"""Flywheel API — retention & commercial orchestration.

Every route depends on the platform's existing auth (`get_current_user`,
`require_permission`) and scopes by `user['tenant_id']` plus
`get_accessible_store_ids`. Flywheel introduces NO parallel authorization.

TRANSACTION DISCIPLINE: routes that move money or stock let `get_db` own the
commit — it commits on clean return and rolls back on exception. That is what
makes redemption atomic across inventory, budget, redemption row and outbox.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_deps import (
    get_accessible_store_ids, get_current_user, require_permission,
)
from app.services.database import get_db
from app.services.flywheel import (
    allocator, approvals, budget as budget_service, campaign_state,
    campaigns as campaign_service, cannibalization, churn as churn_service,
    coalition, contact_governance, data_trust, decisioning, erasure,
    features as feature_service,
    guardrails, identity, inventory_atp, jobs, liability, measurement, metering,
    objections, optimizer, outbox, outcome_pricing, procurement, readout, registry,
    seasonality, seeder, sequential, shadow, shelf_life, tax, trade, trace,
    uplift as uplift_service,
)
from app.services.flywheel.budget import BudgetError, InsufficientBudget
from app.services.flywheel.data_trust import DataNotReady
from app.services.flywheel.campaign_state import TransitionError
from app.services.flywheel.types import BudgetType, CampaignStatus, money

logger = logging.getLogger(__name__)
router = APIRouter()


def _tenant(user: Dict[str, Any]) -> int:
    return int(user.get("tenant_id") or 1)


def _request_id(request: Request) -> Optional[str]:
    return request.headers.get("x-request-id")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    objective: str = Field("retain_at_risk")
    starts_on: date
    ends_on: date
    channel: str = "email"
    max_discount_pct: Decimal = Decimal("20")
    min_margin_pct: Decimal = Decimal("10")
    discount_budget_aed: Decimal = Decimal("0")
    procurement_budget_aed: Decimal = Decimal("0")
    safety_stock_pct: Decimal = Decimal("10")
    control_group_pct: Decimal = Decimal("20")
    contact_cap_per_week: int = 2
    audience_spec: Dict[str, Any] = Field(default_factory=dict)


class AudienceRequest(BaseModel):
    min_churn_probability: float = 0.25
    max_size: int = 5000


class EvaluateRequest(BaseModel):
    """§16 — the real-time decision input."""
    customer_id: int
    store_id: int
    channel: str = "email"
    cart_items: Optional[List[int]] = None
    campaign_id: Optional[int] = None
    idempotency_key: Optional[str] = None
    issue_offer: bool = True


class RedeemRequest(BaseModel):
    offer_code: str
    units: int = Field(1, ge=1)
    idempotency_key: str = Field(..., min_length=8, max_length=120)
    store_id: Optional[int] = None


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected|changes_requested)$")
    comment: Optional[str] = None


class SeedRequest(BaseModel):
    customer_count: int = Field(600, ge=10, le=5000)
    history_days: int = Field(365, ge=90, le=730)
    seed: int = 42
    force: bool = False


# ---------------------------------------------------------------------------
# Stage 1 — data foundation
# ---------------------------------------------------------------------------

@router.post("/seed", summary="Generate the synthetic customer layer")
async def seed(
    body: SeedRequest,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Fixed-seed synthetic customers, events and consents. Idempotent unless
    `force=true`. Data is stamped synthetic and confined to the caller's tenant."""
    result = await seeder.seed_customers(
        db, tenant_id=_tenant(user), customer_count=body.customer_count,
        history_days=body.history_days, seed=body.seed, force=body.force)
    return {"success": True, **result}


@router.get("/customers", summary="Browse the synthetic customer population")
async def list_customers(
    risk_band: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    stores = get_accessible_store_ids(user)
    store_clause = "AND c.home_store_id = ANY(:stores)" if stores else ""
    band_clause = "AND p.risk_band = :band" if risk_band else ""

    params: Dict[str, Any] = {"t": tenant_id, "lim": limit, "off": offset}
    if stores:
        params["stores"] = stores
    if risk_band:
        params["band"] = risk_band

    rows = (await db.execute(
        text(f"""SELECT c.id, c.external_ref, c.display_name, c.home_store_id, s.name,
                        c.loyalty_tier, c.status, c.archetype,
                        p.churn_probability, p.risk_band, p.reason_codes
                   FROM flywheel_customers c
                   JOIN stores s ON s.id = c.home_store_id
                   LEFT JOIN LATERAL (
                        SELECT churn_probability, risk_band, reason_codes
                          FROM flywheel_churn_predictions
                         WHERE customer_id = c.id AND tenant_id = c.tenant_id
                         ORDER BY as_of_date DESC LIMIT 1
                   ) p ON TRUE
                  WHERE c.tenant_id = :t {store_clause} {band_clause}
                  ORDER BY p.churn_probability DESC NULLS LAST, c.id
                  LIMIT :lim OFFSET :off"""),
        params,
    )).fetchall()

    return {
        "customers": [{
            "id": int(r[0]), "external_ref": r[1], "display_name": r[2],
            "store_id": int(r[3]), "store_name": r[4], "loyalty_tier": r[5],
            "status": r[6], "archetype": r[7],
            "churn_probability": float(r[8]) if r[8] is not None else None,
            "risk_band": r[9], "reason_codes": r[10] or [],
        } for r in rows],
        "limit": limit, "offset": offset,
        "synthetic": True,
        "disclaimer": "Synthetic customers. No real personal data.",
    }


@router.get("/customers/{customer_id}", summary="Customer 360 (synthetic)")
async def customer_detail(
    customer_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    header = (await db.execute(
        text("""SELECT c.id, c.display_name, c.external_ref, c.home_store_id, s.name,
                       c.loyalty_tier, c.status, c.archetype, c.enrolled_on
                  FROM flywheel_customers c JOIN stores s ON s.id = c.home_store_id
                 WHERE c.id = :c AND c.tenant_id = :t"""),
        {"c": customer_id, "t": tenant_id},
    )).fetchone()
    if not header:
        raise HTTPException(404, "Customer not found")

    stores = get_accessible_store_ids(user)
    if stores and int(header[3]) not in stores:
        raise HTTPException(403, "Customer's home store is outside your access scope")

    score = await churn_service.get_score(db, tenant_id=tenant_id, customer_id=customer_id)
    as_of = await feature_service.latest_snapshot_date(db, tenant_id) or date.today()
    feats = await feature_service.load_snapshot(
        db, tenant_id=tenant_id, customer_id=customer_id, as_of=as_of)

    events = (await db.execute(
        text("""SELECT event_type, occurred_at, item_id, category,
                       quantity_units, value_aed
                  FROM flywheel_customer_events
                 WHERE tenant_id = :t AND customer_id = :c
                 ORDER BY occurred_at DESC LIMIT 40"""),
        {"t": tenant_id, "c": customer_id},
    )).fetchall()

    consents = (await db.execute(
        text("""SELECT channel, granted, max_contacts_per_week
                  FROM flywheel_customer_consents
                 WHERE tenant_id = :t AND customer_id = :c ORDER BY channel"""),
        {"t": tenant_id, "c": customer_id},
    )).fetchall()

    contacts_week = int((await db.execute(
        text("""SELECT COUNT(*) FROM flywheel_contact_log
                 WHERE tenant_id = :t AND customer_id = :c
                   AND contacted_at >= now() - INTERVAL '7 days'"""),
        {"t": tenant_id, "c": customer_id},
    )).scalar() or 0)

    offers = (await db.execute(
        text("""SELECT offer_code, action_type, discount_pct, status, issued_at, expires_at
                  FROM flywheel_offers WHERE tenant_id = :t AND customer_id = :c
                 ORDER BY issued_at DESC LIMIT 20"""),
        {"t": tenant_id, "c": customer_id},
    )).fetchall()

    return {
        "customer": {
            "id": int(header[0]), "display_name": header[1], "external_ref": header[2],
            "store_id": int(header[3]), "store_name": header[4],
            "loyalty_tier": header[5], "status": header[6],
            "archetype": header[7], "enrolled_on": str(header[8]),
        },
        "churn": score,
        "features": {k: (float(v) if isinstance(v, Decimal) else v)
                     for k, v in (feats or {}).items()},
        "events": [{"type": e[0], "at": e[1].isoformat(), "item_id": e[2],
                    "category": e[3], "units": int(e[4]), "value_aed": str(money(e[5]))}
                   for e in events],
        "consents": [{"channel": c[0], "granted": bool(c[1]),
                      "max_per_week": int(c[2])} for c in consents],
        "contact_status": {"contacts_last_7_days": contacts_week},
        "offers": [{"offer_code": o[0], "action": o[1], "discount_pct": str(o[2]),
                    "status": o[3], "issued_at": o[4].isoformat(),
                    "expires_at": o[5].isoformat()} for o in offers],
        "synthetic": True,
    }


# ---------------------------------------------------------------------------
# Stage 2 — intelligence
# ---------------------------------------------------------------------------

@router.post("/features/build", summary="Build point-in-time feature snapshots")
async def build_features(
    as_of: Optional[date] = Query(None),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await feature_service.build_snapshots(db, tenant_id=_tenant(user), as_of=as_of)


@router.post("/churn/score", summary="Score churn risk for the population")
async def score_churn(
    as_of: Optional[date] = Query(None),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await churn_service.score_customers(db, tenant_id=_tenant(user), as_of=as_of)


@router.get("/models", summary="Registered model versions and their metrics")
async def list_models(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""SELECT id, model_kind, algorithm, version_label, metrics, is_active,
                       trained_at, feature_window_days, outcome_window_days,
                       random_seed, notes
                  FROM flywheel_model_versions WHERE tenant_id = :t
                 ORDER BY model_kind, trained_at DESC NULLS LAST"""),
        {"t": _tenant(user)},
    )).fetchall()
    return {
        "models": [{
            "id": int(r[0]), "kind": r[1], "algorithm": r[2], "version": r[3],
            "metrics": r[4] or {}, "is_active": bool(r[5]),
            "trained_at": r[6].isoformat() if r[6] else None,
            "feature_window_days": int(r[7]), "outcome_window_days": int(r[8]),
            "random_seed": int(r[9]), "notes": r[10],
        } for r in rows],
        "honesty_note": "Metrics are computed on synthetic holdouts. "
                        "No production accuracy is claimed.",
    }


# ---------------------------------------------------------------------------
# Stage 3–4 — campaigns
# ---------------------------------------------------------------------------

@router.post("/campaigns", summary="Create a campaign draft")
async def create_campaign(
    body: CampaignCreate,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    if body.ends_on < body.starts_on:
        raise HTTPException(400, "ends_on must be on or after starts_on")

    import json
    row = (await db.execute(
        text("""INSERT INTO flywheel_campaigns
                   (tenant_id, name, objective, status, starts_on, ends_on, channel,
                    max_discount_pct, min_margin_pct, discount_budget_aed,
                    procurement_budget_aed, safety_stock_pct, control_group_pct,
                    contact_cap_per_week, audience_spec, created_by)
                VALUES (:t, :n, :o, 'DRAFT', :s, :e, :ch, :maxd, :minm, :db, :pb,
                        :ss, :cg, :cap, CAST(:spec AS JSONB), :by)
                RETURNING id"""),
        {"t": _tenant(user), "n": body.name, "o": body.objective,
         "s": body.starts_on, "e": body.ends_on, "ch": body.channel,
         "maxd": body.max_discount_pct, "minm": body.min_margin_pct,
         "db": body.discount_budget_aed, "pb": body.procurement_budget_aed,
         "ss": body.safety_stock_pct, "cg": body.control_group_pct,
         "cap": body.contact_cap_per_week, "spec": json.dumps(body.audience_spec),
         "by": user.get("id")},
    )).fetchone()

    campaign_id = int(row[0])
    await db.execute(
        text("""INSERT INTO flywheel_campaign_transitions
                   (tenant_id, campaign_id, from_status, to_status, actor_user_id, reason)
                VALUES (:t, :c, NULL, 'DRAFT', :u, 'Campaign created')"""),
        {"t": _tenant(user), "c": campaign_id, "u": user.get("id")},
    )
    return {"campaign_id": campaign_id, "status": "DRAFT", "name": body.name}


@router.get("/campaigns", summary="List campaigns")
async def list_campaigns(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clause = "AND c.status = :st" if status else ""
    params: Dict[str, Any] = {"t": _tenant(user), "lim": limit}
    if status:
        params["st"] = status

    rows = (await db.execute(
        text(f"""SELECT c.id, c.name, c.objective, c.status, c.starts_on, c.ends_on,
                        c.discount_budget_aed, c.control_group_pct, c.pause_reason,
                        c.created_at,
                        (SELECT COUNT(*) FROM flywheel_campaign_audience a
                          WHERE a.campaign_id = c.id AND a.assignment = 'treatment'),
                        (SELECT COUNT(*) FROM flywheel_campaign_audience a
                          WHERE a.campaign_id = c.id AND a.assignment = 'control'),
                        (SELECT COUNT(*) FROM flywheel_redemptions r WHERE r.campaign_id = c.id)
                   FROM flywheel_campaigns c
                  WHERE c.tenant_id = :t {clause}
                  ORDER BY c.created_at DESC LIMIT :lim"""),
        params,
    )).fetchall()

    return {"campaigns": [{
        "id": int(r[0]), "name": r[1], "objective": r[2], "status": r[3],
        "starts_on": str(r[4]), "ends_on": str(r[5]),
        "discount_budget_aed": str(money(r[6])),
        "control_group_pct": float(r[7]), "pause_reason": r[8],
        "created_at": r[9].isoformat() if r[9] else None,
        "treatment_size": int(r[10]), "control_size": int(r[11]),
        "redemptions": int(r[12]),
    } for r in rows]}


@router.get("/campaigns/{campaign_id}", summary="Campaign detail + history")
async def campaign_detail(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    row = (await db.execute(
        text("""SELECT id, name, objective, status, starts_on, ends_on, channel,
                       max_discount_pct, min_margin_pct, discount_budget_aed,
                       procurement_budget_aed, safety_stock_pct, control_group_pct,
                       contact_cap_per_week, audience_spec, policy_version,
                       pause_reason, activated_at, created_at
                  FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not row:
        raise HTTPException(404, "Campaign not found")

    history = (await db.execute(
        text("""SELECT t.from_status, t.to_status, t.actor_kind, t.reason,
                       t.created_at, u.email
                  FROM flywheel_campaign_transitions t
                  LEFT JOIN users u ON u.id = t.actor_user_id
                 WHERE t.campaign_id = :c AND t.tenant_id = :t
                 ORDER BY t.created_at"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchall()

    audience = (await db.execute(
        text("""SELECT assignment, COUNT(*), AVG(churn_probability)
                  FROM flywheel_campaign_audience
                 WHERE campaign_id = :c AND tenant_id = :t GROUP BY assignment"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchall()

    exposure = await budget_service.campaign_exposure(
        db, tenant_id=tenant_id, campaign_id=campaign_id)

    current = CampaignStatus(row[3])
    return {
        "campaign": {
            "id": int(row[0]), "name": row[1], "objective": row[2], "status": row[3],
            "starts_on": str(row[4]), "ends_on": str(row[5]), "channel": row[6],
            "max_discount_pct": float(row[7]), "min_margin_pct": float(row[8]),
            "discount_budget_aed": str(money(row[9])),
            "procurement_budget_aed": str(money(row[10])),
            "safety_stock_pct": float(row[11]), "control_group_pct": float(row[12]),
            "contact_cap_per_week": int(row[13]), "audience_spec": row[14] or {},
            "policy_version": row[15], "pause_reason": row[16],
            "activated_at": row[17].isoformat() if row[17] else None,
            "created_at": row[18].isoformat() if row[18] else None,
        },
        "allowed_transitions": sorted(
            s.value for s in campaign_state.TRANSITIONS.get(current, set())),
        "history": [{"from": h[0], "to": h[1], "actor_kind": h[2], "reason": h[3],
                     "at": h[4].isoformat(), "actor": h[5]} for h in history],
        "audience": {a[0]: {"size": int(a[1]),
                            "avg_churn": round(float(a[2]), 4) if a[2] else None}
                     for a in audience},
        "budget_exposure": exposure,
    }


@router.post("/campaigns/{campaign_id}/audience", summary="Build the eligible audience")
async def build_audience(
    campaign_id: int, body: AudienceRequest,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await campaign_service.build_audience(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            min_churn_probability=body.min_churn_probability, max_size=body.max_size,
            accessible_store_ids=get_accessible_store_ids(user) or None)
    except DataNotReady as exc:
        # 422: the request is well-formed, the DATA is not fit to decide on.
        # A STRING, not a dict: the app-wide error handler assigns exc.detail
        # straight to the envelope's "message" field, so a dict here produces a
        # malformed message. The structured report stays available on the
        # dedicated GET .../data-trust endpoint, which the UI already holds.
        raise HTTPException(422, str(exc))
    except TransitionError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/campaigns/{campaign_id}/simulate", summary="Simulate outcomes (no commitment)")
async def simulate_campaign(
    campaign_id: int,
    sample_size: int = Query(400, ge=50, le=2000),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await campaign_service.simulate(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            sample_size=sample_size,
            accessible_store_ids=get_accessible_store_ids(user) or None)
    except TransitionError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/campaigns/{campaign_id}/data-trust",
            summary="Is the input data fit to decide on? (READY / WARNINGS / NOT_READY)")
async def campaign_data_trust(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Read-only. The same gate simulate() and activate() enforce, exposed so an
    operator can see WHY a campaign will be refused before attempting it."""
    return await data_trust.evaluate(
        db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.get("/data-trust", summary="Tenant-wide data readiness")
async def tenant_data_trust(
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Campaign-independent view — the onboarding check for a new data feed."""
    return await data_trust.evaluate(db, tenant_id=_tenant(user), campaign_id=None)


@router.post("/campaigns/{campaign_id}/submit", summary="Submit for approval")
async def submit_campaign(
    campaign_id: int,
    sample_size: int = Query(400, ge=50, le=2000),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Re-simulates first so the approval chain is sized on CURRENT numbers,
    not on a simulation the operator ran an hour ago."""
    try:
        simulation = await campaign_service.simulate(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            sample_size=sample_size,
            accessible_store_ids=get_accessible_store_ids(user) or None)
        result = await campaign_service.submit_for_approval(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            simulation=simulation, user=user)
        return {**result, "simulation": simulation}
    except TransitionError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/campaigns/{campaign_id}/activate", summary="Activate an approved campaign")
async def activate_campaign(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    # Activation reserves what the APPROVAL recorded, so no re-simulation is
    # needed or wanted here. An earlier version re-simulated and swallowed the
    # resulting error; because simulating an APPROVED campaign raises (that
    # transition is illegal), activation silently fell back to reserving the
    # whole declared budget and placed zero inventory allocations. The bug was
    # invisible precisely because the exception was caught and discarded.
    try:
        return await campaign_service.activate(
            db, tenant_id=_tenant(user), campaign_id=campaign_id, user=user)
    except DataNotReady as exc:
        raise HTTPException(422, str(exc))
    except InsufficientBudget as exc:
        raise HTTPException(409, str(exc))
    except (TransitionError, BudgetError) as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/campaigns/{campaign_id}/pause", summary="Pause a live campaign")
async def pause_campaign(
    campaign_id: int, reason: str = Query(..., min_length=3),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await campaign_state.transition(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            target=CampaignStatus.PAUSED, actor_user_id=user.get("id"),
            reason=reason, pause_reason=reason)
        return {"campaign_id": campaign_id, "status": "PAUSED", "reason": reason}
    except TransitionError as exc:
        raise HTTPException(409, str(exc))


@router.post("/campaigns/{campaign_id}/resume", summary="Resume a paused campaign")
async def resume_campaign(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Re-runs guardrails first: resuming into the same breach that paused the
    campaign would just pause it again on the next redemption."""
    tenant_id = _tenant(user)
    check = await guardrails.check_campaign(
        db, tenant_id=tenant_id, campaign_id=campaign_id, auto_pause=False)
    if check.get("hard_breaches"):
        raise HTTPException(409, {
            "error": "Cannot resume — the breach that paused this campaign is unresolved",
            "breaches": check["breaches"],
        })
    try:
        await campaign_state.transition(
            db, tenant_id=tenant_id, campaign_id=campaign_id,
            target=CampaignStatus.ACTIVE, actor_user_id=user.get("id"),
            reason="Resumed after guardrail check passed")
        return {"campaign_id": campaign_id, "status": "ACTIVE"}
    except TransitionError as exc:
        raise HTTPException(409, str(exc))


@router.post("/campaigns/{campaign_id}/conclude", summary="Complete or cancel")
async def conclude_campaign(
    campaign_id: int, cancel: bool = Query(False),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await campaign_service.conclude(
            db, tenant_id=_tenant(user), campaign_id=campaign_id, user=user, cancel=cancel)
    except TransitionError as exc:
        raise HTTPException(409, str(exc))


# ---------------------------------------------------------------------------
# Stage 4 — inventory, procurement, budget, approvals
# ---------------------------------------------------------------------------

@router.get("/inventory/atp", summary="Available-to-promise for a store × item")
async def get_atp(
    store_id: int, item_id: int,
    safety_stock_pct: Decimal = Query(Decimal("10")),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stores = get_accessible_store_ids(user)
    if stores and store_id not in stores:
        raise HTTPException(403, "Store outside your access scope")
    atp = await inventory_atp.compute_atp(
        db, tenant_id=_tenant(user), store_id=store_id, item_id=item_id,
        safety_stock_pct=safety_stock_pct)
    return {**atp.to_snapshot(),
            "formula": "ATP = on_hand + incoming − hard_reservations "
                       "− soft_allocations − safety_stock − demand_buffer"}


@router.get("/campaigns/{campaign_id}/procurement", summary="Requisitions for a campaign")
async def campaign_procurement(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""SELECT r.id, r.store_id, s.name, r.item_id, i.name, sup.name,
                       r.shortage_units, r.order_units, r.unit_cost_aed, r.total_cost_aed,
                       r.lead_time_days, r.required_by, r.expected_arrival, r.status,
                       r.justification, r.purchase_order_id
                  FROM flywheel_procurement_requisitions r
                  JOIN stores s ON s.id = r.store_id
                  JOIN items i ON i.id = r.item_id
                  LEFT JOIN suppliers sup ON sup.id = r.supplier_id
                 WHERE r.tenant_id = :t AND r.campaign_id = :c
                 ORDER BY r.total_cost_aed DESC"""),
        {"t": _tenant(user), "c": campaign_id},
    )).fetchall()

    return {"requisitions": [{
        "id": int(r[0]), "store_id": int(r[1]), "store_name": r[2],
        "item_id": int(r[3]), "item_name": r[4], "supplier": r[5],
        "shortage_units": int(r[6]), "order_units": int(r[7]),
        "unit_cost_aed": str(money(r[8])), "total_cost_aed": str(money(r[9])),
        "lead_time_days": int(r[10]), "required_by": str(r[11]),
        "expected_arrival": str(r[12]) if r[12] else None,
        "status": r[13], "justification": r[14] or {},
        "purchase_order_id": r[15],
    } for r in rows]}


@router.post("/requisitions/{requisition_id}/convert",
             summary="Convert an approved requisition into a draft PO")
async def convert_requisition(
    requisition_id: int,
    user: dict = Depends(require_permission("can_manage_inventory")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await procurement.convert_to_purchase_order(
            db, tenant_id=_tenant(user), requisition_id=requisition_id,
            actor_user_id=user.get("id"))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/budget", summary="CFO view — allocated / reserved / committed / spent")
async def budget_overview(
    user: dict = Depends(require_permission("can_view_financials")),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    rows = (await db.execute(
        text("""SELECT id, budget_type FROM flywheel_budgets
                 WHERE tenant_id = :t AND period_end > CURRENT_DATE
                 ORDER BY budget_type"""),
        {"t": tenant_id},
    )).fetchall()

    budgets = []
    for budget_id, _kind in rows:
        budgets.append(await budget_service.snapshot(
            db, tenant_id=tenant_id, budget_id=int(budget_id)))

    ledger = (await db.execute(
        text("""SELECT l.entry_type, l.amount_aed, l.source_type, l.created_at,
                       l.balance_before, l.balance_after, l.reason, c.name, u.email
                  FROM flywheel_budget_ledger l
                  LEFT JOIN flywheel_campaigns c ON c.id = l.campaign_id
                  LEFT JOIN users u ON u.id = l.actor_user_id
                 WHERE l.tenant_id = :t
                 ORDER BY l.created_at DESC LIMIT 60"""),
        {"t": tenant_id},
    )).fetchall()

    # Cash requirement by expected arrival — the CFO's "when do I need money".
    cash = (await db.execute(
        text("""SELECT expected_arrival, COALESCE(SUM(total_cost_aed), 0)
                  FROM flywheel_procurement_requisitions
                 WHERE tenant_id = :t AND status IN ('approved', 'converted_to_po')
                   AND expected_arrival IS NOT NULL
                 GROUP BY expected_arrival ORDER BY expected_arrival"""),
        {"t": tenant_id},
    )).fetchall()

    return {
        "budgets": budgets,
        "ledger": [{
            "entry_type": l[0], "amount_aed": str(money(l[1])), "source_type": l[2],
            "at": l[3].isoformat(), "balance_before": str(money(l[4])),
            "balance_after": str(money(l[5])), "reason": l[6],
            "campaign": l[7], "actor": l[8],
        } for l in ledger],
        "cash_requirement_by_date": [
            {"date": str(c[0]), "amount_aed": str(money(c[1]))} for c in cash],
    }


@router.get("/approvals", summary="Approval inbox")
async def approval_inbox(
    status: str = Query("pending"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"requests": await approvals.list_inbox(
        db, tenant_id=_tenant(user), user=user, status=status)}


@router.get("/approvals/{request_id}", summary="Approval request detail")
async def approval_detail(
    request_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detail = await approvals.request_detail(
        db, tenant_id=_tenant(user), request_id=request_id)
    if not detail:
        raise HTTPException(404, "Approval request not found")
    for step in detail["steps"]:
        step["can_decide"] = approvals.can_decide(user, step)
    return detail


@router.post("/approvals/steps/{step_id}/decide", summary="Approve / reject a step")
async def decide_approval(
    step_id: int, body: ApprovalDecision, request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await approvals.decide_step(
            db, tenant_id=_tenant(user), step_id=step_id, user=user,
            decision=body.decision, comment=body.comment)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if result.get("applied"):
        await outbox.emit(
            db, tenant_id=_tenant(user), channel=outbox.CHANNEL_APPROVAL,
            event_type="approval.decided",
            payload={"step_id": step_id, "decision": body.decision,
                     "request_status": result.get("request_status")},
            campaign_id=result.get("campaign_id"))

        # A fully approved campaign advances to APPROVED so it becomes activatable.
        if result.get("fully_approved") and result.get("campaign_id"):
            try:
                await campaign_state.transition(
                    db, tenant_id=_tenant(user), campaign_id=int(result["campaign_id"]),
                    target=CampaignStatus.APPROVED, actor_user_id=user.get("id"),
                    reason="All approval steps approved")
            except TransitionError:
                pass  # already past APPROVED — not an error
    return result


# ---------------------------------------------------------------------------
# Stage 5 — real-time decisioning & redemption
# ---------------------------------------------------------------------------

@router.post("/decisioning/evaluate", summary="Real-time next-best action")
async def evaluate(
    body: EvaluateRequest, request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns an action + offer, or a safe NO_ACTION with reason codes.
    Never raises on a policy refusal — a refusal is a valid answer."""
    return await decisioning.evaluate(
        db, tenant_id=_tenant(user), customer_id=body.customer_id,
        store_id=body.store_id, channel=body.channel, cart_items=body.cart_items,
        campaign_id=body.campaign_id, request_id=_request_id(request),
        issue_offer=body.issue_offer,
        accessible_store_ids=get_accessible_store_ids(user) or None)


@router.post("/decisioning/redeem", summary="Redeem an offer (idempotent, atomic)")
async def redeem(
    body: RedeemRequest, request: Request,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """One transaction: stock down, reserved budget → spent, redemption recorded,
    outbox event queued. A repeat with the same idempotency key returns the
    original result and changes nothing."""
    tenant_id = _tenant(user)
    try:
        result = await decisioning.redeem(
            db, tenant_id=tenant_id, offer_code=body.offer_code, units=body.units,
            idempotency_key=body.idempotency_key, store_id=body.store_id,
            actor_user_id=user.get("id"), request_id=_request_id(request))
    except InsufficientBudget as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    # Guardrails run immediately after the money moves — a breach must stop the
    # NEXT offer, not wait for a nightly sweep.
    if result.get("applied") and result.get("campaign_id"):
        try:
            check = await guardrails.check_campaign(
                db, tenant_id=tenant_id, campaign_id=int(result["campaign_id"]))
            result["guardrails"] = {"auto_paused": check.get("auto_paused"),
                                    "breaches": check.get("breaches", [])}
        except Exception as exc:
            logger.warning("flywheel.guardrail post-redemption check failed: %s", exc)
    return result


class ReturnRequest(BaseModel):
    redemption_id: int
    units_returned: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=8, max_length=120)
    reason: Optional[str] = None
    restock: bool = True


@router.post("/returns", summary="Process a return — claws back discount and margin")
async def process_return(
    body: ReturnRequest, request: Request,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Reverses a redemption with COMPENSATING ledger entries — the original
    rows are never edited. Idempotent on the key: a retried return cannot claw
    back twice. Partial returns are pro-rata."""
    try:
        return await liability.process_return(
            db, tenant_id=_tenant(user), redemption_id=body.redemption_id,
            units_returned=body.units_returned, idempotency_key=body.idempotency_key,
            reason=body.reason, restock=body.restock,
            actor_user_id=user.get("id"), request_id=_request_id(request))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/offers/expire", summary="Expire lapsed offers and record breakage")
async def expire_offers(
    campaign_id: Optional[int] = Query(None),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Releases the reservation AND records breakage as a separate memo entry,
    so the same money is never counted as both returned headroom and a saving."""
    return await liability.expire_and_record_breakage(
        db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.get("/campaigns/{campaign_id}/liability", summary="CFO exposure view")
async def campaign_liability(
    campaign_id: int,
    user: dict = Depends(require_permission("can_view_financials")),
    db: AsyncSession = Depends(get_db),
):
    """Outstanding liability, breakage, breakage rate and claw-backs — what the
    business is still on the hook for, separate from what it has spent."""
    return await liability.campaign_liability(
        db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.get("/customers/{customer_id}/contact-status",
            summary="Global contact status across ALL campaigns")
async def customer_contact_status(
    customer_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await contact_governance.contact_status(
        db, tenant_id=_tenant(user), customer_id=customer_id)


@router.get("/customers/{customer_id}/may-contact",
            summary="Would a contact be permitted right now, and if not why")
async def may_contact(
    customer_id: int, channel: str = Query("email"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    decision = await contact_governance.may_contact(
        db, tenant_id=_tenant(user), customer_id=customer_id, channel=channel)
    return decision.as_dict()


@router.get("/suppressions", summary="Campaigns suppressed by offer-conflict rules")
async def list_suppressions(
    campaign_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Why a marketer's campaign stopped reaching people. Silent suppression is
    how a decisioning system loses their trust."""
    clause = "AND s.suppressed_campaign_id = :c" if campaign_id else ""
    params: Dict[str, Any] = {"t": _tenant(user), "lim": limit}
    if campaign_id:
        params["c"] = campaign_id
    rows = (await db.execute(
        text(f"""SELECT s.customer_id, s.suppressed_campaign_id, sc.name,
                        s.winning_campaign_id, wc.name, s.reason_code, s.detail,
                        s.created_at
                   FROM flywheel_offer_suppressions s
                   LEFT JOIN flywheel_campaigns sc ON sc.id = s.suppressed_campaign_id
                   LEFT JOIN flywheel_campaigns wc ON wc.id = s.winning_campaign_id
                  WHERE s.tenant_id = :t {clause}
                  ORDER BY s.created_at DESC LIMIT :lim"""),
        params,
    )).fetchall()
    return {"suppressions": [{
        "customer_id": int(r[0]), "suppressed_campaign_id": int(r[1]),
        "suppressed_campaign": r[2], "winning_campaign_id": r[3],
        "winning_campaign": r[4], "reason_code": r[5], "detail": r[6],
        "at": r[7].isoformat() if r[7] else None,
    } for r in rows]}


@router.get("/decisions/{decision_id}", summary="Decision trace (full explainability)")
async def decision_trace(
    decision_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything that produced this decision, plus a REPLAY that recomputes EIV
    from the stored terms — proving the decision is reproducible."""
    row = (await db.execute(
        text("""SELECT d.id, d.campaign_id, d.customer_id, d.store_id, d.item_id,
                       d.category, d.action_type, d.churn_probability, d.uplift,
                       d.redemption_probability, d.unit_price_aed, d.unit_cost_aed,
                       d.discount_pct, d.expected_retained_value_aed, d.expected_margin_aed,
                       d.expected_discount_cost_aed, d.comms_cost_aed, d.fulfilment_cost_aed,
                       d.procurement_cost_aed, d.stockout_risk_penalty_aed, d.eiv_aed,
                       d.reason_codes, d.rejected_actions, d.inventory_snapshot,
                       d.budget_snapshot, d.policy_version, d.decided_at,
                       m.version_label, m.algorithm, c.display_name, s.name, i.name
                  FROM flywheel_decisions d
                  LEFT JOIN flywheel_model_versions m ON m.id = d.churn_model_version_id
                  LEFT JOIN flywheel_customers c ON c.id = d.customer_id
                  LEFT JOIN stores s ON s.id = d.store_id
                  LEFT JOIN items i ON i.id = d.item_id
                 WHERE d.id = :d AND d.tenant_id = :t"""),
        {"d": decision_id, "t": _tenant(user)},
    )).fetchone()
    if not row:
        raise HTTPException(404, "Decision not found")

    stored = {
        "expected_retained_value_aed": row[13], "expected_margin_aed": row[14],
        "expected_discount_cost_aed": row[15], "comms_cost_aed": row[16],
        "fulfilment_cost_aed": row[17], "procurement_cost_aed": row[18],
        "stockout_risk_penalty_aed": row[19], "eiv_aed": row[20],
        "policy_version": row[25],
    }

    return {
        "decision": {
            "id": int(row[0]), "campaign_id": row[1], "customer_id": int(row[2]),
            "customer_name": row[29], "store_id": row[3], "store_name": row[30],
            "item_id": row[4], "item_name": row[31], "category": row[5],
            "action_type": row[6], "decided_at": row[26].isoformat(),
        },
        "model_inputs": {
            "churn_probability": float(row[7]), "uplift": float(row[8]),
            "redemption_probability": float(row[9]),
            "churn_model": row[27], "algorithm": row[28],
        },
        "price_snapshot": {
            "unit_price_aed": str(money(row[10])), "unit_cost_aed": str(money(row[11])),
            "discount_pct": str(row[12]),
            "note": "Price and cost as at the decision. History stays explainable "
                    "after prices change.",
        },
        "eiv_breakdown": {
            "expected_retained_value_aed": str(money(row[13])),
            "expected_margin_aed": str(money(row[14])),
            "less_discount_cost_aed": str(money(row[15])),
            "less_comms_cost_aed": str(money(row[16])),
            "less_fulfilment_cost_aed": str(money(row[17])),
            "less_procurement_cost_aed": str(money(row[18])),
            "less_stockout_penalty_aed": str(money(row[19])),
            "eiv_aed": str(money(row[20])),
        },
        "reason_codes": row[21] or [],
        "rejected_actions": row[22] or [],
        "inventory_snapshot": row[23] or {},
        "budget_snapshot": row[24] or {},
        "policy_version": row[25],
        "reproducibility": optimizer.replay(stored),
    }


# ---------------------------------------------------------------------------
# Stage 5–6 — live control centre, guardrails, measurement
# ---------------------------------------------------------------------------

@router.get("/campaigns/{campaign_id}/live", summary="Live control centre")
async def live_metrics(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    header = (await db.execute(
        text("""SELECT status, pause_reason, discount_budget_aed, starts_on, ends_on
                  FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not header:
        raise HTTPException(404, "Campaign not found")

    offers = (await db.execute(
        text("""SELECT status, COUNT(*) FROM flywheel_offers
                 WHERE tenant_id = :t AND campaign_id = :c GROUP BY status"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()

    redemption = (await db.execute(
        text("""SELECT COUNT(*), COALESCE(SUM(units), 0),
                       COALESCE(SUM(discount_aed), 0), COALESCE(SUM(net_value_aed), 0),
                       COALESCE(SUM(margin_aed), 0)
                  FROM flywheel_redemptions WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()

    audience = (await db.execute(
        text("""SELECT assignment, COUNT(*) FROM flywheel_campaign_audience
                 WHERE campaign_id = :c AND tenant_id = :t GROUP BY assignment"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchall()

    exposure = await budget_service.campaign_exposure(
        db, tenant_id=tenant_id, campaign_id=campaign_id)
    check = await guardrails.check_campaign(
        db, tenant_id=tenant_id, campaign_id=campaign_id, auto_pause=False)

    reserved = money(exposure["reserved_aed"])
    spent = money(exposure["spent_aed"])

    return {
        "campaign_id": campaign_id, "status": header[0], "pause_reason": header[1],
        "period": {"from": str(header[3]), "to": str(header[4])},
        "audience": {a[0]: int(a[1]) for a in audience},
        "offers": {o[0]: int(o[1]) for o in offers},
        "redemptions": {
            "count": int(redemption[0]), "units": int(redemption[1]),
            "discount_aed": str(money(redemption[2])),
            "net_value_aed": str(money(redemption[3])),
            "margin_aed": str(money(redemption[4])),
        },
        "budget": {
            **exposure,
            "burn_pct": round(float(spent / reserved * 100), 1) if reserved > 0 else 0.0,
        },
        "guardrails": {"breaches": check.get("breaches", []),
                       "hard_breaches": check.get("hard_breaches", 0)},
    }


@router.post("/campaigns/{campaign_id}/measure", summary="Measure treatment vs control")
async def measure_campaign(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await measurement.measure(
            db, tenant_id=_tenant(user), campaign_id=campaign_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/campaigns/{campaign_id}/outcome", summary="Latest persisted outcome")
async def campaign_outcome(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    outcome = await measurement.latest_outcome(
        db, tenant_id=_tenant(user), campaign_id=campaign_id)
    if not outcome:
        raise HTTPException(404, "Campaign has not been measured yet")
    return outcome


@router.get("/health", summary="Flywheel subsystem health")
async def flywheel_health(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    pending = await outbox.pending_count(db, tenant_id)
    counts = (await db.execute(
        text("""SELECT
                  (SELECT COUNT(*) FROM flywheel_customers WHERE tenant_id = :t),
                  (SELECT COUNT(*) FROM flywheel_campaigns WHERE tenant_id = :t),
                  (SELECT COUNT(*) FROM flywheel_decisions WHERE tenant_id = :t),
                  (SELECT COUNT(*) FROM flywheel_redemptions WHERE tenant_id = :t),
                  (SELECT MAX(as_of_date) FROM flywheel_feature_snapshots WHERE tenant_id = :t)"""),
        {"t": tenant_id},
    )).fetchone()

    return {
        "customers": int(counts[0]), "campaigns": int(counts[1]),
        "decisions": int(counts[2]), "redemptions": int(counts[3]),
        "latest_feature_snapshot": str(counts[4]) if counts[4] else None,
        "outbox_pending": pending,
        # A climbing outbox backlog means live dashboards are stale — surface it
        # rather than let the UI quietly show old numbers.
        "outbox_healthy": pending < 500,
        "synthetic": True,
    }


# ===========================================================================
# HORIZON 1 — proving it.
#
# Everything below serves the four surfaces added in Horizon 1: Incrementality,
# Holdout, Contact Governance and Shadow Mode. See
# docs/MASTER_IMPLEMENTATION_PLAN_C_LEVEL.md Addendum A.
# ===========================================================================

class PreregistrationIn(BaseModel):
    """What we commit to measuring, BEFORE the campaign runs."""
    primary_metric: str = Field("incremental_retention")
    window_days: int = Field(60, ge=1, le=365)
    alpha: float = Field(0.05, gt=0, lt=0.5)
    min_detectable_effect: float = Field(0.02, ge=0, le=1)
    planned_treatment_n: int = Field(0, ge=0)
    planned_control_n: int = Field(0, ge=0)
    control_pct: Decimal = Field(Decimal("10.00"), ge=0, le=50)
    notes: Optional[str] = None


@router.get("/incrementality", summary="Tenant-wide incrementality roll-up")
async def incrementality_summary(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The headline: incremental margin per AED spent, proven against control."""
    return await readout.portfolio_summary(db, tenant_id=_tenant(user))


@router.get("/campaigns/{campaign_id}/readout", summary="Latest incrementality readout")
async def campaign_readout(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    latest = await readout.latest(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if not latest:
        # NOT a 404. A campaign with no readout yet is a normal, expected state
        # early in its life; returning an error would make the UI render a
        # failure where the honest answer is "not yet".
        return {"campaign_id": campaign_id, "state": "not_yet_measured",
                "readout": None,
                "note": "No readout computed yet. The scheduler measures hourly."}

    prereg = await readout.get_preregistration(
        db, tenant_id=tenant_id, campaign_id=campaign_id)
    mde = float(prereg["min_detectable_effect"]) if prereg else 0.0
    cs = sequential.difference_of_proportions(
        treatment_converted=latest["treatment_converted"],
        treatment_n=latest["treatment_n"],
        control_converted=latest["control_converted"],
        control_n=latest["control_n"],
        alpha=float(prereg["alpha"]) if prereg else sequential.DEFAULT_ALPHA,
    )
    return {
        "campaign_id": campaign_id, "state": "measured", "readout": latest,
        "interpretation": sequential.interpret(cs, min_detectable_effect=mde),
        "preregistration": prereg,
    }


@router.get("/campaigns/{campaign_id}/readout/history",
            summary="Readout time series — how evidence accumulated")
async def campaign_readout_history(
    campaign_id: int,
    limit: int = Query(90, ge=1, le=365),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        "campaign_id": campaign_id,
        "series": await readout.history(
            db, tenant_id=_tenant(user), campaign_id=campaign_id, limit=limit),
        "note": ("The interval is anytime-valid: it is correct however often it "
                 "was checked. Watching it narrow is the intended use."),
    }


@router.post("/campaigns/{campaign_id}/readout/recompute",
             summary="Recompute this campaign's readout now")
async def campaign_readout_recompute(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await readout.compute_and_store(
        db, tenant_id=_tenant(user), campaign_id=campaign_id, computed_by="api")


@router.get("/campaigns/{campaign_id}/preregistration",
            summary="What this campaign committed to measuring")
async def campaign_preregistration(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prereg = await readout.get_preregistration(
        db, tenant_id=_tenant(user), campaign_id=campaign_id)
    if not prereg:
        return {"campaign_id": campaign_id, "preregistered": False,
                "warning": ("This campaign was NOT pre-registered. Its results can "
                            "still be read, but the metric and stopping rule were "
                            "not fixed in advance, so they carry less weight.")}
    return {"campaign_id": campaign_id, "preregistered": True, **prereg}


@router.post("/campaigns/{campaign_id}/preregistration",
             summary="Pre-register the measurement plan")
async def create_preregistration(
    campaign_id: int,
    payload: PreregistrationIn,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await readout.preregister(
            db, tenant_id=_tenant(user), campaign_id=campaign_id,
            primary_metric=payload.primary_metric, window_days=payload.window_days,
            alpha=payload.alpha, min_detectable_effect=payload.min_detectable_effect,
            planned_treatment_n=payload.planned_treatment_n,
            planned_control_n=payload.planned_control_n,
            control_pct=payload.control_pct,
            registered_by=user.get("id"), notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/campaigns/{campaign_id}/holdout",
            summary="Holdout health and covariate balance")
async def campaign_holdout(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    balance = await readout.check_balance(
        db, tenant_id=tenant_id, campaign_id=campaign_id, persist=False)

    arms = (await db.execute(
        text("""SELECT assignment, COUNT(*)
                  FROM flywheel_campaign_audience
                 WHERE tenant_id = :t AND campaign_id = :c
                 GROUP BY assignment"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()
    sizes = {row[0]: int(row[1]) for row in arms}

    return {
        "campaign_id": campaign_id,
        "arms": {"treatment": sizes.get("treatment", 0),
                 "control": sizes.get("control", 0)},
        "balance": balance,
        "assignment_method": (
            "BLAKE2b stable hash of (tenant, campaign, customer). Stable across "
            "processes and releases, so a restart can never reassign anyone — "
            "Python's built-in hash() is salted per process and would silently "
            "destroy the experiment."),
    }


@router.get("/holdout", summary="Holdout health across all campaigns")
async def holdout_overview(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    rows = (await db.execute(
        text("""SELECT c.id, c.name, c.status,
                       COUNT(*) FILTER (WHERE a.assignment = 'treatment'),
                       COUNT(*) FILTER (WHERE a.assignment = 'control')
                  FROM flywheel_campaigns c
                  LEFT JOIN flywheel_campaign_audience a
                    ON a.campaign_id = c.id AND a.tenant_id = c.tenant_id
                 WHERE c.tenant_id = :t
                 GROUP BY c.id, c.name, c.status
                 ORDER BY c.id DESC"""),
        {"t": tenant_id},
    )).fetchall()

    campaigns = []
    for r in rows:
        treatment, control = int(r[3]), int(r[4])
        campaigns.append({
            "campaign_id": int(r[0]), "name": r[1], "status": r[2],
            "treatment_n": treatment, "control_n": control,
            "control_share": (round(control / (treatment + control), 4)
                              if (treatment + control) else 0.0),
            "adequate": control >= 30,
        })
    return {"campaigns": campaigns,
            "note": ("Control groups below 30 are flagged: they can still be "
                     "read, but the estimate is directional only.")}


@router.get("/governance", summary="Contact governance — caps, suppressions, fatigue")
async def governance_overview(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Surface the restraint the system is exercising.

    The suppressed count is a FEATURE, not a loss: it is the system declining to
    over-contact people. Presenting it as a failure metric would train operators
    to disable the protection.
    """
    tenant_id = _tenant(user)
    return await contact_governance.overview(db, tenant_id=tenant_id)


@router.get("/models/shadow", summary="Rule tier vs shadow models")
async def shadow_overview(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    return {
        "comparison": await shadow.comparison(db, tenant_id=tenant_id),
        "promotion": await shadow.promotion_standing(db, tenant_id=tenant_id),
        "governing_rule": (
            "The deterministic rule tier is the production decision path. Models "
            "run in shadow and are promoted only when a pre-registered holdout "
            "beats rules with a confidence interval excluding zero. This is a "
            "governance control, not a limitation: model ranking is currently "
            "unstable at this data volume (three training runs produced three "
            "different winners; Qini ranged +1.13 to -3.80 at n=300)."),
    }


@router.get("/campaigns/{campaign_id}/allocation",
            summary="Portfolio allocation vs per-customer greedy")
async def campaign_allocation(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    rows = (await db.execute(
        text("""SELECT id, mode, is_shadow, budget_limit_aed, customers_considered,
                       candidates_considered, actions_selected, total_eiv_aed,
                       total_cost_aed, binding_constraint, eiv_delta_vs_greedy_aed,
                       solver, runtime_ms, created_at
                  FROM flywheel_allocation_runs
                 WHERE tenant_id = :t AND campaign_id = :c
                 ORDER BY created_at DESC LIMIT 20"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()

    return {
        "campaign_id": campaign_id,
        "runs": [{
            "id": int(r[0]), "mode": r[1], "is_shadow": bool(r[2]),
            "budget_limit_aed": str(money(r[3])),
            "customers_considered": int(r[4]), "candidates_considered": int(r[5]),
            "actions_selected": int(r[6]), "total_eiv_aed": str(money(r[7])),
            "total_cost_aed": str(money(r[8])), "binding_constraint": r[9],
            "eiv_delta_vs_greedy_aed": str(money(r[10])) if r[10] is not None else None,
            "solver": r[11], "runtime_ms": int(r[12]) if r[12] is not None else None,
            "created_at": r[13].isoformat() if r[13] else None,
        } for r in rows],
        "note": ("Positive eiv_delta_vs_greedy_aed is margin the per-customer "
                 "path left on the table. Zero is CORRECT when no constraint "
                 "binds — the allocator must not differ in the easy case."),
    }


@router.post("/models/shadow/score", summary="Run a shadow scoring pass")
async def shadow_score(
    campaign_id: Optional[int] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Score every customer through BOTH paths and record the disagreements.

    Touches no money, no stock and no customer — it records an opinion.
    """
    return await shadow.score_pass(
        db, tenant_id=_tenant(user), campaign_id=campaign_id, limit=limit)


# ===========================================================================
# HORIZON 2 — operability: durable jobs, model registry, tracing.
# ===========================================================================

class EnqueueJobIn(BaseModel):
    kind: str = Field(..., pattern="^(score_audience|measure_all|shadow_score)$")
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.post("/jobs", summary="Enqueue a durable background job")
async def enqueue_job(
    body: EnqueueJobIn,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch long-running work to the durable queue.

    The job survives a worker crash: it is claimed under a lease and checkpoints
    its progress, so a redeploy mid-run resumes from the last completed batch
    rather than restarting. Idempotent per (tenant, kind) per calendar day, so a
    double-submit watches the same job instead of creating a second.
    """
    tenant_id = _tenant(user)
    # A per-day idempotency key: the same logical job (today's scoring) enqueued
    # twice returns the first. trace_id ties any decisions this job produces back
    # to the dispatch, so the whole chain is one lookup.
    day = date.today().isoformat()
    trace_id = trace.ensure_trace_id()
    job_id = await jobs.enqueue(
        db, tenant_id=tenant_id, kind=body.kind, payload=body.payload,
        idempotency_key=f"{body.kind}:{tenant_id}:{day}", trace_id=trace_id)
    return {"job_id": job_id, "kind": body.kind, "trace_id": trace_id,
            "note": ("Watch GET /jobs/{job_id}. Idempotent for today — the same "
                     "kind submitted again returns this same job.")}


@router.get("/jobs", summary="Job queue health")
async def job_queue_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stats = await jobs.queue_stats(db, tenant_id=_tenant(user))
    stats["note"] = ("dead_letter counts jobs that exhausted their retries. They "
                     "are retained, not deleted, so they can be inspected and "
                     "requeued rather than silently lost.")
    return stats


@router.get("/jobs/{job_id}", summary="Inspect one job")
async def job_detail(
    job_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await jobs.get_job(db, tenant_id=_tenant(user), job_id=job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/models/registry", summary="Model registry with data-snapshot lineage")
async def model_registry(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await registry.list_versions(db, tenant_id=_tenant(user))


@router.get("/decisions/{decision_id}/trace", summary="Full lifecycle trace of a decision")
async def decision_trace_timeline(
    decision_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The whole life of a decision, in one place.

    A PDPL obligation as much as an operational one: a data subject may demand an
    explanation of an automated decision, and this is that explanation — inputs,
    the action chosen, and everything that happened to it afterwards.
    """
    result = await trace.decision_timeline(
        db, tenant_id=_tenant(user), decision_id=decision_id)
    if not result:
        raise HTTPException(404, "Decision not found")
    return result


# ===========================================================================
# HORIZON 3 — two tracks over one engine.
#
# Track A (retention) reuses the retailer-funded path already in place. Track B
# (supplier-funded trade promotion) is new: funding, settlement, cannibalization,
# and a supplier-scoped view. Shared: metering, PDPL objections, identity.
# ===========================================================================

class FundingIn(BaseModel):
    supplier_id: int
    funding_type: str = Field(..., pattern="^(co_op|scan_down|fixed_fee)$")
    committed_aed: Decimal
    item_ids: List[int] = Field(..., min_length=1)
    rebate_per_unit_aed: Decimal = Decimal("0")
    agreement_ref: Optional[str] = None


class SettlementIn(BaseModel):
    period_start: date
    period_end: date


class ObjectionIn(BaseModel):
    customer_id: int
    note: Optional[str] = None


@router.post("/campaigns/{campaign_id}/funding", summary="Propose supplier funding (Track B)")
async def create_funding(
    campaign_id: int, body: FundingIn,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await trade.propose_funding(
            db, tenant_id=_tenant(user), supplier_id=body.supplier_id,
            campaign_id=campaign_id, funding_type=body.funding_type,
            committed_aed=body.committed_aed, item_ids=body.item_ids,
            rebate_per_unit_aed=body.rebate_per_unit_aed,
            agreement_ref=body.agreement_ref, created_by=user.get("id"))
    except trade.TradeError as exc:
        raise HTTPException(422, str(exc))


@router.post("/funding/{funding_id}/transition", summary="Advance a funding's lifecycle")
async def funding_transition(
    funding_id: int, target: str = Query(..., pattern="^(committed|active|settled|disputed|cancelled)$"),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await trade.transition_funding(db, tenant_id=_tenant(user),
                                              funding_id=funding_id, target=target)
    except trade.TradeError as exc:
        raise HTTPException(422, str(exc))


@router.post("/funding/{funding_id}/settle", summary="Issue an audit-defensible settlement")
async def issue_funding_settlement(
    funding_id: int, body: SettlementIn,
    user: dict = Depends(require_permission("can_view_financials")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await trade.issue_settlement(
            db, tenant_id=_tenant(user), funding_id=funding_id,
            period_start=body.period_start, period_end=body.period_end)
    except trade.TradeError as exc:
        raise HTTPException(422, str(exc))


@router.get("/suppliers/{supplier_id}/dashboard", summary="Supplier-scoped trade view (Track B)")
async def supplier_trade_dashboard(
    supplier_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything a supplier is entitled to see — and nothing they are not.
    Every figure is intersected with the supplier's funded-SKU scope."""
    return await trade.supplier_dashboard(db, tenant_id=_tenant(user), supplier_id=supplier_id)


@router.get("/trade", summary="Trade-promotion overview across suppliers")
async def trade_overview(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant(user)
    rows = (await db.execute(
        text("""SELECT f.id, f.supplier_id, sup.name, f.campaign_id, c.name,
                       f.funding_type, f.status, f.committed_aed, f.spent_aed, f.settled_aed
                  FROM flywheel_supplier_funding f
                  JOIN suppliers sup ON sup.id = f.supplier_id AND sup.tenant_id = f.tenant_id
                  JOIN flywheel_campaigns c ON c.id = f.campaign_id AND c.tenant_id = f.tenant_id
                 WHERE f.tenant_id = :t
                 ORDER BY f.created_at DESC"""),
        {"t": tenant_id},
    )).fetchall()
    return {
        "fundings": [{
            "funding_id": int(r[0]), "supplier_id": int(r[1]), "supplier_name": r[2],
            "campaign_id": int(r[3]), "campaign_name": r[4], "funding_type": r[5],
            "status": r[6], "committed_aed": str(money(r[7])),
            "spent_aed": str(money(r[8])), "settled_aed": str(money(r[9])),
        } for r in rows],
        "note": ("Supplier-funded trade promotion. Each funding is settled on "
                 "measured, cannibalization-adjusted incremental performance — a "
                 "supplier pays only for demand the promotion genuinely created."),
    }


@router.get("/campaigns/{campaign_id}/cannibalization", summary="Cannibalization (Track B)")
async def campaign_cannibalization(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await cannibalization.latest(db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.post("/campaigns/{campaign_id}/cannibalization/recompute",
             summary="Recompute cannibalization now")
async def recompute_cannibalization(
    campaign_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await cannibalization.estimate(db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.get("/metering", summary="Flywheel metered usage + hybrid pricing")
async def metering_summary(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await metering.summary(db, tenant_id=_tenant(user))


@router.get("/objections", summary="PDPL profiling objections")
async def list_profiling_objections(
    active_only: bool = Query(True),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await objections.list_objections(db, tenant_id=_tenant(user), active_only=active_only)


@router.post("/objections", summary="Record a PDPL objection to automated profiling")
async def create_objection(
    body: ObjectionIn,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await objections.record_objection(
        db, tenant_id=_tenant(user), customer_id=body.customer_id, note=body.note)


@router.delete("/objections/{customer_id}", summary="Withdraw a PDPL objection")
async def withdraw_profiling_objection(
    customer_id: int,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await objections.withdraw_objection(db, tenant_id=_tenant(user), customer_id=customer_id)


@router.get("/identity/stats", summary="POS→loyalty identity resolution stats")
async def identity_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await identity.resolution_stats(db, tenant_id=_tenant(user))


@router.post("/identity/resolve", summary="Resolve pending POS transactions")
async def resolve_identities(
    batch: int = Query(500, ge=1, le=5000),
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await identity.resolve_pending(db, tenant_id=_tenant(user), batch=batch)


# ===========================================================================
# HORIZON 4 — expand: seasonality, coalition, shelf-life, gated outcome pricing.
# ===========================================================================

class PartnerIn(BaseModel):
    partner_name: str = Field(..., min_length=2, max_length=120)
    partner_type: str = Field(..., pattern="^(grocery|fuel|hospitality|travel|retail|dining|other)$")
    external_ref: Optional[str] = None


class OutcomePlanIn(BaseModel):
    plan_name: str = Field(..., min_length=2, max_length=80)
    margin_share_pct: Decimal = Field(..., gt=0, le=Decimal("0.5"))
    gate_readouts_required: int = Field(2, ge=1)


@router.get("/seasonality", summary="Seasonality calendar + current demand factor")
async def seasonality_calendar(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The demand-multiplier calendar (Ramadan, Eid, summer lull, …) that scales
    a customer's forward value in the EIV calculation."""
    return await seasonality.calendar(db, tenant_id=_tenant(user))


@router.get("/shelf-life", summary="Near-expiry stock + markdown recommendations")
async def shelf_life_candidates(
    store_id: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Perishables near expiry, ranked by value at risk, with a recommended
    markdown — for a grocer, clearing this can outrank a retention offer."""
    return await shelf_life.markdown_candidates(db, tenant_id=_tenant(user), store_id=store_id)


@router.get("/coalition/partners", summary="Coalition partners")
async def coalition_partners(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"partners": await coalition.partners(db, tenant_id=_tenant(user))}


@router.post("/coalition/partners", summary="Register a coalition partner")
async def register_coalition_partner(
    body: PartnerIn,
    user: dict = Depends(require_permission("can_manage_promotions")),
    db: AsyncSession = Depends(get_db),
):
    return await coalition.register_partner(
        db, tenant_id=_tenant(user), partner_name=body.partner_name,
        partner_type=body.partner_type, external_ref=body.external_ref)


@router.get("/campaigns/{campaign_id}/coalition", summary="Coalition attribution for a campaign")
async def campaign_coalition_attribution(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """How a campaign's retained value split across coalition partners — table
    stakes in the GCC, where loyalty spans grocery, fuel, hospitality and travel."""
    return await coalition.campaign_attribution(db, tenant_id=_tenant(user), campaign_id=campaign_id)


@router.get("/outcome-pricing", summary="Outcome-based pricing plans + gate status")
async def outcome_pricing_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Outcome-based pricing charges a share of measured incremental margin — but
    only once the evidence gate (significant holdout readouts) is met."""
    return await outcome_pricing.status(db, tenant_id=_tenant(user))


@router.post("/outcome-pricing", summary="Propose an outcome-pricing plan (inert until gated)")
async def create_outcome_plan(
    body: OutcomePlanIn,
    user: dict = Depends(require_permission("can_view_financials")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await outcome_pricing.propose_plan(
            db, tenant_id=_tenant(user), plan_name=body.plan_name,
            margin_share_pct=body.margin_share_pct,
            gate_readouts_required=body.gate_readouts_required)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/outcome-pricing/{plan_id}/evaluate-gate", summary="Recompute the evidence gate")
async def evaluate_outcome_gate(
    plan_id: int,
    user: dict = Depends(require_permission("can_view_financials")),
    db: AsyncSession = Depends(get_db),
):
    """Recompute whether the plan has earned the right to charge — from the
    immutable holdout readouts. The gate is never set by hand."""
    try:
        return await outcome_pricing.evaluate_gate(db, tenant_id=_tenant(user), plan_id=plan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
