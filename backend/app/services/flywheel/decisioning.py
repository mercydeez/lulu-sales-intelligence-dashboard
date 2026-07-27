"""Stage 5 — real-time decisioning and the atomic, idempotent redemption.

TWO ENTRY POINTS, TWO DIFFERENT SAFETY PROFILES:

  evaluate()  — read-mostly. Called at a customer interaction. Returns an action
                or a safe NO_ACTION. It may issue an offer (which reserves
                nothing physical), so its worst failure mode is a wasted offer.

  redeem()    — the money moment. Decrements real stock and converts reserved
                budget into real spend. Its worst failure mode is a double-spend
                or an oversell, so it is a SINGLE transaction with row locks and
                a database-enforced idempotency key.

THE ORDER OF OPERATIONS IN redeem() IS NOT ARBITRARY (§17). Locks are taken in a
consistent order — offer, then inventory, then budget — because taking them in
different orders in different code paths is how deadlocks happen. Every validation
happens BEFORE any mutation, so a refusal never leaves a partial write.

NO_ACTION IS A SUCCESS, NOT AN ERROR. Every gate below returns a structured
NO_ACTION with a reason code rather than raising. A decision endpoint that 500s
when consent is missing would take down the checkout it is embedded in.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import (
    budget as budget_service, churn as churn_service, contact_governance,
    features as feature_service, inventory_atp, liability, metering, objections,
    optimizer, outbox, seasonality, tax, trace, uplift as uplift_service,
)
from app.services.flywheel.campaign_state import LIVE_STATES
from app.services.flywheel.types import (
    ZERO, ActionType, BudgetType, CampaignStatus, PolicyEnvelope, ReasonCode,
    is_control, money, money4,
)

logger = logging.getLogger(__name__)

#: How long an issued offer stays redeemable.
OFFER_TTL_DAYS = 14


def _no_action(reason: ReasonCode, detail: str, **extra: Any) -> Dict[str, Any]:
    """The safe answer. Always well-formed so callers need no special casing."""
    return {
        "action": ActionType.NO_ACTION.value,
        "decision_id": None,
        "offer": None,
        "reason_codes": [reason.value],
        "detail": detail,
        "message_key": "flywheel.offer.none",
        **extra,
    }


async def _unit_cost(db: AsyncSession, tenant_id: int, item_id: int) -> Decimal:
    """Effective-dated unit cost from `item_costs` — the platform's existing
    source of truth for COGS. Falls back to a documented 70%-of-price assumption
    ONLY when no cost row exists, and the fallback is recorded on the decision so
    a reader knows the margin was estimated rather than known."""
    row = (await db.execute(
        text("""SELECT unit_cost_aed FROM item_costs
                 WHERE tenant_id = :t AND item_id = :i
                   AND valid_from <= CURRENT_DATE
                   AND (valid_until IS NULL OR valid_until > CURRENT_DATE)
                 ORDER BY valid_from DESC LIMIT 1"""),
        {"t": tenant_id, "i": item_id},
    )).fetchone()
    if row:
        return money4(row[0])
    price = (await db.execute(
        text("SELECT unit_price_aed FROM items WHERE id = :i"), {"i": item_id},
    )).scalar() or 0
    return money4(Decimal(str(price)) * Decimal("0.70"))


async def _contacts_this_week(db: AsyncSession, tenant_id: int, customer_id: int) -> int:
    return int((await db.execute(
        text("""SELECT COUNT(*) FROM flywheel_contact_log
                 WHERE tenant_id = :t AND customer_id = :c
                   AND contacted_at >= now() - INTERVAL '7 days'"""),
        {"t": tenant_id, "c": customer_id},
    )).scalar() or 0)


async def evaluate(
    db: AsyncSession, *, tenant_id: int, customer_id: int, store_id: int,
    channel: str = "email", cart_items: Optional[List[int]] = None,
    campaign_id: Optional[int] = None, request_id: Optional[str] = None,
    issue_offer: bool = True, accessible_store_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Return the next-best action for a customer at a point of interaction.

    Every gate below is checked FRESH — not read from a cached audience row.
    A campaign paused thirty seconds ago must stop issuing offers immediately,
    and stock/budget must be re-validated because the audience was built hours
    or days earlier.
    """
    # --- scope ------------------------------------------------------------
    if accessible_store_ids and store_id not in accessible_store_ids:
        return _no_action(ReasonCode.OUT_OF_SCOPE,
                          f"Store {store_id} is outside your access scope")

    customer = (await db.execute(
        text("""SELECT id, home_store_id, status FROM flywheel_customers
                 WHERE id = :c AND tenant_id = :t"""),
        {"c": customer_id, "t": tenant_id},
    )).fetchone()
    if not customer:
        return _no_action(ReasonCode.OUT_OF_SCOPE,
                          f"Customer {customer_id} not found in this tenant")
    if customer[2] == "opted_out":
        return _no_action(ReasonCode.NO_CONSENT, "Customer has opted out entirely")

    # --- PDPL: the right to object to automated profiling -----------------
    # Checked BEFORE any scoring. An objecting customer is excluded from
    # automated decisions entirely — this is a legal instruction (UAE PDPL),
    # not a value judgement, so it short-circuits ahead of every commercial gate.
    if await objections.is_objected(db, tenant_id=tenant_id, customer_id=customer_id):
        return _no_action(
            ReasonCode.PROFILING_OBJECTION,
            "Customer has objected to automated profiling (PDPL); excluded from "
            "automated decisions until the objection is withdrawn")

    # --- an ACTIVE campaign covering this customer ------------------------
    campaign_filter = "AND c.id = :cid" if campaign_id else ""
    params: Dict[str, Any] = {"t": tenant_id, "cust": customer_id}
    if campaign_id:
        params["cid"] = campaign_id

    campaign = (await db.execute(
        text(f"""SELECT c.id, c.status, c.channel, c.max_discount_pct, c.min_margin_pct,
                        c.contact_cap_per_week, c.safety_stock_pct, c.control_group_pct,
                        c.policy_version, c.starts_on, c.ends_on, a.assignment
                   FROM flywheel_campaigns c
                   JOIN flywheel_campaign_audience a
                     ON a.campaign_id = c.id AND a.customer_id = :cust
                  WHERE c.tenant_id = :t AND c.status = 'ACTIVE' {campaign_filter}
                  ORDER BY c.id DESC LIMIT 1"""),
        params,
    )).fetchone()

    if not campaign:
        return _no_action(ReasonCode.CAMPAIGN_NOT_ACTIVE,
                          "No active campaign includes this customer")

    (camp_id, status, camp_channel, max_discount, min_margin, contact_cap,
     safety_pct, control_pct, policy_version, starts_on, ends_on, assignment) = campaign

    if CampaignStatus(status) not in LIVE_STATES:
        return _no_action(ReasonCode.CAMPAIGN_NOT_ACTIVE,
                          f"Campaign {camp_id} is {status}", campaign_id=int(camp_id))

    today = date.today()
    if today < starts_on or today > ends_on:
        return _no_action(ReasonCode.CAMPAIGN_NOT_ACTIVE,
                          f"Campaign {camp_id} runs {starts_on} to {ends_on}",
                          campaign_id=int(camp_id))

    # --- CONTROL GROUP: measurable, but never treated ---------------------
    # Checked against the PERSISTED assignment (not recomputed) so a change to
    # control_group_pct mid-flight cannot move someone between arms and destroy
    # the experiment.
    if assignment == "control":
        return _no_action(ReasonCode.CONTROL_GROUP,
                          "Customer is in the control group and receives no "
                          "promotional intervention (still measured)",
                          campaign_id=int(camp_id), assignment="control")

    # --- consent + GLOBAL contact governance -------------------------------
    # One gate covering consent (re-checked NOW, not at audience build), the
    # daily cap, the per-channel weekly cap, the ALL-CHANNEL weekly ceiling and
    # the ignore-cooldown — all counted ACROSS EVERY LIVE CAMPAIGN.
    #
    # The per-campaign cap this replaced was unsound: three campaigns each
    # capped at 2 could contact the same person six times a week, each
    # individually compliant. A customer does not experience campaigns, they
    # experience messages.
    gate = await contact_governance.may_contact(
        db, tenant_id=tenant_id, customer_id=customer_id, channel=channel,
        campaign_id=int(camp_id))
    if not gate.allowed:
        code = (ReasonCode.NO_CONSENT if gate.reason_code == "NO_CONSENT"
                else ReasonCode.CONTACT_CAP_REACHED)
        return _no_action(code, gate.detail, campaign_id=int(camp_id),
                          contact_counts=gate.counts,
                          governance_reason=gate.reason_code)

    # --- model inputs -----------------------------------------------------
    as_of = await feature_service.latest_snapshot_date(db, tenant_id) or today
    score = await churn_service.get_score(db, tenant_id=tenant_id, customer_id=customer_id)
    churn_probability = score["churn_probability"] if score else 0.5
    feats = await feature_service.load_snapshot(
        db, tenant_id=tenant_id, customer_id=customer_id, as_of=as_of) or {}

    # Candidate item: the cart, else the customer's most-bought recent item.
    item_id = cart_items[0] if cart_items else None
    if item_id is None:
        row = (await db.execute(
            text("""SELECT item_id FROM flywheel_customer_events
                     WHERE tenant_id = :t AND customer_id = :c
                       AND event_type = 'purchase' AND item_id IS NOT NULL
                     GROUP BY item_id ORDER BY COUNT(*) DESC LIMIT 1"""),
            {"t": tenant_id, "c": customer_id},
        )).fetchone()
        item_id = int(row[0]) if row else None

    if item_id is None:
        return _no_action(ReasonCode.NO_PRICE_DATA,
                          "No candidate item for this customer",
                          campaign_id=int(camp_id))

    item = (await db.execute(
        text("SELECT unit_price_aed, category FROM items WHERE id = :i"), {"i": item_id},
    )).fetchone()
    if not item:
        return _no_action(ReasonCode.NO_PRICE_DATA, f"Item {item_id} not found",
                          campaign_id=int(camp_id))
    unit_price = money4(item[0])
    category = item[1]
    unit_cost = await _unit_cost(db, tenant_id, item_id)

    monthly_value = money(feats.get("monetary_90d_aed", 0)) / Decimal("3")

    # SEASONALITY (Horizon 4). Scale the customer's forward value by the demand
    # multiplier in force today — a retention offer made before Ramadan is worth
    # more because the customer's near-term value genuinely is. Deterministic
    # policy from the seasonality calendar; the optimizer never sees it as
    # anything but a value, so its determinism and "no model" guarantee hold. A
    # neutral 1.0 (the default when no season applies) leaves the value untouched.
    season_factor = await seasonality.factor_for(
        db, tenant_id=tenant_id, category=category)
    if season_factor != Decimal("1.000"):
        monthly_value = money(monthly_value * season_factor)

    # --- FRESH stock and budget guards ------------------------------------
    if not await inventory_atp.inventory_freshness_ok(db, store_id=store_id, item_id=item_id):
        return _no_action(ReasonCode.STALE_DATA,
                          "Inventory data is too stale to promise against",
                          campaign_id=int(camp_id))

    atp = await inventory_atp.compute_atp(
        db, tenant_id=tenant_id, store_id=store_id, item_id=item_id,
        safety_stock_pct=Decimal(str(safety_pct)))

    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
    budget_snapshot = (await budget_service.snapshot(
        db, tenant_id=tenant_id, budget_id=budget_id)) if budget_id else {}
    available_budget = money(budget_snapshot.get("available_aed", 0))
    if budget_id and available_budget <= ZERO:
        return _no_action(ReasonCode.INSUFFICIENT_BUDGET,
                          "Discount budget is exhausted", campaign_id=int(camp_id))

    # --- uplift per action, then the optimizer ----------------------------
    envelope = PolicyEnvelope(
        max_discount_pct=Decimal(str(max_discount)),
        min_margin_pct=Decimal(str(min_margin)),
        contact_cap_per_week=int(contact_cap),
        safety_stock_pct=Decimal(str(safety_pct)),
        policy_version=policy_version,
    )

    uplift_by_action: Dict[ActionType, float] = {}
    for action in (ActionType.REMINDER, ActionType.LOYALTY_POINTS,
                   ActionType.FREE_DELIVERY, ActionType.PERCENT_DISCOUNT):
        estimate = await uplift_service.estimate_for_customer(
            db, tenant_id=tenant_id, customer_id=customer_id, action=action,
            churn_probability=churn_probability, features=feats,
            discount_pct=float(max_discount), as_of=as_of)
        uplift_by_action[action] = estimate["uplift"]

    tax_rule = await tax.rule_for(db, tenant_id=tenant_id, category=category)

    candidates = optimizer.build_candidates(
        customer_id=customer_id, churn_probability=churn_probability, features=feats,
        monthly_value_aed=monthly_value, uplift_by_action=uplift_by_action,
        envelope=envelope, channel=channel, item_id=item_id, store_id=store_id,
        category=category, unit_price_aed=unit_price, unit_cost_aed=unit_cost,
        atp_units=atp.atp_units, tax_rule=tax_rule)

    result = optimizer.select_best(candidates, envelope=envelope)
    winner = result["selected"]

    # Budget affordability of the CHOSEN action, checked last so the reason code
    # is specific ("we chose this but cannot afford it") rather than generic.
    if budget_id and winner.expected_discount_cost_aed > available_budget:
        result["rejected"].append({
            "action": winner.action_type.value,
            "reason_code": ReasonCode.INSUFFICIENT_BUDGET.value,
            "detail": f"needs {winner.expected_discount_cost_aed} AED, "
                      f"{available_budget} available",
        })
        winner = next(c for c in candidates if c.action_type == ActionType.NO_ACTION)
        winner.reason_codes = [ReasonCode.INSUFFICIENT_BUDGET.value]

    # --- persist the decision (always, including NO_ACTION) ---------------
    row = winner.to_row()
    decision = (await db.execute(
        text("""INSERT INTO flywheel_decisions
                   (tenant_id, campaign_id, customer_id, store_id, item_id, category,
                    action_type, churn_probability, uplift, redemption_probability,
                    unit_price_aed, unit_cost_aed, discount_pct,
                    expected_retained_value_aed, expected_margin_aed,
                    expected_discount_cost_aed, comms_cost_aed, fulfilment_cost_aed,
                    procurement_cost_aed, stockout_risk_penalty_aed, eiv_aed,
                    reason_codes, rejected_actions, inventory_snapshot, budget_snapshot,
                    churn_model_version_id, policy_version, request_id,
                    tax_rate_pct, net_price_aed, margin_net_pct, trace_id)
                VALUES (:t, :c, :cust, :store, :item, :cat, :action, :churn, :uplift,
                        :redeem, :price, :cost, :discount, :retained, :margin,
                        :disc_cost, :comms, :fulfil, :procure, :stockout, :eiv,
                        CAST(:reasons AS JSONB), CAST(:rejected AS JSONB),
                        CAST(:inv AS JSONB), CAST(:bud AS JSONB), :model, :policy, :rid,
                        :tax_rate, :net_price, :margin_net, :trace)
                RETURNING id"""),
        {"t": tenant_id, "c": int(camp_id), "cust": customer_id, "store": store_id,
         "item": row["item_id"], "cat": row["category"], "action": row["action_type"],
         "churn": row["churn_probability"], "uplift": row["uplift"],
         "redeem": row["redemption_probability"], "price": row["unit_price_aed"],
         "cost": row["unit_cost_aed"], "discount": row["discount_pct"],
         "retained": row["expected_retained_value_aed"], "margin": row["expected_margin_aed"],
         "disc_cost": row["expected_discount_cost_aed"], "comms": row["comms_cost_aed"],
         "fulfil": row["fulfilment_cost_aed"], "procure": row["procurement_cost_aed"],
         "stockout": row["stockout_risk_penalty_aed"], "eiv": row["eiv_aed"],
         "reasons": json.dumps(winner.reason_codes),
         "rejected": json.dumps(result["rejected"]),
         "inv": json.dumps(atp.to_snapshot()), "bud": json.dumps(budget_snapshot),
         "model": score["model_version_id"] if score else None,
         "policy": policy_version, "rid": request_id,
         # Tax snapshotted alongside price and cost, for the same reason: a
         # decision must stay explainable after the VAT rate changes.
         "tax_rate": tax_rule.rate_pct,
         "net_price": winner.net_price_aed,
         "margin_net": winner.margin_net_pct,
         # The trace spans this decision's whole life; mint one if the request
         # did not already carry one, so even a decision made by a background job
         # is traceable end to end.
         "trace": trace.ensure_trace_id(request_id)},
    )).fetchone()
    decision_id = int(decision[0])

    # METER the decision. Every decision served is a billable event under the
    # hybrid pricing model. Best-effort and in its own session — a metering
    # failure must never fail the decision (see metering.record).
    await metering.record(tenant_id, metering.EVENT_DECISION,
                          metadata={"decision_id": decision_id, "campaign_id": int(camp_id)})

    if winner.action_type == ActionType.NO_ACTION:
        # The optimizer's own codes are authoritative and may include values
        # that are not ReasonCode members (e.g. BASELINE_DO_NOTHING), so they
        # are passed through verbatim rather than coerced into the enum.
        return {**_no_action(ReasonCode.NEGATIVE_EIV,
                             "No action beats doing nothing for this customer"),
                "decision_id": decision_id, "campaign_id": int(camp_id),
                "reason_codes": winner.reason_codes,
                "rejected_actions": result["rejected"],
                "eiv_aed": str(winner.eiv_aed)}

    # --- issue the offer --------------------------------------------------
    offer_payload = None
    if issue_offer:
        offer_code = f"HQ-{camp_id}-{secrets.token_hex(4).upper()}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=OFFER_TTL_DAYS)
        offer = (await db.execute(
            text("""INSERT INTO flywheel_offers
                       (tenant_id, campaign_id, customer_id, decision_id, offer_code,
                        action_type, store_id, item_id, discount_pct, reserved_aed,
                        status, expires_at)
                    VALUES (:t, :c, :cust, :d, :code, :action, :store, :item,
                            :discount, :reserved, 'issued', :exp)
                    RETURNING id"""),
            {"t": tenant_id, "c": int(camp_id), "cust": customer_id, "d": decision_id,
             "code": offer_code, "action": winner.action_type.value, "store": store_id,
             "item": winner.item_id, "discount": winner.discount_pct,
             "reserved": winner.expected_discount_cost_aed, "exp": expires_at},
        )).fetchone()

        # An issued offer is a LIABILITY from this moment: the customer may
        # redeem it, so the business is exposed. Recorded here, in the same
        # transaction as the offer, so exposure can never exist unrecorded.
        await liability.record_liability(
            db, tenant_id=tenant_id, offer_id=int(offer[0]),
            amount=winner.expected_discount_cost_aed)

        # Logged through the governance service (same transaction as the
        # offer) — a crash between issuing and logging would let the cap be
        # bypassed on the retry.
        await contact_governance.record_contact(
            db, tenant_id=tenant_id, customer_id=customer_id,
            channel=channel, campaign_id=int(camp_id))

        offer_payload = {
            "offer_id": int(offer[0]), "offer_code": offer_code,
            "action": winner.action_type.value,
            "discount_pct": str(winner.discount_pct),
            "item_id": winner.item_id, "store_id": store_id,
            "unit_price_aed": str(winner.unit_price_aed),
            "expires_at": expires_at.isoformat(),
        }

        await outbox.emit(
            db, tenant_id=tenant_id, channel=outbox.CHANNEL_OFFER,
            event_type="offer.issued",
            payload={"offer_code": offer_code, "campaign_id": int(camp_id),
                     "action": winner.action_type.value, "store_id": store_id},
            store_id=store_id, campaign_id=int(camp_id))

    return {
        "action": winner.action_type.value,
        "decision_id": decision_id,
        "campaign_id": int(camp_id),
        "offer": offer_payload,
        "reason_codes": winner.reason_codes,
        "rejected_actions": result["rejected"],
        "eiv_aed": str(winner.eiv_aed),
        "churn_probability": round(churn_probability, 4),
        "uplift": round(winner.uplift, 4),
        "inventory_status": atp.to_snapshot(),
        "budget_status": budget_snapshot,
        "model_version": score["model_version"] if score else "none",
        "policy_version": policy_version,
        "message_key": f"flywheel.offer.{winner.action_type.value.lower()}",
        "assignment": "treatment",
        "synthetic": True,
    }


async def redeem(
    db: AsyncSession, *, tenant_id: int, offer_code: str, units: int,
    idempotency_key: str, store_id: Optional[int] = None,
    actor_user_id: Optional[int] = None, request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Redeem an offer in ONE transaction. The money moment.

    Order (locks acquired consistently to avoid deadlock):
      1. Replay check on the idempotency key — return the ORIGINAL result.
      2. Lock the offer row; validate status and expiry.
      3. Lock the inventory row; validate stock; decrement.
      4. Lock the budget row; convert reserved → spent.
      5. Write redemption + inventory ledger + allocation consumption.
      6. Emit the outbox event (co-committed with all of the above).

    Every validation precedes every mutation, so a refusal can never leave the
    system half-changed. Does not commit — the route wraps it so the outbox row
    and the money move share one commit.
    """
    # --- 1. idempotency: a retry returns the original, it does not re-apply ---
    existing = (await db.execute(
        text("""SELECT id, offer_id, units, discount_aed, net_value_aed, created_at
                  FROM flywheel_redemptions
                 WHERE tenant_id = :t AND idempotency_key = :k"""),
        {"t": tenant_id, "k": idempotency_key},
    )).fetchone()
    if existing:
        logger.info("flywheel.redeem replay key=%s → redemption %s", idempotency_key, existing[0])
        return {
            "redemption_id": int(existing[0]), "replayed": True, "applied": False,
            "units": int(existing[2]), "discount_aed": str(money(existing[3])),
            "net_value_aed": str(money(existing[4])),
            "detail": "Idempotent replay — the original redemption is returned "
                      "and nothing was charged or decremented a second time",
        }

    # --- 2. lock and validate the offer -------------------------------------
    # The originating decision's trace_id is pulled forward so the redemption —
    # which happens on a different request, possibly days later — joins back to
    # the decision that created the offer. That is what makes the decision
    # timeline (trace.decision_timeline) show the full life, not just the birth.
    offer = (await db.execute(
        text("""SELECT o.id, o.campaign_id, o.customer_id, o.store_id, o.item_id,
                       o.discount_pct, o.status, o.expires_at, o.reserved_aed,
                       o.action_type, d.trace_id
                  FROM flywheel_offers o
                  LEFT JOIN flywheel_decisions d ON d.id = o.decision_id
                 WHERE o.tenant_id = :t AND o.offer_code = :code
                 FOR UPDATE OF o"""),
        {"t": tenant_id, "code": offer_code},
    )).fetchone()
    if not offer:
        raise ValueError(f"Offer {offer_code} not found")

    (offer_id, campaign_id, customer_id, offer_store, item_id, discount_pct,
     status, expires_at, reserved_aed, action_type, decision_trace_id) = offer

    if status != "issued":
        raise ValueError(f"Offer {offer_code} is already '{status}' and cannot be redeemed")
    if expires_at and expires_at < datetime.now(timezone.utc):
        await db.execute(
            text("UPDATE flywheel_offers SET status = 'expired' WHERE id = :o"), {"o": offer_id})
        raise ValueError(f"Offer {offer_code} expired on {expires_at.date()}")

    campaign_status = (await db.execute(
        text("SELECT status FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"),
        {"c": campaign_id, "t": tenant_id},
    )).scalar()
    if CampaignStatus(campaign_status) not in LIVE_STATES:
        raise ValueError(f"Campaign {campaign_id} is {campaign_status} — redemption refused")

    target_store = store_id or offer_store
    if target_store is None or item_id is None:
        raise ValueError(f"Offer {offer_code} has no store/item to redeem against")

    # --- 3. lock inventory and validate stock -------------------------------
    # FOR UPDATE here is what makes concurrent redemptions safe: the second
    # transaction waits and then re-reads the DECREMENTED stock, so two
    # simultaneous redemptions of the last unit cannot both succeed.
    inventory = (await db.execute(
        text("""SELECT id, current_stock, COALESCE(reserved_stock, 0)
                  FROM inventory WHERE store_id = :s AND item_id = :i FOR UPDATE"""),
        {"s": target_store, "i": item_id},
    )).fetchone()
    if not inventory:
        raise ValueError(f"No inventory record for store {target_store}, item {item_id}")

    inventory_id = int(inventory[0])
    on_hand = int(inventory[1])
    if on_hand < units:
        raise ValueError(
            f"Insufficient stock: {on_hand} unit(s) on hand, {units} requested")

    # --- pricing (snapshot at redemption time) ------------------------------
    unit_price = money4((await db.execute(
        text("SELECT unit_price_aed FROM items WHERE id = :i"), {"i": item_id},
    )).scalar() or 0)
    unit_cost = await _unit_cost(db, tenant_id, item_id)

    # Tax-aware settlement. `net` is what the customer PAYS (tax-inclusive, the
    # till figure); `net_of_tax` is what the business KEEPS after remitting.
    # Margin is computed on the latter — the earlier version margined on the
    # tax-inclusive amount and overstated every redemption by the VAT rate.
    category_row = (await db.execute(
        text("SELECT category FROM items WHERE id = :i"), {"i": item_id})).fetchone()
    tax_rule = await tax.rule_for(
        db, tenant_id=tenant_id, category=category_row[0] if category_row else None)

    gross = money(unit_price * Decimal(units))
    discount = money(gross * Decimal(str(discount_pct)) / Decimal("100"))
    net = money(gross - discount)                 # customer pays this
    net_of_tax = tax_rule.net_of_tax(net)         # business keeps this
    tax_amount = money(net - net_of_tax)
    margin = money(net_of_tax - money(unit_cost * Decimal(units)))

    # --- 4a. THE PER-CAMPAIGN HARD CAP, checked BEFORE any money moves ------
    #
    # This is a CONTROL, not a report. The guardrail sweep also watches campaign
    # burn, but it necessarily runs AFTER a redemption commits — so on its own it
    # can only tell you that you have already overspent. Measured live: a
    # campaign approved for 37.49 AED reached 57.20 before the sweep paused it.
    #
    # `discount_budget_aed` is the operator's declared ceiling for THIS campaign
    # and is enforced here, inside the same transaction and before the spend, so
    # a campaign can never consume budget its own cap does not permit — however
    # much headroom the tenant-wide pool happens to have.
    #
    # The approved exposure is an ESTIMATE of expected spend and deliberately is
    # NOT the hard stop: redemptions are stochastic, and refusing at 100% of an
    # estimate would kill campaigns that are merely performing well. Exceeding
    # the estimate raises the guardrail; exceeding the CAP is refused outright.
    campaign_cap = money((await db.execute(
        text("SELECT discount_budget_aed FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"),
        {"c": campaign_id, "t": tenant_id},
    )).scalar() or 0)

    if campaign_cap > ZERO and discount > ZERO:
        already_spent = money((await db.execute(
            text("""SELECT COALESCE(SUM(amount_aed), 0) FROM flywheel_budget_ledger
                     WHERE tenant_id = :t AND campaign_id = :c AND entry_type = 'SPENT'"""),
            {"t": tenant_id, "c": campaign_id},
        )).scalar() or 0)
        if money(already_spent + discount) > campaign_cap:
            raise ValueError(
                f"Refused: this redemption would take campaign {campaign_id} to "
                f"{money(already_spent + discount)} AED against its approved cap of "
                f"{campaign_cap} AED (already spent {already_spent})")

    # --- 4b. budget: reserved → spent ---------------------------------------
    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
    budget_result: Dict[str, Any] = {"applied": False}
    if budget_id and discount > ZERO:
        # Raises InsufficientBudget if this would breach the allocation — which
        # aborts the whole transaction, leaving stock untouched.
        budget_result = await budget_service.spend(
            db, tenant_id=tenant_id, budget_id=budget_id, amount=discount,
            campaign_id=int(campaign_id), source_type="redemption",
            source_id=offer_code, actor_user_id=actor_user_id,
            request_id=request_id, idempotency_key=f"redeem:{idempotency_key}",
            reason=f"Redemption of {offer_code}")

    # --- 5. mutate: stock, offer, allocation, redemption row ---------------
    await db.execute(
        text("""UPDATE inventory
                   SET current_stock = current_stock - :u,
                       last_sale_date = CURRENT_DATE,
                       updated_at = now()
                 WHERE store_id = :s AND item_id = :i"""),
        {"u": units, "s": target_store, "i": item_id},
    )

    # The existing inventory ledger — Flywheel movements appear alongside every
    # other stock movement rather than in a private log.
    #
    # `stock_before`/`stock_after` are NOT NULL on this table, and they are the
    # reason it is trustworthy: every row carries the balance either side of the
    # move, so the ledger reconciles independently of the inventory row. We are
    # inside the FOR UPDATE on that row, so `on_hand` is the true before-value.
    # `transaction_type` is the inventory_transaction_type enum ('sale' here);
    # the reference is split across reference_type/reference_id.
    await db.execute(
        text("""INSERT INTO inventory_transactions
                   (inventory_id, store_id, item_id, transaction_type, quantity,
                    stock_before, stock_after, reference_type, reference_id,
                    notes, performed_by)
                VALUES (:inv, :s, :i, 'sale', :q, :before, :after,
                        'flywheel_offer', :ref, :notes, :actor)"""),
        {"inv": inventory_id, "s": target_store, "i": item_id, "q": -units,
         "before": on_hand, "after": on_hand - units, "ref": offer_code,
         "notes": f"Flywheel campaign {campaign_id} redemption",
         "actor": actor_user_id},
    )

    await db.execute(
        text("""UPDATE flywheel_inventory_allocations
                   SET consumed_units = LEAST(allocated_units, consumed_units + :u)
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND store_id = :s AND item_id = :i"""),
        {"u": units, "t": tenant_id, "c": campaign_id, "s": target_store, "i": item_id},
    )

    await db.execute(
        text("""UPDATE flywheel_offers
                   SET status = 'redeemed', redeemed_at = now() WHERE id = :o"""),
        {"o": offer_id},
    )

    try:
        redemption = (await db.execute(
            text("""INSERT INTO flywheel_redemptions
                       (tenant_id, offer_id, campaign_id, customer_id, store_id, item_id,
                        units, gross_value_aed, discount_aed, net_value_aed, margin_aed,
                        idempotency_key, request_id,
                        tax_rate_pct, tax_amount_aed, net_of_tax_aed, trace_id)
                    VALUES (:t, :o, :c, :cust, :s, :i, :u, :gross, :disc, :net, :margin,
                            :key, :rid, :tax_rate, :tax_amt, :net_of_tax, :trace)
                    RETURNING id"""),
            {"t": tenant_id, "o": offer_id, "c": campaign_id, "cust": customer_id,
             "s": target_store, "i": item_id, "u": units, "gross": gross,
             "disc": discount, "net": net, "margin": margin,
             "key": idempotency_key, "rid": request_id,
             "tax_rate": tax_rule.rate_pct, "tax_amt": tax_amount,
             "net_of_tax": net_of_tax,
             # Inherit the decision's trace so the redemption joins its origin.
             "trace": decision_trace_id or trace.ensure_trace_id(request_id)},
        )).fetchone()
    except IntegrityError:
        # Another request with the same key won the race between our check at
        # step 1 and this insert. The unique constraint is the arbiter.
        raise ValueError("Concurrent redemption with the same idempotency key")

    redemption_id = int(redemption[0])

    # Record the purchase as a customer event so it feeds the next feature
    # snapshot — this is literally where the Flywheel loop closes back to stage 1.
    await db.execute(
        text("""INSERT INTO flywheel_customer_events
                   (tenant_id, customer_id, event_type, occurred_at, store_id, item_id,
                    quantity_units, value_aed, margin_aed, metadata)
                VALUES (:t, :c, 'offer_redeemed', now(), :s, :i, :u, :v, :m,
                        CAST(:meta AS JSONB))"""),
        {"t": tenant_id, "c": customer_id, "s": target_store, "i": item_id,
         "u": units, "v": net, "m": margin,
         "meta": json.dumps({"offer_code": offer_code, "campaign_id": int(campaign_id)})},
    )

    # --- 6. outbox, co-committed with everything above ---------------------
    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_OFFER,
        event_type="offer.redeemed",
        payload={"offer_code": offer_code, "campaign_id": int(campaign_id),
                 "units": units, "discount_aed": str(discount),
                 "net_value_aed": str(net), "store_id": target_store},
        store_id=target_store, campaign_id=int(campaign_id))
    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_INVENTORY,
        event_type="inventory.decremented",
        payload={"store_id": target_store, "item_id": item_id,
                 "units": units, "remaining": on_hand - units},
        store_id=target_store, campaign_id=int(campaign_id))

    logger.info("flywheel.redeem offer=%s units=%s discount=%s redemption=%s",
                offer_code, units, discount, redemption_id)

    return {
        "redemption_id": redemption_id, "replayed": False, "applied": True,
        "offer_code": offer_code, "campaign_id": int(campaign_id),
        "units": units,
        "gross_value_aed": str(gross), "discount_aed": str(discount),
        "net_value_aed": str(net), "margin_aed": str(margin),
        "tax_rate_pct": str(tax_rule.rate_pct),
        "tax_amount_aed": str(tax_amount),
        "net_of_tax_aed": str(net_of_tax),
        "tax_note": f"Customer paid {net} AED including {tax_amount} AED tax; "
                    f"margin is on the {net_of_tax} AED retained.",
        "stock_remaining": on_hand - units,
        "budget": budget_result,
    }


async def expire_offers(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """Expire lapsed offers and release the exposure they were holding (§6.18)."""
    rows = (await db.execute(
        text("""UPDATE flywheel_offers
                   SET status = 'expired'
                 WHERE tenant_id = :t AND status = 'issued' AND expires_at < now()
                 RETURNING id, campaign_id, reserved_aed"""),
        {"t": tenant_id},
    )).fetchall()
    if not rows:
        return {"expired": 0, "released_aed": "0.00"}

    by_campaign: Dict[int, Decimal] = {}
    for _oid, campaign_id, reserved in rows:
        by_campaign[int(campaign_id)] = money(
            by_campaign.get(int(campaign_id), ZERO) + money(reserved))

    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
    total = ZERO
    if budget_id:
        for campaign_id, amount in by_campaign.items():
            if amount > ZERO:
                await budget_service.release(
                    db, tenant_id=tenant_id, budget_id=budget_id, amount=amount,
                    campaign_id=campaign_id, source_type="offer_expiry",
                    reason="Offers expired unredeemed")
                total = money(total + amount)

    return {"expired": len(rows), "released_aed": str(total)}
