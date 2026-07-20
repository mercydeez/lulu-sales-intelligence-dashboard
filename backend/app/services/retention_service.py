"""
Retention & Commercial Orchestration — the closed-loop decisioning service.

Flow: audience (churn scores + treatment/control) -> simulate (deterministic
next-best-action optimizer + inventory ladder) -> approve (budget reserve +
soft allocations, threshold from the existing approval_rules) -> activate
(issue offers) -> evaluate (real-time guarded decision) -> redeem (single
locked transaction: inventory + budget + ledgers) -> outcomes (treatment vs
control).

Reuses: items.unit_price_aed/unit_cost_aed (005/058) for price+cost snapshots,
inventory + inventory_transactions (002) for stock truth, purchase_orders (016)
for procurement requisitions, approval_rules (019) for the approval threshold,
publish_alert for notifications.

HONESTY: the churn model is a deterministic, documented heuristic
(churn_heuristic_v1) over synthetic data — reproducible, explainable via reason
codes, and never presented as a trained production model. No LLM touches any
mutation in this module.

Money is Decimal end-to-end; probabilities are floats (they are not money).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger

MODEL_VERSION = "churn_heuristic_v1"
POLICY_VERSION = "policy_v1"
COMM_COST_AED = Decimal("0.05")     # per-contact communication cost
RETENTION_LIFT = 0.4                # share of churn risk removed by a response
CENT = Decimal("0.01")

# Campaign state machine — validated here, never by arbitrary status writes.
# The spec's four PENDING_* review states collapse into 'pending_approval' for
# slice 1: the approval requirement is threshold-driven (approval_rules), and a
# procurement requisition is a linked draft PO reviewed in the procurement
# module. ponytail: parallel per-role approval steps when a real approval chain is needed.
STATUS_TRANSITIONS: Dict[str, set] = {
    "draft": {"audience_ready", "cancelled"},
    "audience_ready": {"simulated", "draft", "cancelled"},
    "simulated": {"pending_approval", "audience_ready", "cancelled"},
    "pending_approval": {"approved", "simulated", "cancelled"},
    "approved": {"active", "cancelled"},
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "completed", "cancelled"},
    "completed": {"measured"},
    "measured": set(),
    "cancelled": set(),
}

ACTIONS = ("NO_ACTION", "REMINDER", "PERCENT_DISCOUNT", "SUBSTITUTE_PRODUCT")


# ---------------------------------------------------------------------------
# Pure decision logic (unit-testable without a database)
# ---------------------------------------------------------------------------

def assign_cohort(tenant_id: int, campaign_id: int, customer_id: int,
                  control_pct: float) -> str:
    """Deterministic treatment/control split: stable SHA-256 hash of the
    (tenant, campaign, customer) triple. Same inputs -> same cohort, forever."""
    h = hashlib.sha256(f"{tenant_id}:{campaign_id}:{customer_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) % 10000
    return "control" if bucket < control_pct * 100 else "treatment"


def churn_score(features: Dict) -> Tuple[float, List[str]]:
    """Deterministic churn probability + reason codes.

    Logistic over documented behavioural features (no sensitive attributes):
      recency_days, purchases_90d, interpurchase_interval deviation,
      promo_rate (discount dependency), return_rate.
    Label definition (documented, leak-free): 'churned' = no purchase in the
    45 days after the scoring date, for customers active in the prior 90 days.
    """
    recency = float(features.get("recency_days") or 999)
    freq_90 = float(features.get("purchases_90d") or 0)
    interval = float(features.get("avg_interval_days") or 30)
    promo_rate = float(features.get("promo_rate") or 0)
    return_rate = float(features.get("return_rate") or 0)

    # Deviation from the customer's own rhythm is the strongest signal.
    overdue = recency / max(interval, 1.0)

    z = -2.2 + 1.1 * min(overdue, 5.0) + 0.05 * max(0.0, 10 - freq_90) \
        + 0.6 * return_rate + 0.3 * promo_rate
    score = 1.0 / (1.0 + math.exp(-z))

    reasons: List[str] = []
    if overdue >= 2.0:
        reasons.append("overdue_vs_own_rhythm")
    if recency >= 30:
        reasons.append("recency_high")
    if freq_90 <= 2:
        reasons.append("low_frequency_90d")
    if promo_rate >= 0.5:
        reasons.append("discount_dependent")
    if return_rate >= 0.2:
        reasons.append("high_return_ratio")
    if not reasons:
        reasons.append("active_baseline")
    return round(score, 3), reasons


def response_prob(churn: float, discount_pct: float, promo_rate: float) -> float:
    """Deterministic offer-response estimate. Documented, not trained:
    base propensity rises with historical promo affinity; discount depth lifts
    it; very-high churn dampens it (disengaged customers respond less)."""
    base = 0.10 + 0.45 * promo_rate
    lift = (discount_pct / 100.0) * 1.2 * (0.5 + 0.5 * promo_rate)
    damp = 1.0 - 0.35 * max(0.0, churn - 0.5)
    return round(min(0.95, max(0.02, (base + lift) * damp)), 3)


def action_ev(action: str, *, churn: float, resp: float,
              price: Decimal, cost: Optional[Decimal],
              discount_pct: Decimal, monthly_value: Decimal) -> Decimal:
    """Expected incremental value of one candidate action for one customer.

    EV = retained value + incremental purchase margin - discount cost - comm cost.
    Decimal throughout; returns AED rounded to the cent.
    """
    if action == "NO_ACTION":
        return Decimal("0.00")
    d = discount_pct / Decimal(100)
    resp_d = Decimal(str(resp))
    retained = Decimal(str(churn)) * Decimal(str(RETENTION_LIFT)) * resp_d * monthly_value
    unit_margin = (price * (1 - d) - cost) if cost is not None else Decimal("0")
    margin_gain = resp_d * unit_margin
    discount_cost = resp_d * price * d
    return (retained + margin_gain - discount_cost - COMM_COST_AED).quantize(CENT, ROUND_HALF_UP)


def choose_action(*, churn: float, promo_rate: float, price: Decimal,
                  cost: Optional[Decimal], monthly_value: Decimal,
                  max_discount_pct: Decimal, min_margin_pct: Decimal
                  ) -> Tuple[str, Decimal, float, Decimal, List[str]]:
    """Deterministic next-best-action: evaluate every allowed candidate, pick
    the highest positive EV. High churn alone never forces a discount — the EV
    decides. Returns (action, discount_pct, response_prob, ev, reason_codes)."""
    candidates: List[Tuple[str, Decimal, float, Decimal, List[str]]] = [
        ("NO_ACTION", Decimal("0"), 0.0, Decimal("0.00"), ["no_positive_ev_action"]),
    ]
    r = response_prob(churn, 0.0, promo_rate)
    candidates.append(("REMINDER", Decimal("0"), r,
                       action_ev("REMINDER", churn=churn, resp=r, price=price,
                                 cost=cost, discount_pct=Decimal("0"),
                                 monthly_value=monthly_value),
                       ["reminder_no_discount_cost"]))

    for pct in (Decimal("5"), Decimal("10"), max_discount_pct):
        if pct <= 0 or pct > max_discount_pct:
            continue
        # Margin floor: a discount may never sell below min_margin_pct of price.
        if cost is None:
            continue  # cost unknown -> discounting is not policy-safe
        sell = price * (1 - pct / Decimal(100))
        margin_pct = (sell - cost) / price * Decimal(100)
        if margin_pct < min_margin_pct:
            continue
        r = response_prob(churn, float(pct), promo_rate)
        ev = action_ev("PERCENT_DISCOUNT", churn=churn, resp=r, price=price,
                       cost=cost, discount_pct=pct, monthly_value=monthly_value)
        candidates.append(("PERCENT_DISCOUNT", pct, r, ev,
                           [f"discount_{pct}pct_margin_ok"]))

    best = max(candidates, key=lambda c: (c[3], c[0] == "NO_ACTION"))
    if best[3] <= 0:
        # Nothing beats doing nothing.
        reasons = ["negative_or_zero_ev"] + (["cost_unknown"] if cost is None else [])
        return "NO_ACTION", Decimal("0"), 0.0, Decimal("0.00"), reasons
    return best


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _log_event(db: AsyncSession, tenant_id: int, event_type: str,
                     entity_type: str, entity_id: Optional[int], summary: str,
                     actor: Optional[int] = None, metadata: Optional[Dict] = None) -> None:
    """Audit event inside the caller's transaction. Best-effort."""
    try:
        await db.execute(text("""
            INSERT INTO retention_events
                (tenant_id, event_type, entity_type, entity_id, actor_user_id, summary, metadata)
            VALUES (:t, :et, :ent, :eid, :actor, :summary, CAST(:meta AS jsonb))
        """), {"t": tenant_id, "et": event_type, "ent": entity_type, "eid": entity_id,
               "actor": actor, "summary": summary, "meta": json.dumps(metadata or {}, default=str)})
    except Exception as e:  # pragma: no cover
        logger.warning(f"retention audit log failed ({event_type}): {e}")


async def _notify(payload: Dict) -> None:
    """Post-commit notification via the existing alerts stream. Best-effort —
    Postgres (offers/ledger/events) is the financial record, never Redis."""
    try:
        from app.services.redis_client import publish_alert
        await publish_alert(payload)
    except Exception as e:  # pragma: no cover
        logger.debug(f"retention notify skipped: {e}")


async def _get_campaign_row(db: AsyncSession, tenant_id: int, campaign_id: int,
                            lock: bool = False):
    row = (await db.execute(text(f"""
        SELECT * FROM retention_campaigns
        WHERE id = :id AND tenant_id = :t {'FOR UPDATE' if lock else ''}
    """), {"id": campaign_id, "t": tenant_id})).mappings().fetchone()
    if not row:
        raise ValueError(f"Campaign {campaign_id} not found")
    return row


def _require_transition(current: str, new: str) -> None:
    if new not in STATUS_TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot move campaign from '{current}' to '{new}'")


async def _set_status(db: AsyncSession, tenant_id: int, campaign_id: int,
                      new_status: str, paused_reason: Optional[str] = None) -> None:
    await db.execute(text("""
        UPDATE retention_campaigns
        SET status = :s, paused_reason = :pr, updated_at = CURRENT_TIMESTAMP
        WHERE id = :id AND tenant_id = :t
    """), {"s": new_status, "pr": paused_reason, "id": campaign_id, "t": tenant_id})


# ---------------------------------------------------------------------------
# Campaign CRUD + lifecycle
# ---------------------------------------------------------------------------

async def create_campaign(db: AsyncSession, tenant_id: int, *, name: str,
                          store_id: int, item_id: int, starts_on: date,
                          ends_on: date, discount_budget_aed: Decimal,
                          max_discount_pct: Decimal, min_margin_pct: Decimal,
                          control_pct: Decimal, churn_threshold: float,
                          safety_stock_units: int, created_by: Optional[int],
                          objective: str = "churn_retention") -> Dict:
    row = (await db.execute(text("""
        INSERT INTO retention_campaigns
            (tenant_id, name, objective, store_id, item_id, starts_on, ends_on,
             discount_budget_aed, max_discount_pct, min_margin_pct, control_pct,
             churn_threshold, safety_stock_units, model_version, policy_version, created_by)
        VALUES (:t, :name, :obj, :store, :item, :s, :e, :budget, :maxd, :minm, :ctrl,
                :thr, :ss, :mv, :pv, :by)
        RETURNING id
    """), {"t": tenant_id, "name": name, "obj": objective, "store": store_id, "item": item_id,
           "s": starts_on, "e": ends_on, "budget": discount_budget_aed,
           "maxd": max_discount_pct, "minm": min_margin_pct, "ctrl": control_pct,
           "thr": churn_threshold, "ss": safety_stock_units,
           "mv": MODEL_VERSION, "pv": POLICY_VERSION, "by": created_by})).fetchone()
    await _log_event(db, tenant_id, "campaign_created", "campaign", row.id,
                     f"Campaign '{name}' drafted ({objective})", actor=created_by)
    await db.commit()
    return {"id": row.id, "status": "draft"}


async def list_campaigns(db: AsyncSession, tenant_id: int,
                         allowed_stores: List[int]) -> List[Dict]:
    where = ["c.tenant_id = :t"]
    params: Dict = {"t": tenant_id}
    if allowed_stores:
        where.append("c.store_id = ANY(:stores)")
        params["stores"] = allowed_stores
    rows = (await db.execute(text(f"""
        SELECT c.*, s.name AS store_name, i.name AS item_name,
               (SELECT COUNT(*) FROM campaign_offers o WHERE o.campaign_id = c.id) AS audience_size
        FROM retention_campaigns c
        JOIN stores s ON s.id = c.store_id
        JOIN items i ON i.id = c.item_id
        WHERE {' AND '.join(where)}
        ORDER BY c.created_at DESC
    """), params)).mappings().fetchall()
    return [dict(r) for r in rows]


async def get_campaign(db: AsyncSession, tenant_id: int, campaign_id: int) -> Dict:
    c = dict(await _get_campaign_row(db, tenant_id, campaign_id))
    stats = (await db.execute(text("""
        SELECT cohort, status, COUNT(*) AS n
        FROM campaign_offers WHERE campaign_id = :c AND tenant_id = :t
        GROUP BY cohort, status
    """), {"c": campaign_id, "t": tenant_id})).fetchall()
    c["offer_stats"] = [{"cohort": r.cohort, "status": r.status, "n": r.n} for r in stats]
    ledger = (await db.execute(text("""
        SELECT entry_type, amount_aed, balance_before_aed, balance_after_aed,
               source_type, reason, created_at
        FROM retention_budget_ledger
        WHERE campaign_id = :c AND tenant_id = :t
        ORDER BY id DESC LIMIT 50
    """), {"c": campaign_id, "t": tenant_id})).mappings().fetchall()
    c["ledger"] = [dict(r) for r in ledger]
    return c


# ---------------------------------------------------------------------------
# Audience: churn-score every consenting customer at the campaign store,
# keep those over threshold, split treatment/control deterministically.
# ---------------------------------------------------------------------------

FEATURE_SQL = """
    SELECT c.id AS customer_id, c.customer_ref, c.archetype, c.consent_marketing,
           c.contact_cap_month, c.contacts_this_month,
           (CURRENT_DATE - MAX(p.purchase_date)) AS recency_days,
           COUNT(*) FILTER (WHERE p.purchase_date >= CURRENT_DATE - 90) AS purchases_90d,
           COALESCE(AVG(p.amount_aed) FILTER (WHERE p.purchase_date >= CURRENT_DATE - 90), 0) AS avg_amount_90d,
           COALESCE(SUM(p.amount_aed) FILTER (WHERE p.purchase_date >= CURRENT_DATE - 30), 0) AS spend_30d,
           CASE WHEN COUNT(*) > 1
                THEN (MAX(p.purchase_date) - MIN(p.purchase_date))::float / (COUNT(*) - 1)
                ELSE 30 END AS avg_interval_days,
           AVG(CASE WHEN p.was_promo THEN 1.0 ELSE 0.0 END) AS promo_rate,
           AVG(CASE WHEN p.is_return THEN 1.0 ELSE 0.0 END) AS return_rate,
           COALESCE(SUM(p.amount_aed) FILTER (WHERE p.purchase_date >= CURRENT_DATE - 90), 0) / 3 AS monthly_value
    FROM customers c
    JOIN customer_purchases p ON p.customer_id = c.id AND p.tenant_id = c.tenant_id
    WHERE c.tenant_id = :t AND c.home_store_id = :store
    GROUP BY c.id
"""


async def build_audience(db: AsyncSession, tenant_id: int, campaign_id: int,
                         actor: Optional[int]) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id)
    _require_transition(camp["status"], "audience_ready")

    rows = (await db.execute(text(FEATURE_SQL),
                             {"t": tenant_id, "store": camp["store_id"]})).mappings().fetchall()
    await db.execute(text(
        "DELETE FROM campaign_offers WHERE campaign_id = :c AND tenant_id = :t"),
        {"c": campaign_id, "t": tenant_id})

    kept = 0
    for r in rows:
        if not r["consent_marketing"]:
            continue
        score, reasons = churn_score(dict(r))
        if score < float(camp["churn_threshold"]):
            continue
        cohort = assign_cohort(tenant_id, campaign_id, r["customer_id"],
                               float(camp["control_pct"]))
        await db.execute(text("""
            INSERT INTO campaign_offers
                (tenant_id, campaign_id, customer_id, store_id, cohort,
                 churn_score, reason_codes)
            VALUES (:t, :c, :cust, :store, :cohort, :score, CAST(:reasons AS jsonb))
        """), {"t": tenant_id, "c": campaign_id, "cust": r["customer_id"],
               "store": camp["store_id"], "cohort": cohort, "score": score,
               "reasons": json.dumps(reasons)})
        kept += 1

    await _set_status(db, tenant_id, campaign_id, "audience_ready")
    await _log_event(db, tenant_id, "audience_built", "campaign", campaign_id,
                     f"Audience built: {kept} at-risk customers of {len(rows)} scored",
                     actor=actor, metadata={"scored": len(rows), "kept": kept})
    await db.commit()
    return {"scored": len(rows), "audience_size": kept, "status": "audience_ready"}


# ---------------------------------------------------------------------------
# Simulation: optimizer + inventory ladder + financial projection.
# ---------------------------------------------------------------------------

async def _atp(db: AsyncSession, tenant_id: int, store_id: int, item_id: int,
               safety_stock: int, exclude_campaign: Optional[int] = None) -> int:
    """Available-to-promise = on-hand available - safety stock - other
    campaigns' live soft allocations."""
    row = (await db.execute(text("""
        SELECT COALESCE((SELECT available_stock FROM inventory
                         WHERE store_id = :s AND item_id = :i), 0) AS avail,
               COALESCE((SELECT SUM(allocated_units - consumed_units)
                         FROM campaign_allocations
                         WHERE tenant_id = :t AND store_id = :s AND item_id = :i
                           AND released_at IS NULL
                           AND (:excl IS NULL OR campaign_id <> :excl)), 0) AS allocated
    """), {"s": store_id, "i": item_id, "t": tenant_id,
           "excl": exclude_campaign})).fetchone()
    return max(0, int(row.avail) - int(row.allocated) - safety_stock)


async def simulate(db: AsyncSession, tenant_id: int, campaign_id: int,
                   actor: Optional[int]) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id)
    _require_transition(camp["status"], "simulated")

    item = (await db.execute(text("""
        SELECT id, name, category, unit_price_aed, unit_cost_aed
        FROM items WHERE id = :i AND tenant_id = :t
    """), {"i": camp["item_id"], "t": tenant_id})).mappings().fetchone()
    if not item:
        raise ValueError("Campaign item not found")
    price = Decimal(str(item["unit_price_aed"]))
    cost = Decimal(str(item["unit_cost_aed"])) if item["unit_cost_aed"] is not None else None

    features = {r["customer_id"]: r for r in (await db.execute(
        text(FEATURE_SQL), {"t": tenant_id, "store": camp["store_id"]})).mappings().fetchall()}
    offers = (await db.execute(text("""
        SELECT id, customer_id, cohort, churn_score FROM campaign_offers
        WHERE campaign_id = :c AND tenant_id = :t ORDER BY id
    """), {"c": campaign_id, "t": tenant_id})).mappings().fetchall()

    # 1. Optimize each treatment customer independently.
    decisions = []  # (offer_id, action, disc, resp, ev, reasons)
    for o in offers:
        if o["cohort"] == "control":
            decisions.append((o["id"], "NO_ACTION", Decimal("0"), 0.0,
                              Decimal("0.00"), ["control_cohort"]))
            continue
        f = features.get(o["customer_id"], {})
        action, disc, resp, ev, reasons = choose_action(
            churn=float(o["churn_score"]),
            promo_rate=float(f.get("promo_rate") or 0),
            price=price, cost=cost,
            monthly_value=Decimal(str(f.get("monthly_value") or 0)).quantize(CENT),
            max_discount_pct=Decimal(str(camp["max_discount_pct"])),
            min_margin_pct=Decimal(str(camp["min_margin_pct"])))
        decisions.append((o["id"], action, disc, resp, ev, reasons))

    # 2. Inventory ladder for the stock-bearing actions.
    needs_stock = [d for d in decisions if d[1] == "PERCENT_DISCOUNT"]
    atp = await _atp(db, tenant_id, camp["store_id"], camp["item_id"],
                     camp["safety_stock_units"], exclude_campaign=campaign_id)
    shortfall = max(0, len(needs_stock) - atp)
    substitute = None
    transfer_rec = None

    if shortfall > 0:
        # a) keep the highest-EV customers on the primary item (sort by EV desc)
        needs_stock.sort(key=lambda d: d[4], reverse=True)
        overflow = needs_stock[atp:]

        # b) in-stock substitute from the same category
        sub = (await db.execute(text("""
            SELECT i.id, i.name, i.unit_price_aed, i.unit_cost_aed, inv.available_stock
            FROM items i
            JOIN inventory inv ON inv.item_id = i.id AND inv.store_id = :s
            WHERE i.tenant_id = :t AND i.category = :cat AND i.id <> :i
              AND inv.available_stock - :ss >= :need
            ORDER BY inv.available_stock DESC LIMIT 1
        """), {"t": tenant_id, "s": camp["store_id"], "cat": item["category"],
               "i": camp["item_id"], "ss": camp["safety_stock_units"],
               "need": shortfall})).mappings().fetchone()
        if sub:
            substitute = {
                "item_id": sub["id"], "name": sub["name"],
                "available": sub["available_stock"],
                "price": Decimal(str(sub["unit_price_aed"])),
                "cost": (Decimal(str(sub["unit_cost_aed"]))
                         if sub["unit_cost_aed"] is not None else None)}
            for idx, d in enumerate(overflow):
                overflow[idx] = (d[0], "SUBSTITUTE_PRODUCT", d[2], d[3], d[4],
                                 d[5] + ["primary_item_shortage", "substitute_in_stock"])
        else:
            # c) inter-store transfer recommendation (recommend only — the
            #    inventory module owns actual stock_transfers)
            surplus = (await db.execute(text("""
                SELECT inv.store_id, s.name, inv.available_stock
                FROM inventory inv JOIN stores s ON s.id = inv.store_id
                WHERE inv.item_id = :i AND inv.store_id <> :store
                  AND s.tenant_id = :t
                  AND inv.available_stock - :ss >= :need
                ORDER BY inv.available_stock DESC LIMIT 1
            """), {"i": camp["item_id"], "store": camp["store_id"], "t": tenant_id,
                   "ss": camp["safety_stock_units"], "need": shortfall})).fetchone()
            if surplus:
                transfer_rec = {"from_store_id": surplus.store_id,
                                "from_store": surplus.name, "units": shortfall}
            # d/e) meanwhile the overflow customers get a non-inventory REMINDER
            for idx, d in enumerate(overflow):
                overflow[idx] = (d[0], "REMINDER", Decimal("0"),
                                 response_prob(0.5, 0, 0.3), Decimal("0.00"),
                                 d[5] + ["primary_item_shortage", "fallback_reminder"])
            # e) procurement is PROPOSED (not created) — the scenario pack below
            #    enumerates buy/transfer/substitute/delay options. A draft PO is
            #    created only at approval (approve()), never during simulation.
            #    (master prompt §3/§11.G/§26: no side effects, never auto-buy.)

        decisions = [d for d in decisions if d[1] != "PERCENT_DISCOUNT"] \
            + needs_stock[:atp] + overflow

    # 3. Persist per-offer decisions (price/cost snapshots for reproducibility;
    #    substitutes snapshot the substitute item's own price/cost).
    for offer_id, action, disc, resp, ev, reasons in decisions:
        is_sub = action == "SUBSTITUTE_PRODUCT" and substitute
        await db.execute(text("""
            UPDATE campaign_offers
            SET action = :a, discount_pct = :d, response_prob = :r,
                expected_value_aed = :ev, unit_price_aed = :price,
                unit_cost_aed = :cost, item_id = :item,
                reason_codes = CAST(:reasons AS jsonb),
                status = CASE WHEN :a = 'NO_ACTION' AND cohort = 'treatment'
                              THEN 'suppressed' ELSE status END
            WHERE id = :id AND tenant_id = :t
        """), {"a": action, "d": disc, "r": resp, "ev": ev,
               "price": substitute["price"] if is_sub else price,
               "cost": substitute["cost"] if is_sub else cost,
               "item": substitute["item_id"] if is_sub else camp["item_id"],
               "reasons": json.dumps(reasons), "id": offer_id, "t": tenant_id})

    # 4. Financial projection.
    treated = [d for d in decisions if d[1] in ("PERCENT_DISCOUNT", "SUBSTITUTE_PRODUCT")]
    exp_redemptions = sum(d[3] for d in treated)
    exp_discount = sum((Decimal(str(d[3])) * price * d[2] / Decimal(100) for d in treated),
                       Decimal("0")).quantize(CENT)
    exp_ev = sum((d[4] for d in decisions), Decimal("0")).quantize(CENT)
    sim = {
        "audience": len(offers),
        "control": sum(1 for d in decisions if d[5] and d[5][0] == "control_cohort"),
        "treated_offers": len(treated),
        "reminders": sum(1 for d in decisions if d[1] == "REMINDER"),
        "suppressed": sum(1 for d in decisions if d[1] == "NO_ACTION"
                          and "control_cohort" not in d[5]),
        "expected_redemptions": round(exp_redemptions, 1),
        "expected_discount_spend_aed": str(exp_discount),
        "expected_incremental_value_aed": str(exp_ev),
        "budget_sufficient": exp_discount <= Decimal(str(camp["discount_budget_aed"])),
        "atp_units": atp,
        "shortfall_units": shortfall,
        "substitute": ({"item_id": substitute["item_id"], "name": substitute["name"],
                        "available": substitute["available"],
                        "price_aed": str(substitute["price"]),
                        "cost_aed": str(substitute["cost"]) if substitute["cost"] is not None else None}
                       if substitute else None),
        "transfer_recommendation": transfer_rec,
        "price_snapshot_aed": str(price),
        "cost_snapshot_aed": str(cost) if cost is not None else None,
        "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "synthetic_data": True,
        "simulated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Attach the full commercial decision pack (baseline, low/exp/high scenarios,
    # category effects, inventory/shelf-life, procurement OPTIONS, finance,
    # recommendation, department views). Pure read+compute — no side effects.
    from app.services.campaign_scenario import run_scenario
    sim["scenario_pack"] = await run_scenario(db, tenant_id, dict(camp), actor, persist=False)
    await db.execute(text("""
        UPDATE retention_campaigns SET simulation = CAST(:sim AS jsonb),
               status = 'simulated', updated_at = CURRENT_TIMESTAMP
        WHERE id = :id AND tenant_id = :t
    """), {"sim": json.dumps(sim, default=str), "id": campaign_id, "t": tenant_id})
    await _log_event(db, tenant_id, "campaign_simulated", "campaign", campaign_id,
                     f"Simulated: {len(treated)} offers, expected spend AED {exp_discount}",
                     actor=actor, metadata=sim)
    await db.commit()
    return sim


# Draft-PO creation from a campaign shortfall lived here; it moved out of the
# simulation path (simulation must have no side effects). Procurement is now
# PROPOSED by campaign_scenario.procurement_options and only committed to a real
# draft PO at approval time — implemented in Phase 2. The retention_campaigns
# .requisition_po_id column is reserved for that link.


# ---------------------------------------------------------------------------
# Submit / approve / activate / pause / cancel
# ---------------------------------------------------------------------------

async def submit(db: AsyncSession, tenant_id: int, campaign_id: int,
                 actor: Optional[int]) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id)
    _require_transition(camp["status"], "pending_approval")
    await _set_status(db, tenant_id, campaign_id, "pending_approval")
    await _log_event(db, tenant_id, "campaign_submitted", "campaign", campaign_id,
                     "Submitted for approval", actor=actor)
    # Reuse the tenant's existing approval threshold (migration 019): small
    # campaigns auto-approve exactly like small POs do.
    rule = (await db.execute(text(
        "SELECT auto_approve_under FROM approval_rules WHERE tenant_id = :t"),
        {"t": tenant_id})).fetchone()
    threshold = Decimal(str(rule.auto_approve_under)) if rule else Decimal("0")
    if threshold > 0 and Decimal(str(camp["discount_budget_aed"])) <= threshold:
        await db.commit()
        return await approve(db, tenant_id, campaign_id, actor=None,
                             auto=True)
    await db.commit()
    return {"status": "pending_approval", "auto_approved": False}


async def approve(db: AsyncSession, tenant_id: int, campaign_id: int,
                  actor: Optional[int], auto: bool = False) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id, lock=True)
    _require_transition(camp["status"], "approved")
    budget = Decimal(str(camp["discount_budget_aed"]))

    # Reserve the expected discount exposure (capped at the approved budget).
    sim = camp["simulation"] or {}
    exposure = min(budget, Decimal(str(sim.get("expected_discount_spend_aed", "0"))))
    remaining_before = budget - Decimal(str(camp["budget_spent_aed"]))
    await db.execute(text("""
        UPDATE retention_campaigns
        SET status = 'approved', budget_reserved_aed = :r,
            approved_by = :by, approved_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id AND tenant_id = :t
    """), {"r": exposure, "by": actor, "id": campaign_id, "t": tenant_id})
    await db.execute(text("""
        INSERT INTO retention_budget_ledger
            (tenant_id, campaign_id, entry_type, amount_aed, balance_before_aed,
             balance_after_aed, source_type, source_id, actor_user_id, reason)
        VALUES (:t, :c, 'reserve', :amt, :b0, :b1, 'campaign', :c, :actor, :reason)
    """), {"t": tenant_id, "c": campaign_id, "amt": exposure,
           "b0": remaining_before, "b1": remaining_before, "actor": actor,
           "reason": "auto-approved under threshold" if auto else "approved"})

    # Soft inventory allocation for the treated offers on the primary item.
    treated = (await db.execute(text("""
        SELECT item_id, COUNT(*) AS n FROM campaign_offers
        WHERE campaign_id = :c AND tenant_id = :t
          AND action IN ('PERCENT_DISCOUNT', 'SUBSTITUTE_PRODUCT')
        GROUP BY item_id
    """), {"c": campaign_id, "t": tenant_id})).fetchall()
    for row in treated:
        await db.execute(text("""
            INSERT INTO campaign_allocations
                (tenant_id, campaign_id, store_id, item_id, allocated_units)
            VALUES (:t, :c, :s, :i, :n)
            ON CONFLICT (campaign_id, store_id, item_id)
            DO UPDATE SET allocated_units = EXCLUDED.allocated_units, released_at = NULL
        """), {"t": tenant_id, "c": campaign_id, "s": camp["store_id"],
               "i": row.item_id, "n": row.n})

    await _log_event(db, tenant_id, "campaign_approved", "campaign", campaign_id,
                     f"Approved ({'auto' if auto else 'manual'}); reserved AED {exposure}",
                     actor=actor, metadata={"reserved_aed": str(exposure)})
    await db.commit()
    return {"status": "approved", "reserved_aed": str(exposure), "auto_approved": auto}


async def activate(db: AsyncSession, tenant_id: int, campaign_id: int,
                   actor: Optional[int]) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id)
    _require_transition(camp["status"], "active")

    # Issue offers to treated customers under their contact-frequency cap.
    issued = (await db.execute(text("""
        UPDATE campaign_offers o
        SET status = 'issued', issued_at = CURRENT_TIMESTAMP,
            expires_at = (CAST(:ends AS date) + 1)::timestamptz
        FROM customers cu
        WHERE o.campaign_id = :c AND o.tenant_id = :t AND cu.id = o.customer_id
          AND o.cohort = 'treatment' AND o.action <> 'NO_ACTION'
          AND o.status = 'planned'
          AND cu.consent_marketing
          AND cu.contacts_this_month < LEAST(cu.contact_cap_month, :cap)
        RETURNING o.id, o.customer_id
    """), {"c": campaign_id, "t": tenant_id, "ends": camp["ends_on"],
           "cap": camp["contact_cap_month"]})).fetchall()
    if issued:
        await db.execute(text("""
            UPDATE customers SET contacts_this_month = contacts_this_month + 1
            WHERE tenant_id = :t AND id = ANY(:ids)
        """), {"t": tenant_id, "ids": [r.customer_id for r in issued]})
    # Anyone over their cap is suppressed, with the reason on the record.
    await db.execute(text("""
        UPDATE campaign_offers o
        SET status = 'suppressed',
            reason_codes = o.reason_codes || '["contact_frequency_cap"]'::jsonb
        FROM customers cu
        WHERE o.campaign_id = :c AND o.tenant_id = :t AND cu.id = o.customer_id
          AND o.status = 'planned' AND o.cohort = 'treatment' AND o.action <> 'NO_ACTION'
    """), {"c": campaign_id, "t": tenant_id})

    await _set_status(db, tenant_id, campaign_id, "active")
    await _log_event(db, tenant_id, "campaign_activated", "campaign", campaign_id,
                     f"Activated; {len(issued)} offers issued", actor=actor)
    await db.commit()
    await _notify({"type": "retention", "severity": "info",
                   "title": f"Campaign '{camp['name']}' activated",
                   "message": f"{len(issued)} retention offers issued",
                   "campaign_id": campaign_id, "tenant_id": tenant_id})
    return {"status": "active", "offers_issued": len(issued)}


async def set_lifecycle(db: AsyncSession, tenant_id: int, campaign_id: int,
                        new_status: str, actor: Optional[int],
                        reason: Optional[str] = None) -> Dict:
    """pause / resume(active) / complete / cancel — with release on cancel/complete."""
    camp = await _get_campaign_row(db, tenant_id, campaign_id, lock=True)
    _require_transition(camp["status"], new_status)
    await _set_status(db, tenant_id, campaign_id, new_status,
                      paused_reason=reason if new_status == "paused" else None)

    if new_status in ("cancelled", "completed"):
        # Release unspent reservation + soft allocations, expire open offers.
        remaining = Decimal(str(camp["budget_reserved_aed"])) - Decimal(str(camp["budget_spent_aed"]))
        remaining = max(remaining, Decimal("0"))
        budget_left = Decimal(str(camp["discount_budget_aed"])) - Decimal(str(camp["budget_spent_aed"]))
        await db.execute(text("""
            UPDATE retention_campaigns SET budget_reserved_aed = 0 WHERE id = :c AND tenant_id = :t
        """), {"c": campaign_id, "t": tenant_id})
        if remaining > 0:
            await db.execute(text("""
                INSERT INTO retention_budget_ledger
                    (tenant_id, campaign_id, entry_type, amount_aed, balance_before_aed,
                     balance_after_aed, source_type, source_id, actor_user_id, reason)
                VALUES (:t, :c, 'release', :amt, :b, :b, 'campaign', :c, :actor, :r)
            """), {"t": tenant_id, "c": campaign_id, "amt": remaining,
                   "b": budget_left, "actor": actor, "r": f"campaign {new_status}"})
        await db.execute(text("""
            UPDATE campaign_allocations SET released_at = CURRENT_TIMESTAMP
            WHERE campaign_id = :c AND tenant_id = :t AND released_at IS NULL
        """), {"c": campaign_id, "t": tenant_id})
        await db.execute(text("""
            UPDATE campaign_offers SET status = 'expired'
            WHERE campaign_id = :c AND tenant_id = :t AND status = 'issued'
        """), {"c": campaign_id, "t": tenant_id})

    await _log_event(db, tenant_id, f"campaign_{new_status}", "campaign", campaign_id,
                     f"Campaign {new_status}" + (f": {reason}" if reason else ""),
                     actor=actor)
    await db.commit()
    if new_status == "paused":
        await _notify({"type": "retention", "severity": "warning",
                       "title": f"Campaign '{camp['name']}' paused",
                       "message": reason or "paused", "campaign_id": campaign_id,
                       "tenant_id": tenant_id})
    return {"status": new_status, "reason": reason}


# ---------------------------------------------------------------------------
# Real-time decision + atomic idempotent redemption
# ---------------------------------------------------------------------------

async def evaluate(db: AsyncSession, tenant_id: int, customer_id: int,
                   store_id: int) -> Dict:
    """Next-best action for a customer interaction. Every guard that fails
    returns NO_ACTION with the reason — never an error the till has to handle."""
    no_action = lambda *reasons: {  # noqa: E731 - tiny local ctor
        "action": "NO_ACTION", "reason_codes": list(reasons),
        "model_version": MODEL_VERSION, "policy_version": POLICY_VERSION}

    row = (await db.execute(text("""
        SELECT o.id AS offer_id, o.action, o.discount_pct, o.item_id, o.cohort,
               o.status, o.expires_at, o.unit_price_aed, o.reason_codes,
               c.id AS campaign_id, c.status AS campaign_status,
               c.discount_budget_aed, c.budget_spent_aed, c.safety_stock_units,
               cu.consent_marketing, i.name AS item_name
        FROM campaign_offers o
        JOIN retention_campaigns c ON c.id = o.campaign_id
        JOIN customers cu ON cu.id = o.customer_id
        LEFT JOIN items i ON i.id = o.item_id
        WHERE o.tenant_id = :t AND o.customer_id = :cust AND c.status = 'active'
        ORDER BY o.expected_value_aed DESC LIMIT 1
    """), {"t": tenant_id, "cust": customer_id})).mappings().fetchone()

    if not row:
        return no_action("no_active_campaign_offer")
    if row["cohort"] == "control":
        return no_action("control_cohort")
    if not row["consent_marketing"]:
        return no_action("consent_missing")
    if row["status"] != "issued":
        return no_action(f"offer_{row['status']}")
    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
        return no_action("offer_expired")
    remaining = Decimal(str(row["discount_budget_aed"])) - Decimal(str(row["budget_spent_aed"]))
    if remaining <= 0:
        return no_action("budget_exhausted")
    if row["action"] in ("PERCENT_DISCOUNT", "SUBSTITUTE_PRODUCT"):
        atp = await _atp(db, tenant_id, store_id, row["item_id"],
                         row["safety_stock_units"])
        if atp <= 0:
            return no_action("inventory_at_safety_stock")

    price = Decimal(str(row["unit_price_aed"] or 0))
    disc = Decimal(str(row["discount_pct"]))
    return {
        "decision_id": row["offer_id"],
        "action": row["action"],
        "campaign_id": row["campaign_id"],
        "item_id": row["item_id"],
        "item_name": row["item_name"],
        "unit_price_aed": str(price),
        "discount_pct": str(disc),
        "discounted_price_aed": str((price * (1 - disc / 100)).quantize(CENT)),
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "reason_codes": row["reason_codes"],
        "message_key": f"retention.offer.{row['action'].lower()}",
        "budget_status": "ok",
        "inventory_status": "ok",
        "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
    }


async def redeem(db: AsyncSession, tenant_id: int, offer_id: int,
                 idempotency_key: str, actor: Optional[int]) -> Dict:
    """Atomic redemption. One transaction: lock offer + campaign + inventory,
    guarded budget + stock updates (can never go negative / over budget),
    ledgers, audit. A replay with the same idempotency key returns the stored
    result without touching money or stock again."""
    # Idempotent replay: the key was already consumed.
    prior = (await db.execute(text("""
        SELECT id, redemption_amount_aed, redeemed_at FROM campaign_offers
        WHERE tenant_id = :t AND redemption_key = :k
    """), {"t": tenant_id, "k": idempotency_key})).fetchone()
    if prior:
        return {"offer_id": prior.id, "status": "redeemed", "replay": True,
                "amount_aed": str(prior.redemption_amount_aed),
                "redeemed_at": prior.redeemed_at.isoformat() if prior.redeemed_at else None}

    offer = (await db.execute(text("""
        SELECT * FROM campaign_offers
        WHERE id = :id AND tenant_id = :t FOR UPDATE
    """), {"id": offer_id, "t": tenant_id})).mappings().fetchone()
    if not offer:
        raise ValueError("Offer not found")
    if offer["status"] == "redeemed":
        raise ValueError("Offer already redeemed")
    if offer["status"] != "issued":
        raise ValueError(f"Offer is {offer['status']}, not redeemable")
    if offer["expires_at"] and offer["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("Offer expired")

    camp = await _get_campaign_row(db, tenant_id, offer["campaign_id"], lock=True)
    if camp["status"] != "active":
        raise ValueError(f"Campaign is {camp['status']}, not active")

    price = Decimal(str(offer["unit_price_aed"]))
    disc = Decimal(str(offer["discount_pct"]))
    cost = Decimal(str(offer["unit_cost_aed"])) if offer["unit_cost_aed"] is not None else None
    discount_amount = (price * disc / Decimal(100)).quantize(CENT, ROUND_HALF_UP)

    # Final margin validation against the stored snapshot.
    if cost is not None:
        margin_pct = (price * (1 - disc / 100) - cost) / price * Decimal(100)
        if margin_pct < Decimal(str(camp["min_margin_pct"])):
            raise ValueError("Final price violates the margin floor")

    # Budget guard: the UPDATE only succeeds while spend stays within budget.
    spent = (await db.execute(text("""
        UPDATE retention_campaigns
        SET budget_spent_aed = budget_spent_aed + :amt, updated_at = CURRENT_TIMESTAMP
        WHERE id = :c AND tenant_id = :t
          AND budget_spent_aed + :amt <= discount_budget_aed
        RETURNING budget_spent_aed, discount_budget_aed
    """), {"amt": discount_amount, "c": camp["id"], "t": tenant_id})).fetchone()
    if not spent:
        await _set_status(db, tenant_id, camp["id"], "paused",
                          "guardrail: discount budget exhausted")
        await _log_event(db, tenant_id, "campaign_auto_paused", "campaign", camp["id"],
                         "Auto-paused: budget exhausted")
        await db.commit()
        await _notify({"type": "retention", "severity": "critical",
                       "title": f"Campaign '{camp['name']}' auto-paused",
                       "message": "Discount budget exhausted", "tenant_id": tenant_id,
                       "campaign_id": camp["id"]})
        raise ValueError("Budget exhausted — campaign paused")

    # Inventory guard for stock-bearing actions: lock + conditional decrement.
    stock_after = None
    if offer["action"] in ("PERCENT_DISCOUNT", "SUBSTITUTE_PRODUCT"):
        inv = (await db.execute(text("""
            UPDATE inventory SET current_stock = current_stock - 1,
                   updated_at = CURRENT_TIMESTAMP
            WHERE store_id = :s AND item_id = :i AND current_stock >= 1
            RETURNING id, current_stock
        """), {"s": offer["store_id"], "i": offer["item_id"]})).fetchone()
        if not inv:
            # No negative inventory, ever. Roll back the budget spend with the
            # transaction by raising before commit.
            raise ValueError("Insufficient stock for redemption")
        stock_after = inv.current_stock
        await db.execute(text("""
            INSERT INTO inventory_transactions
                (inventory_id, store_id, item_id, transaction_type, quantity,
                 stock_before, stock_after, reference_type, reference_id,
                 performed_by, notes)
            VALUES (:inv, :s, :i, 'sale', -1, :b, :a, 'retention_redemption',
                    :ref, :by, 'Retention offer redemption')
        """), {"inv": inv.id, "s": offer["store_id"], "i": offer["item_id"],
               "b": stock_after + 1, "a": stock_after, "ref": str(offer_id),
               "by": actor})
        await db.execute(text("""
            UPDATE campaign_allocations
            SET consumed_units = consumed_units + 1
            WHERE campaign_id = :c AND tenant_id = :t AND store_id = :s
              AND item_id = :i AND consumed_units < allocated_units
        """), {"c": camp["id"], "t": tenant_id, "s": offer["store_id"],
               "i": offer["item_id"]})

    remaining_after = Decimal(str(spent.discount_budget_aed)) - Decimal(str(spent.budget_spent_aed))
    await db.execute(text("""
        UPDATE campaign_offers
        SET status = 'redeemed', redeemed_at = CURRENT_TIMESTAMP,
            redemption_key = :k, redemption_amount_aed = :amt
        WHERE id = :id AND tenant_id = :t
    """), {"k": idempotency_key, "amt": discount_amount, "id": offer_id, "t": tenant_id})
    await db.execute(text("""
        INSERT INTO retention_budget_ledger
            (tenant_id, campaign_id, entry_type, amount_aed, balance_before_aed,
             balance_after_aed, source_type, source_id, idempotency_key,
             actor_user_id, reason)
        VALUES (:t, :c, 'spend', :amt, :b0, :b1, 'redemption', :o, :k, :actor,
                'offer redeemed')
    """), {"t": tenant_id, "c": camp["id"], "amt": discount_amount,
           "b0": remaining_after + discount_amount, "b1": remaining_after,
           "o": offer_id, "k": idempotency_key, "actor": actor})
    await _log_event(db, tenant_id, "offer_redeemed", "offer", offer_id,
                     f"Redeemed for AED {discount_amount} discount", actor=actor,
                     metadata={"campaign_id": camp["id"], "stock_after": stock_after,
                               "budget_remaining_aed": str(remaining_after)})

    # Guardrails: pause when budget or stock hits the floor (inside the txn so
    # the pause is durable with the redemption).
    paused_reason = None
    if remaining_after <= 0:
        paused_reason = "guardrail: discount budget exhausted"
    elif stock_after is not None and stock_after <= camp["safety_stock_units"]:
        paused_reason = "guardrail: inventory reached safety stock"
    if paused_reason:
        await _set_status(db, tenant_id, camp["id"], "paused", paused_reason)
        await _log_event(db, tenant_id, "campaign_auto_paused", "campaign",
                         camp["id"], f"Auto-paused: {paused_reason}")

    await db.commit()
    await _notify({"type": "retention", "severity": "info",
                   "title": "Offer redeemed",
                   "message": f"AED {discount_amount} discount honoured "
                              f"(campaign #{camp['id']})",
                   "tenant_id": tenant_id, "campaign_id": camp["id"]})
    if paused_reason:
        await _notify({"type": "retention", "severity": "critical",
                       "title": f"Campaign '{camp['name']}' auto-paused",
                       "message": paused_reason, "tenant_id": tenant_id,
                       "campaign_id": camp["id"]})
    return {"offer_id": offer_id, "status": "redeemed", "replay": False,
            "amount_aed": str(discount_amount),
            "budget_remaining_aed": str(remaining_after),
            "stock_after": stock_after, "auto_paused": paused_reason}


# ---------------------------------------------------------------------------
# Measurement (treatment vs control) + decision trace + model card
# ---------------------------------------------------------------------------

async def outcomes(db: AsyncSession, tenant_id: int, campaign_id: int) -> Dict:
    camp = await _get_campaign_row(db, tenant_id, campaign_id)
    rows = (await db.execute(text("""
        SELECT o.cohort,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE o.status = 'redeemed') AS redeemed,
               COUNT(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM customer_purchases p
                   WHERE p.customer_id = o.customer_id AND p.tenant_id = o.tenant_id
                     AND p.purchase_date >= :starts)) AS purchased,
               COALESCE(SUM(o.redemption_amount_aed), 0) AS discount_spend
        FROM campaign_offers o
        WHERE o.campaign_id = :c AND o.tenant_id = :t
        GROUP BY o.cohort
    """), {"c": campaign_id, "t": tenant_id, "starts": camp["starts_on"]})).mappings().fetchall()
    by = {r["cohort"]: r for r in rows}
    t, c = by.get("treatment"), by.get("control")
    t_rate = (t["purchased"] / t["n"]) if t and t["n"] else 0.0
    c_rate = (c["purchased"] / c["n"]) if c and c["n"] else 0.0
    result = {
        "treatment": {"n": t["n"] if t else 0, "purchase_rate": round(t_rate, 3),
                      "redemptions": t["redeemed"] if t else 0,
                      "discount_spend_aed": str(t["discount_spend"] if t else 0)},
        "control": {"n": c["n"] if c else 0, "purchase_rate": round(c_rate, 3)},
        "incremental_purchase_rate": round(t_rate - c_rate, 3),
        "budget": {"approved_aed": str(camp["discount_budget_aed"]),
                   "spent_aed": str(camp["budget_spent_aed"]),
                   "reserved_aed": str(camp["budget_reserved_aed"])},
        # Honesty: randomized split, but synthetic data and tiny n — this is a
        # demonstration of the measurement mechanics, not a causal claim.
        "caveats": ["synthetic_data", "small_sample",
                    "randomized_split_but_demo_scale"],
    }
    if camp["status"] == "completed":
        sim = camp["simulation"] or {}
        sim["outcomes"] = result
        await db.execute(text("""
            UPDATE retention_campaigns SET simulation = CAST(:sim AS jsonb),
                   status = 'measured', updated_at = CURRENT_TIMESTAMP
            WHERE id = :c AND tenant_id = :t
        """), {"sim": json.dumps(sim, default=str), "c": campaign_id, "t": tenant_id})
        await _log_event(db, tenant_id, "campaign_measured", "campaign", campaign_id,
                         "Outcomes measured and persisted")
        await db.commit()
        result["status"] = "measured"
    return result


async def list_offers(db: AsyncSession, tenant_id: int, campaign_id: int,
                      limit: int = 200) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT o.id, o.customer_id, cu.customer_ref, cu.archetype, o.cohort,
               o.churn_score, o.response_prob, o.action, o.discount_pct,
               o.unit_price_aed, o.unit_cost_aed, o.expected_value_aed,
               o.reason_codes, o.status, o.expires_at, o.redeemed_at,
               i.name AS item_name
        FROM campaign_offers o
        JOIN customers cu ON cu.id = o.customer_id
        LEFT JOIN items i ON i.id = o.item_id
        WHERE o.campaign_id = :c AND o.tenant_id = :t
        ORDER BY o.expected_value_aed DESC, o.id
        LIMIT :lim
    """), {"c": campaign_id, "t": tenant_id, "lim": max(1, min(limit, 500))})).mappings().fetchall()
    return [dict(r) for r in rows]


async def list_customers(db: AsyncSession, tenant_id: int,
                         allowed_stores: List[int], limit: int = 200) -> List[Dict]:
    where = "AND c.home_store_id = ANY(:stores)" if allowed_stores else ""
    params: Dict = {"t": tenant_id, "lim": max(1, min(limit, 500))}
    if allowed_stores:
        params["stores"] = allowed_stores
    rows = (await db.execute(text(f"""
        SELECT c.id, c.customer_ref, c.archetype, c.home_store_id,
               c.consent_marketing, c.contact_cap_month, c.contacts_this_month,
               c.is_synthetic,
               (CURRENT_DATE - MAX(p.purchase_date)) AS recency_days,
               COUNT(p.id) FILTER (WHERE p.purchase_date >= CURRENT_DATE - 90) AS purchases_90d,
           CASE WHEN COUNT(p.id) > 1
                THEN (MAX(p.purchase_date) - MIN(p.purchase_date))::float / (COUNT(p.id) - 1)
                ELSE 30 END AS avg_interval_days,
           COALESCE(AVG(CASE WHEN p.was_promo THEN 1.0 ELSE 0.0 END), 0) AS promo_rate,
           COALESCE(AVG(CASE WHEN p.is_return THEN 1.0 ELSE 0.0 END), 0) AS return_rate
        FROM customers c
        LEFT JOIN customer_purchases p ON p.customer_id = c.id AND p.tenant_id = c.tenant_id
        WHERE c.tenant_id = :t {where}
        GROUP BY c.id ORDER BY c.id LIMIT :lim
    """), params)).mappings().fetchall()
    out = []
    for r in rows:
        d = dict(r)
        score, reasons = churn_score(d)
        d["churn_score"], d["churn_reasons"] = score, reasons
        out.append(d)
    return out


def model_card() -> Dict:
    """Honest model metadata — this is a documented heuristic, not a trained
    artifact. No production-accuracy claims from synthetic data."""
    return {
        "model_version": MODEL_VERSION,
        "type": "deterministic_heuristic (calibrated-logistic form, fixed coefficients)",
        "label_definition": "churn = no purchase within 45 days after scoring date, "
                            "for customers active in the prior 90 days",
        "features": ["recency_days", "purchases_90d", "avg_interval_days (own-rhythm deviation)",
                     "promo_rate (discount dependency)", "return_rate"],
        "excluded_features": "no demographic or otherwise sensitive attributes",
        "trained_artifact": None,
        "metrics": {
            "note": "No trained model yet — heuristic baseline. PR-AUC / ROC-AUC / "
                    "Brier reporting activates when a trained artifact replaces it. "
                    "All data is synthetic; no production accuracy is claimed.",
        },
        "policy_version": POLICY_VERSION,
        "synthetic_data": True,
    }
