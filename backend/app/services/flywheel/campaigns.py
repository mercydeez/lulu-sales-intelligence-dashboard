"""Stages 3–5 orchestration — audience, simulation, submission, activation.

This module is the CONDUCTOR. It owns no rules of its own: audience selection
calls churn, simulation calls the optimizer and ATP, submission calls approvals,
activation calls budget and inventory. Keeping the orchestration separate from
the rules means each rule can be tested in isolation and the sequence can be
read in one place.

THE ONE INVARIANT IT ENFORCES ITSELF: nothing that costs money happens before
approval. Simulation is pure arithmetic over snapshots. Soft allocations and
budget reservations are placed at ACTIVATION, inside a single transaction with
the state transition, so a campaign can never be live-but-unfunded or
funded-but-not-live.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import (
    approvals, budget as budget_service, campaign_state, churn as churn_service,
    features as feature_service, inventory_atp, optimizer, outbox, procurement,
    uplift as uplift_service,
)
from app.services.flywheel.types import (
    ZERO, ActionType, BudgetType, CampaignStatus, PolicyEnvelope, money, money4,
    is_control, stable_hash,
)

logger = logging.getLogger(__name__)


async def build_audience(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    min_churn_probability: float = 0.25, max_size: int = 5000,
    accessible_store_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Select the eligible audience and fix the treatment/control split.

    ELIGIBILITY is deliberately narrow — consent, status, store scope and a churn
    floor. Targeting customers who cannot be contacted or are not at risk wastes
    the budget and pollutes the measurement.

    THE SPLIT IS COMPUTED ONCE AND PERSISTED. It uses `stable_hash`, so re-running
    this produces the identical split — but the persisted row is what
    `decisioning.evaluate` reads, so even changing `control_group_pct` later
    cannot silently move a customer between arms mid-flight.
    """
    campaign = (await db.execute(
        text("""SELECT status, control_group_pct, channel, audience_spec, starts_on
                  FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    status, control_pct, channel, audience_spec, starts_on = campaign
    spec = audience_spec if isinstance(audience_spec, dict) else json.loads(audience_spec or "{}")

    # Re-building replaces the previous audience wholesale — a partial refresh
    # would leave customers assigned by an older rule set.
    await db.execute(
        text("DELETE FROM flywheel_campaign_audience WHERE campaign_id = :c AND tenant_id = :t"),
        {"c": campaign_id, "t": tenant_id},
    )

    as_of = await feature_service.latest_snapshot_date(db, tenant_id) or date.today()

    store_filter = ""
    params: Dict[str, Any] = {
        "t": tenant_id, "as_of": as_of, "min_p": min_churn_probability,
        "ch": channel, "lim": max_size,
    }
    scope_stores = spec.get("store_ids") or accessible_store_ids
    if scope_stores:
        store_filter = "AND c.home_store_id = ANY(:stores)"
        params["stores"] = list(scope_stores)

    # ORDERING IS BY PERSUADABILITY, NOT BY RISK — and that distinction is the
    # whole product thesis, so getting it wrong here quietly defeats everything
    # downstream.
    #
    # Ordering by `churn_probability DESC` is the obvious choice and it is
    # wrong. A customer at 0.99 is a LOST CAUSE: the optimizer will (correctly)
    # refuse to spend on them, because expected value multiplies uplift and
    # uplift near the extremes is ~0. Measured on live data, 62% of an audience
    # built that way sat above 0.95 churn and received NO_ACTION. When the
    # audience is capped by `max_size`, risk-ordering therefore fills every slot
    # with customers the system will refuse, and drops the persuadable middle
    # that the campaign exists to reach.
    #
    # `p * (1 - p)` is the inverted-U from the uplift model, peaking at p = 0.5.
    # It ranks the movable middle first while the `min_churn_probability` floor
    # still excludes the genuinely healthy. Risk decides ELIGIBILITY;
    # persuadability decides PRIORITY.
    rows = (await db.execute(
        text(f"""SELECT c.id, p.churn_probability
                   FROM flywheel_customers c
                   JOIN flywheel_churn_predictions p
                     ON p.customer_id = c.id AND p.as_of_date = :as_of
                   LEFT JOIN flywheel_customer_consents cons
                     ON cons.customer_id = c.id AND cons.channel = :ch
                  WHERE c.tenant_id = :t
                    AND c.status IN ('active', 'dormant')
                    AND p.churn_probability >= :min_p
                    AND COALESCE(cons.granted, TRUE) = TRUE
                    {store_filter}
                  ORDER BY (p.churn_probability * (1 - p.churn_probability)) DESC,
                           p.churn_probability DESC
                  LIMIT :lim"""),
        params,
    )).fetchall()

    treatment = control = 0
    for customer_id, probability in rows:
        control_flag = is_control(tenant_id, campaign_id, int(customer_id),
                                  Decimal(str(control_pct)))
        assignment = "control" if control_flag else "treatment"
        await db.execute(
            text("""INSERT INTO flywheel_campaign_audience
                       (tenant_id, campaign_id, customer_id, assignment,
                        assignment_hash, churn_probability, eligibility_note)
                    VALUES (:t, :c, :cust, :a, :h, :p, :note)
                    ON CONFLICT (campaign_id, customer_id) DO NOTHING"""),
            {"t": tenant_id, "c": campaign_id, "cust": int(customer_id),
             "a": assignment, "h": stable_hash(tenant_id, campaign_id, int(customer_id)),
             "p": probability,
             "note": f"churn {float(probability):.2f} >= {min_churn_probability} floor"},
        )
        if control_flag:
            control += 1
        else:
            treatment += 1

    if treatment + control:
        await campaign_state.transition(
            db, tenant_id=tenant_id, campaign_id=campaign_id,
            target=CampaignStatus.AUDIENCE_READY, actor_kind="system",
            reason=f"Audience built: {treatment} treatment / {control} control")

    logger.info("flywheel.audience campaign=%s treatment=%s control=%s",
                campaign_id, treatment, control)
    return {
        "campaign_id": campaign_id, "total": treatment + control,
        "treatment": treatment, "control": control,
        "control_pct_actual": round(control / (treatment + control) * 100, 1)
                              if (treatment + control) else 0,
        "control_pct_target": float(control_pct),
        "as_of": str(as_of),
        "min_churn_probability": min_churn_probability,
    }


async def simulate(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    sample_size: int = 400, accessible_store_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Model the campaign end to end WITHOUT committing anything.

    Runs the real optimizer over a sample of the treatment arm, aggregates the
    financial and operational picture, and extrapolates to the full audience.

    SAMPLING IS EXPLICIT, NOT HIDDEN. Scoring 5,000 customers through the full
    candidate ladder is slow enough to time out a request; we score a sample and
    scale, and we REPORT the sample size and scale factor so nobody mistakes an
    extrapolation for a census.

    THREE SCENARIOS (§20.2) come from varying redemption against the model's
    central estimate: pessimistic 0.6×, expected 1.0×, optimistic 1.4×.
    """
    campaign = (await db.execute(
        text("""SELECT max_discount_pct, min_margin_pct, safety_stock_pct, channel,
                       policy_version, ends_on, discount_budget_aed
                  FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    (max_discount, min_margin, safety_pct, channel,
     policy_version, ends_on, declared_budget) = campaign

    envelope = PolicyEnvelope(
        max_discount_pct=Decimal(str(max_discount)),
        min_margin_pct=Decimal(str(min_margin)),
        safety_stock_pct=Decimal(str(safety_pct)),
        policy_version=policy_version,
    )

    audience_total = int((await db.execute(
        text("""SELECT COUNT(*) FROM flywheel_campaign_audience
                 WHERE campaign_id = :c AND tenant_id = :t AND assignment = 'treatment'"""),
        {"c": campaign_id, "t": tenant_id},
    )).scalar() or 0)

    if not audience_total:
        raise ValueError("Build the audience before simulating")

    as_of = await feature_service.latest_snapshot_date(db, tenant_id) or date.today()

    sample = (await db.execute(
        text(f"""SELECT a.customer_id, a.churn_probability, c.home_store_id,
                        {', '.join('f.' + n for n in feature_service.FEATURE_NAMES)}
                   FROM flywheel_campaign_audience a
                   JOIN flywheel_customers c ON c.id = a.customer_id
                   LEFT JOIN flywheel_feature_snapshots f
                     ON f.customer_id = a.customer_id AND f.as_of_date = :as_of
                  WHERE a.campaign_id = :camp AND a.tenant_id = :t
                    AND a.assignment = 'treatment'
                  ORDER BY a.churn_probability DESC
                  LIMIT :lim"""),
        {"camp": campaign_id, "t": tenant_id, "as_of": as_of, "lim": sample_size},
    )).fetchall()

    scale = audience_total / len(sample) if sample else 1.0

    totals = {
        "discount_cost": ZERO, "margin": ZERO, "retained_value": ZERO,
        "comms": ZERO, "fulfilment": ZERO, "eiv": ZERO,
    }
    action_mix: Dict[str, int] = {}
    expected_redemptions = 0.0
    stock_demand: Dict[tuple, int] = {}
    price_cache: Dict[int, tuple] = {}

    from app.services.flywheel.decisioning import _unit_cost

    for row in sample:
        customer_id, churn_probability, home_store = int(row[0]), float(row[1]), int(row[2])
        feats = {name: row[i + 3] for i, name in enumerate(feature_service.FEATURE_NAMES)}

        item_row = (await db.execute(
            text("""SELECT item_id FROM flywheel_customer_events
                     WHERE tenant_id = :t AND customer_id = :c
                       AND event_type = 'purchase' AND item_id IS NOT NULL
                     GROUP BY item_id ORDER BY COUNT(*) DESC LIMIT 1"""),
            {"t": tenant_id, "c": customer_id},
        )).fetchone()
        if not item_row:
            continue
        item_id = int(item_row[0])

        if item_id not in price_cache:
            item = (await db.execute(
                text("SELECT unit_price_aed, category FROM items WHERE id = :i"),
                {"i": item_id})).fetchone()
            price_cache[item_id] = (money4(item[0]) if item else ZERO,
                                    item[1] if item else None,
                                    await _unit_cost(db, tenant_id, item_id))
        unit_price, category, unit_cost = price_cache[item_id]
        if unit_price <= ZERO:
            continue

        uplift_by_action = {}
        for action in (ActionType.REMINDER, ActionType.LOYALTY_POINTS,
                       ActionType.FREE_DELIVERY, ActionType.PERCENT_DISCOUNT):
            estimate = await uplift_service.estimate_for_customer(
                db, tenant_id=tenant_id, customer_id=customer_id, action=action,
                churn_probability=churn_probability, features=feats,
                discount_pct=float(max_discount), as_of=as_of)
            uplift_by_action[action] = estimate["uplift"]

        monthly_value = money(feats.get("monetary_90d_aed", 0)) / Decimal("3")
        candidates = optimizer.build_candidates(
            customer_id=customer_id, churn_probability=churn_probability,
            features=feats, monthly_value_aed=monthly_value,
            uplift_by_action=uplift_by_action, envelope=envelope, channel=channel,
            item_id=item_id, store_id=home_store, category=category,
            unit_price_aed=unit_price, unit_cost_aed=unit_cost)
        winner = optimizer.select_best(candidates, envelope=envelope)["selected"]

        action_mix[winner.action_type.value] = action_mix.get(winner.action_type.value, 0) + 1
        if winner.action_type == ActionType.NO_ACTION:
            continue

        totals["discount_cost"] = money(totals["discount_cost"] + winner.expected_discount_cost_aed)
        totals["margin"] = money(totals["margin"] + winner.expected_margin_aed)
        totals["retained_value"] = money(totals["retained_value"] + winner.expected_retained_value_aed)
        totals["comms"] = money(totals["comms"] + winner.comms_cost_aed)
        totals["fulfilment"] = money(totals["fulfilment"] + winner.fulfilment_cost_aed)
        totals["eiv"] = money(totals["eiv"] + winner.eiv_aed)
        expected_redemptions += winner.redemption_probability

        if winner.action_type.value in ("PERCENT_DISCOUNT", "FIXED_DISCOUNT", "PRODUCT_BUNDLE"):
            key = (home_store, item_id)
            stock_demand[key] = stock_demand.get(key, 0) + max(1, round(winner.redemption_probability))

    scale_dec = Decimal(str(round(scale, 4)))
    projected = {k: money(v * scale_dec) for k, v in totals.items()}

    # --- inventory reality check -----------------------------------------
    shortages: List[Dict[str, Any]] = []
    resolutions: List[Dict[str, Any]] = []
    for (store_id, item_id), units in stock_demand.items():
        scaled_units = max(1, int(units * scale))
        atp = await inventory_atp.compute_atp(
            db, tenant_id=tenant_id, store_id=store_id, item_id=item_id,
            safety_stock_pct=Decimal(str(safety_pct)), fulfilment_date=ends_on,
            exclude_campaign_id=campaign_id)
        if atp.atp_units < scaled_units:
            shortage_units = scaled_units - atp.atp_units
            shortages.append({
                "store_id": store_id, "item_id": item_id,
                "required_units": scaled_units, "atp_units": atp.atp_units,
                "shortage_units": shortage_units,
                "required_by": str(ends_on),
                "expected_eiv_aed": str(projected["eiv"]),
            })
            resolution = await inventory_atp.resolve_shortage(
                db, tenant_id=tenant_id, campaign_id=campaign_id, store_id=store_id,
                item_id=item_id, required_units=scaled_units, required_by=ends_on,
                safety_stock_pct=Decimal(str(safety_pct)),
                accessible_store_ids=accessible_store_ids,
                expected_eiv_aed=projected["eiv"])
            resolutions.append({"store_id": store_id, "item_id": item_id, **resolution})

    # --- scenarios --------------------------------------------------------
    def scenario(multiplier: Decimal) -> Dict[str, str]:
        discount = money(projected["discount_cost"] * multiplier)
        margin = money(projected["margin"] * multiplier)
        retained = money(projected["retained_value"] * multiplier)
        fixed = money(projected["comms"] + projected["fulfilment"])
        net = money(retained + margin - discount - fixed)
        spend = money(discount + fixed)
        return {
            "discount_spend_aed": str(discount),
            "incremental_margin_aed": str(margin),
            "retained_value_aed": str(retained),
            "net_value_aed": str(net),
            "roi": str(money(net / spend)) if spend > ZERO else "0.00",
        }

    expected_scenario = scenario(Decimal("1.0"))
    roi = Decimal(expected_scenario["roi"])

    # Only a PLANNING-stage simulation advances the state machine. Simulating an
    # already-approved or live campaign is a read-only "what would this do now?"
    # and must not try to drag it backwards to SIMULATED — that transition is
    # illegal, and when the caller swallowed the resulting error it silently
    # turned activation into a no-op (no allocations, wrong reservation).
    current = await campaign_state.current_status(db, tenant_id, campaign_id)
    if current in (CampaignStatus.AUDIENCE_READY, CampaignStatus.SIMULATED):
        await campaign_state.transition(
            db, tenant_id=tenant_id, campaign_id=campaign_id,
            target=CampaignStatus.SIMULATED, actor_kind="system",
            reason=f"Simulated: expected net {expected_scenario['net_value_aed']} AED, ROI {roi}")

    return {
        "campaign_id": campaign_id,
        "audience": {"treatment_total": audience_total,
                     "sampled": len(sample),
                     "scale_factor": round(scale, 3),
                     "note": "Financials are extrapolated from the sample by the "
                             "scale factor; they are an estimate, not a census."},
        "expected_redemptions": int(expected_redemptions * scale),
        "action_mix": action_mix,
        "scenarios": {
            "pessimistic": scenario(Decimal("0.6")),
            "expected": expected_scenario,
            "optimistic": scenario(Decimal("1.4")),
        },
        "discount_budget_declared_aed": str(money(declared_budget)),
        "budget_sufficient": money(declared_budget) >= money(expected_scenario["discount_spend_aed"]),
        "inventory": {
            "skus_evaluated": len(stock_demand),
            "shortages": shortages,
            "resolutions": resolutions,
        },
        "policy_version": policy_version,
        "synthetic": True,
    }


async def submit_for_approval(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    simulation: Dict[str, Any], user: Dict[str, Any],
) -> Dict[str, Any]:
    """Open the approval chain sized to this campaign's actual exposure."""
    expected = simulation.get("scenarios", {}).get("expected", {})
    discount_exposure = money(expected.get("discount_spend_aed", 0))
    procurement_exposure = ZERO
    for resolution in simulation.get("inventory", {}).get("resolutions", []):
        if resolution.get("rung") == "e_procurement":
            procurement_exposure = money(
                procurement_exposure
                + money(resolution["procurement"].get("total_cost_aed", 0)))

    store_count = len({s["store_id"] for s in simulation.get("inventory", {}).get("shortages", [])}) or 1

    result = await approvals.create_request(
        db, tenant_id=tenant_id, request_type="campaign_launch",
        campaign_id=campaign_id, discount_exposure=discount_exposure,
        procurement_exposure=procurement_exposure, store_count=store_count,
        expected_roi=float(expected.get("roi", 0) or 0),
        # The shortages are stored so ACTIVATION allocates exactly the stock the
        # reviewer saw, rather than re-deriving it from a later simulation that
        # may disagree.
        summary={"scenarios": simulation.get("scenarios"),
                 "action_mix": simulation.get("action_mix"),
                 "audience": simulation.get("audience"),
                 "shortages": simulation.get("inventory", {}).get("shortages", []),
                 "resolutions": simulation.get("inventory", {}).get("resolutions", [])},
        requested_by=user.get("id"))

    # Move to the review state matching the FIRST outstanding stage, so the
    # campaign's status tells an operator what it is actually waiting for.
    first_label = (result.get("steps") or [{}])[0].get("step_label", "Marketing")
    target = {
        "Inventory": CampaignStatus.PENDING_INVENTORY_REVIEW,
        "Procurement": CampaignStatus.PENDING_PROCUREMENT_REVIEW,
        "Finance": CampaignStatus.PENDING_FINANCE_APPROVAL,
        "CFO": CampaignStatus.PENDING_FINANCE_APPROVAL,
    }.get(first_label, CampaignStatus.PENDING_MARKETING_APPROVAL)

    await campaign_state.transition(
        db, tenant_id=tenant_id, campaign_id=campaign_id, target=target,
        actor_user_id=user.get("id"),
        reason=f"Submitted for approval — {result.get('step_count')} step(s)")

    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_APPROVAL,
        event_type="approval.requested",
        payload={"campaign_id": campaign_id, "request_id": result.get("request_id"),
                 "discount_exposure_aed": str(discount_exposure)},
        campaign_id=campaign_id)

    return {**result, "campaign_status": target.value,
            "discount_exposure_aed": str(discount_exposure),
            "procurement_exposure_aed": str(procurement_exposure)}


async def activate(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, user: Dict[str, Any],
    simulation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Take an APPROVED campaign live: reserve budget, place soft allocations,
    then transition — all in the caller's single transaction.

    REFUSES unless every approval step is approved. This is the gate that makes
    "a rejected approval cannot activate a campaign" true by construction rather
    than by convention.
    """
    approval = (await db.execute(
        text("""SELECT status, discount_exposure_aed, summary
                  FROM flywheel_approval_requests
                 WHERE tenant_id = :t AND campaign_id = :c
                 ORDER BY created_at DESC LIMIT 1"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    if not approval:
        raise ValueError("Campaign has no approval request — submit it first")
    if approval[0] != "approved":
        raise ValueError(
            f"Approval is '{approval[0]}' — only a fully approved campaign may activate")

    # --- reserve EXACTLY WHAT WAS APPROVED --------------------------------
    # The approvers signed off on a specific exposure figure; that number, not a
    # fresh re-simulation and not the campaign's declared budget, is what gets
    # reserved. Reserving the declared budget would lock (say) 25,000 AED of
    # headroom for a campaign expected to spend 42 — starving every other
    # campaign in the period for no reason. The declared budget remains the HARD
    # CAP, enforced by the guardrail sweep, not by over-reserving up front.
    exposure = money(approval[1] or 0)

    # Fall back to a live simulation only if the approval carried no figure.
    if exposure <= ZERO and simulation:
        exposure = money(simulation.get("scenarios", {})
                         .get("expected", {}).get("discount_spend_aed", 0))

    # Soft allocations come from the shortages recorded AT SUBMISSION, so the
    # stock we hold is the stock the reviewer actually saw and approved.
    approved_summary = approval[2] if isinstance(approval[2], dict) else {}
    approved_shortages = approved_summary.get("shortages") or []
    if not approved_shortages and simulation:
        approved_shortages = simulation.get("inventory", {}).get("shortages", [])

    budget_result: Dict[str, Any] = {"applied": False}
    if exposure > ZERO:
        budget_id = await budget_service.active_budget_id(
            db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
        if budget_id:
            # Raises InsufficientBudget → the whole activation aborts, leaving
            # the campaign APPROVED rather than half-live.
            budget_result = await budget_service.reserve(
                db, tenant_id=tenant_id, budget_id=budget_id, amount=exposure,
                campaign_id=campaign_id, source_type="campaign_approval",
                source_id=str(campaign_id), actor_user_id=user.get("id"),
                idempotency_key=f"activate:{tenant_id}:{campaign_id}",
                reason=f"Reserved at activation of campaign {campaign_id}")

    # --- soft allocations -------------------------------------------------
    allocations = 0
    for shortage in approved_shortages:
        await inventory_atp.allocate_soft(
            db, tenant_id=tenant_id, campaign_id=campaign_id,
            store_id=int(shortage["store_id"]), item_id=int(shortage["item_id"]),
            units=int(shortage["required_units"]))
        allocations += 1

    await campaign_state.transition(
        db, tenant_id=tenant_id, campaign_id=campaign_id,
        target=CampaignStatus.ACTIVE, actor_user_id=user.get("id"),
        reason=f"Activated — {exposure} AED reserved, {allocations} allocation(s)")

    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_CAMPAIGN,
        event_type="campaign.activated",
        payload={"campaign_id": campaign_id, "reserved_aed": str(exposure),
                 "allocations": allocations},
        campaign_id=campaign_id)

    logger.info("flywheel.activate campaign=%s reserved=%s allocations=%s",
                campaign_id, exposure, allocations)
    return {
        "campaign_id": campaign_id, "status": CampaignStatus.ACTIVE.value,
        "reserved_aed": str(exposure), "budget": budget_result,
        "soft_allocations": allocations,
    }


async def conclude(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, user: Dict[str, Any],
    cancel: bool = False,
) -> Dict[str, Any]:
    """Complete or cancel: release every unused reservation and allocation.

    This is §6.18 — unused exposure must go back to the pool, or a tenant's
    budget slowly leaks into campaigns that finished months ago.
    """
    target = CampaignStatus.CANCELLED if cancel else CampaignStatus.COMPLETED

    released = {"applied": False}
    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
    if budget_id:
        released = await budget_service.release(
            db, tenant_id=tenant_id, budget_id=budget_id, campaign_id=campaign_id,
            source_type="campaign_cancelled" if cancel else "campaign_completion",
            actor_user_id=user.get("id"),
            reason=f"Campaign {campaign_id} {'cancelled' if cancel else 'completed'}")

    allocations = await inventory_atp.release_allocations(
        db, tenant_id=tenant_id, campaign_id=campaign_id)

    await db.execute(
        text("""UPDATE flywheel_offers SET status = 'cancelled'
                 WHERE tenant_id = :t AND campaign_id = :c AND status = 'issued'"""),
        {"t": tenant_id, "c": campaign_id},
    )

    await campaign_state.transition(
        db, tenant_id=tenant_id, campaign_id=campaign_id, target=target,
        actor_user_id=user.get("id"),
        reason="Cancelled by operator" if cancel else "Campaign period complete")

    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_CAMPAIGN,
        event_type=f"campaign.{target.value.lower()}",
        payload={"campaign_id": campaign_id, "released": released,
                 "allocations": allocations},
        campaign_id=campaign_id)

    return {"campaign_id": campaign_id, "status": target.value,
            "budget_released": released, "inventory_released": allocations}
