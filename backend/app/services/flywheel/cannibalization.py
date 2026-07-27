"""Cannibalization — did the promotion create demand, or just move it?

THE QUESTION A SUPPLIER ACTUALLY ASKS. "You promoted my yoghurt and it sold 400
more units. But did the category grow by 400, or did 300 of those come from my
OTHER yoghurt on the next shelf?" A supplier pays for NEW demand, not for volume
shuffled between their own SKUs. Getting this wrong is not a rounding error — it
is charging a counterparty for a benefit that did not exist, and it is the first
thing a competent trade-marketing auditor checks.

For retention this is a refinement (Horizon 4). For supplier-funded trade
promotion it is on the critical path, which is why it was pulled forward — the
20 Jul 2026 parallel-markets ruling made the settlement depend on it.

THE METHOD — DIFFERENCE-IN-DIFFERENCES ON CATEGORY TOTALS. The plan chose DiD
over a hierarchical Bayesian model deliberately: DiD is robust, explainable to a
supplier in one sentence, and works at the data volume that exists today. The
Bayesian model is the documented upgrade path when there is enough history.

The two differences:

  1. PROMOTED-SKU lift  = treated arm's per-customer promoted-SKU purchase rate
                          MINUS control arm's rate.
  2. CATEGORY lift      = treated arm's per-customer WHOLE-CATEGORY rate
                          MINUS control arm's rate.

If the promoted SKU rose more than its category did, the gap is volume the SKU
took from other products in the same category:

     cannibalized_per_customer = max(0, promoted_lift - category_lift)

Scaled by the treated arm size, that is the cannibalised volume; the category
lift (not the promoted lift) is the honest incremental basis a supplier is
charged on. The cannibalization RATE is cannibalised / promoted_lift: 0 means
every extra unit was genuinely new, 1 means the promotion only moved volume.

HONESTY UNDER SMALL SAMPLES. A control arm under 30 makes this directional, not
decisive, and `is_reliable` says so — a supplier is never charged on a number
the retailer would not defend in a dispute.

THE GOVERNING RULE HOLDS. No model here; this is deterministic arithmetic over
recorded purchase events, and its output only ADJUSTS DOWN what a supplier can be
charged. It can never invent margin.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: Below this control-arm size the estimate is flagged directional.
RELIABLE_CONTROL_MIN = 30


async def estimate(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    window_days: int = 60, persist: bool = True,
) -> Dict[str, Any]:
    """Estimate cannibalization for a campaign's promoted SKUs.

    Returns one result per promoted SKU (its category lift, cannibalised volume,
    net incremental margin) plus the pairwise substitution within each category.
    """
    campaign = (await db.execute(
        text("""SELECT starts_on, ends_on FROM flywheel_campaigns
                 WHERE tenant_id = :t AND id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    if not campaign:
        raise ValueError(f"campaign {campaign_id} not found")
    starts_on = campaign[0]
    window_end = min(date.today() + timedelta(days=1),
                     starts_on + timedelta(days=window_days))

    # Arm sizes.
    arms = {r[0]: int(r[1]) for r in (await db.execute(
        text("""SELECT assignment, COUNT(DISTINCT customer_id)
                  FROM flywheel_campaign_audience
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND assignment IN ('treatment','control')
                 GROUP BY assignment"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()}
    n_t, n_c = arms.get("treatment", 0), arms.get("control", 0)

    # The promoted SKUs: items this campaign issued offers on. Falls back to the
    # funded SKUs if no offers exist yet.
    promoted = [int(r[0]) for r in (await db.execute(
        text("""SELECT DISTINCT item_id FROM flywheel_offers
                 WHERE tenant_id = :t AND campaign_id = :c AND item_id IS NOT NULL"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()]
    if not promoted:
        promoted = [int(r[0]) for r in (await db.execute(
            text("""SELECT DISTINCT s.item_id
                      FROM flywheel_supplier_funding_skus s
                      JOIN flywheel_supplier_funding f ON f.id = s.funding_id
                     WHERE s.tenant_id = :t AND f.campaign_id = :c"""),
            {"t": tenant_id, "c": campaign_id},
        )).fetchall()]

    if not promoted or n_t == 0 or n_c == 0:
        return {"campaign_id": campaign_id, "results": [], "substitution": [],
                "reason": ("cannot estimate: need a promoted SKU and both arms "
                           f"(promoted={len(promoted)}, treatment={n_t}, control={n_c})")}

    results: List[Dict[str, Any]] = []
    substitution: List[Dict[str, Any]] = []

    for item_id in promoted:
        category = (await db.execute(
            text("SELECT category FROM items WHERE id = :i AND tenant_id = :t"),
            {"i": item_id, "t": tenant_id},
        )).scalar()
        if category is None:
            continue

        # Per-arm purchase units for the promoted SKU and for the whole category,
        # over the measurement window. One pass, joined to the audience arm.
        row = (await db.execute(
            text("""SELECT a.assignment,
                           COALESCE(SUM(e.quantity_units) FILTER (WHERE e.item_id = :item), 0) AS sku_units,
                           COALESCE(SUM(e.quantity_units) FILTER (WHERE e.category = :cat), 0) AS cat_units,
                           COALESCE(SUM(e.margin_aed) FILTER (WHERE e.category = :cat), 0) AS cat_margin
                      FROM flywheel_campaign_audience a
                      LEFT JOIN flywheel_customer_events e
                        ON e.customer_id = a.customer_id AND e.tenant_id = a.tenant_id
                       AND e.event_type = 'purchase'
                       AND e.occurred_at >= :start AND e.occurred_at < :end
                     WHERE a.campaign_id = :c AND a.tenant_id = :t
                       AND a.assignment IN ('treatment','control')
                     GROUP BY a.assignment"""),
            {"item": item_id, "cat": category, "c": campaign_id, "t": tenant_id,
             "start": starts_on, "end": window_end},
        )).fetchall()

        by_arm = {r[0]: {"sku": int(r[1]), "cat": int(r[2]), "cat_margin": money(r[3])}
                  for r in row}
        t = by_arm.get("treatment", {"sku": 0, "cat": 0, "cat_margin": ZERO})
        c = by_arm.get("control", {"sku": 0, "cat": 0, "cat_margin": ZERO})

        # Per-customer rates (the DiD normalisation).
        sku_rate_t = t["sku"] / n_t
        sku_rate_c = c["sku"] / n_c
        cat_rate_t = t["cat"] / n_t
        cat_rate_c = c["cat"] / n_c

        promoted_lift_pc = sku_rate_t - sku_rate_c
        category_lift_pc = cat_rate_t - cat_rate_c

        promoted_lift_units = round(promoted_lift_pc * n_t)
        category_net_lift_units = round(category_lift_pc * n_t)
        cannibalized_units = max(0, promoted_lift_units - category_net_lift_units)
        cannib_rate = (Decimal(cannibalized_units) / Decimal(promoted_lift_units)
                       if promoted_lift_units > 0 else None)

        # The honest incremental margin: category-net per-customer margin lift,
        # scaled by the treated arm. Uses the control arm's category margin rate
        # as the counterfactual.
        cat_margin_rate_t = t["cat_margin"] / Decimal(n_t) if n_t else ZERO
        cat_margin_rate_c = c["cat_margin"] / Decimal(n_c) if n_c else ZERO
        net_incremental_margin = money(
            max(ZERO, (cat_margin_rate_t - cat_margin_rate_c)) * Decimal(n_t))

        reliable = n_c >= RELIABLE_CONTROL_MIN
        result = {
            "promoted_item_id": item_id, "category": category,
            "promoted_lift_units": promoted_lift_units,
            "category_net_lift_units": category_net_lift_units,
            "cannibalized_units": cannibalized_units,
            "cannibalization_rate": round(float(cannib_rate), 4) if cannib_rate is not None else None,
            "net_incremental_margin_aed": str(net_incremental_margin),
            "is_reliable": reliable,
            "note": _interpret(promoted_lift_units, category_net_lift_units,
                               cannibalized_units, reliable),
        }
        results.append(result)

        if persist:
            await db.execute(
                text("""INSERT INTO flywheel_cannibalization
                           (tenant_id, campaign_id, category, promoted_item_id, method,
                            window_start, window_end, promoted_lift_units,
                            category_net_lift_units, cannibalized_units,
                            cannibalization_rate, net_incremental_margin_aed,
                            is_reliable, note)
                        VALUES (:t, :c, :cat, :item, 'did', :ws, :we, :pl, :cl, :cu,
                                :rate, :marg, :rel, :note)
                        ON CONFLICT (tenant_id, campaign_id, promoted_item_id, window_end)
                        DO UPDATE SET
                            promoted_lift_units = EXCLUDED.promoted_lift_units,
                            category_net_lift_units = EXCLUDED.category_net_lift_units,
                            cannibalized_units = EXCLUDED.cannibalized_units,
                            cannibalization_rate = EXCLUDED.cannibalization_rate,
                            net_incremental_margin_aed = EXCLUDED.net_incremental_margin_aed,
                            is_reliable = EXCLUDED.is_reliable, note = EXCLUDED.note,
                            computed_at = now()"""),
                {"t": tenant_id, "c": campaign_id, "cat": category, "item": item_id,
                 "ws": starts_on, "we": window_end, "pl": promoted_lift_units,
                 "cl": category_net_lift_units, "cu": cannibalized_units,
                 "rate": cannib_rate, "marg": net_incremental_margin,
                 "rel": reliable, "note": result["note"]},
            )

        # Pairwise substitution: other SKUs in the same category, treated-vs-
        # control rate delta. A negative delta is a SKU that lost volume when the
        # promoted one was pushed — cannibalisation made concrete per pair.
        others = (await db.execute(
            text("""SELECT e.item_id,
                           COALESCE(SUM(e.quantity_units) FILTER (WHERE a.assignment='treatment'),0) AS t_u,
                           COALESCE(SUM(e.quantity_units) FILTER (WHERE a.assignment='control'),0) AS c_u
                      FROM flywheel_customer_events e
                      JOIN flywheel_campaign_audience a
                        ON a.customer_id = e.customer_id AND a.tenant_id = e.tenant_id
                       AND a.campaign_id = :c
                     WHERE e.tenant_id = :t AND e.category = :cat AND e.item_id <> :item
                       AND e.event_type='purchase'
                       AND e.occurred_at >= :start AND e.occurred_at < :end
                     GROUP BY e.item_id"""),
            {"c": campaign_id, "t": tenant_id, "cat": category, "item": item_id,
             "start": starts_on, "end": window_end},
        )).fetchall()
        for o in others:
            other_id = int(o[0])
            other_rate_t = int(o[1]) / n_t
            other_rate_c = int(o[2]) / n_c
            sub_pc = other_rate_t - other_rate_c
            sub_units = round(sub_pc * n_t)
            if sub_units == 0:
                continue
            substitution.append({
                "from_item_id": item_id, "to_item_id": other_id,
                "substitution_units": sub_units,
            })
            if persist:
                await db.execute(
                    text("""INSERT INTO flywheel_substitution
                               (tenant_id, campaign_id, from_item_id, to_item_id,
                                substitution_units, substitution_rate)
                            VALUES (:t, :c, :fi, :ti, :u, :r)
                            ON CONFLICT (tenant_id, campaign_id, from_item_id, to_item_id)
                            DO UPDATE SET substitution_units = EXCLUDED.substitution_units,
                                          substitution_rate = EXCLUDED.substitution_rate,
                                          computed_at = now()"""),
                    {"t": tenant_id, "c": campaign_id, "fi": item_id, "ti": other_id,
                     "u": sub_units,
                     "r": (Decimal(sub_units) / Decimal(promoted_lift_units)
                           if promoted_lift_units > 0 else None)},
                )

    return {
        "campaign_id": campaign_id,
        "window": {"from": str(starts_on), "to": str(window_end)},
        "arms": {"treatment": n_t, "control": n_c},
        "results": results,
        "substitution": substitution,
        "method": "difference-in-differences (promoted-SKU vs category, treatment vs control)",
    }


def _interpret(promoted: int, category: int, cannibalized: int, reliable: bool) -> str:
    prefix = "" if reliable else "Directional (small control arm): "
    if promoted <= 0:
        return prefix + "No measurable lift on the promoted SKU."
    if cannibalized == 0:
        return prefix + (f"All {promoted} units of lift were incremental to the "
                         f"category — no cannibalisation detected.")
    pct = round(100 * cannibalized / promoted)
    return prefix + (f"{cannibalized} of {promoted} lift units ({pct}%) came from "
                     f"other SKUs in the category, not new demand. A supplier is "
                     f"charged on the {category} genuinely incremental category units.")


async def latest(db: AsyncSession, *, tenant_id: int, campaign_id: int) -> Dict[str, Any]:
    """The most recent persisted cannibalization readout for a campaign."""
    rows = (await db.execute(
        text("""SELECT category, promoted_item_id, promoted_lift_units,
                       category_net_lift_units, cannibalized_units,
                       cannibalization_rate, net_incremental_margin_aed,
                       is_reliable, note, window_end
                  FROM flywheel_cannibalization
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND window_end = (SELECT MAX(window_end) FROM flywheel_cannibalization
                                      WHERE tenant_id = :t AND campaign_id = :c)
                 ORDER BY cannibalized_units DESC"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()
    return {
        "campaign_id": campaign_id,
        "results": [{
            "category": r[0], "promoted_item_id": int(r[1]) if r[1] else None,
            "promoted_lift_units": int(r[2]), "category_net_lift_units": int(r[3]),
            "cannibalized_units": int(r[4]),
            "cannibalization_rate": float(r[5]) if r[5] is not None else None,
            "net_incremental_margin_aed": str(money(r[6])),
            "is_reliable": bool(r[7]), "note": r[8],
            "window_end": str(r[9]),
        } for r in rows],
    }
