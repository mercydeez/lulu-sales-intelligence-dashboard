"""Perishables & shelf-life — when clearing stock beats retaining a customer.

THE GROCER'S TRUTH THE ENGINE WAS MISSING. For a supermarket, the most valuable
promotion this afternoon may have nothing to do with churn. It is the yoghurt
three days from expiry: promote it now and recover most of its margin; leave it
and write off 100% of its cost on Thursday. Markdown TIMING on short-dated stock
can be worth more than a retention offer, and an engine that only reasons about
customers never sees it.

WHAT THIS COMPUTES. For each near-expiry batch, a MARKDOWN URGENCY and the VALUE
AT RISK — the cost the business eats if the batch is not sold. Urgency rises as
expiry approaches; the recommendation is to promote the batch while a markdown
still recovers more than the write-off would lose.

  value_at_risk = units * unit_cost      (what is written off if unsold)
  urgency       = f(days_to_expiry)      (0 far out, 1 at/after expiry)

The recommended markdown depth increases with urgency, because a steeper discount
that sells the stock beats a shallow one that does not clear it in time.

HOW IT REACHES THE ALLOCATOR. As a per-SKU MARKDOWN BOOST the allocator can add
to a candidate's value — a near-expiry SKU is worth promoting beyond its churn
case. This is exposed as data (`markdown_boost_for`) rather than wired invisibly,
so the allocator's determinism and its "degrades to greedy when unconstrained"
property are preserved: the boost is an explicit input, not a hidden side effect.

THE GOVERNING RULE HOLDS. Deterministic arithmetic over recorded batches. It only
ever RECOMMENDS a markdown; it moves no stock and no money on its own.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money, money4

logger = logging.getLogger(__name__)

#: Batches with more days than this are not urgent — no markdown recommended yet.
URGENT_HORIZON_DAYS = 7


def urgency_for(days_to_expiry: int) -> float:
    """0 far from expiry, rising to 1 at/after expiry.

    Linear inside the urgent horizon and clamped outside it. A batch already
    expired is urgency 1 (it should have been actioned; surface it loudly).
    """
    if days_to_expiry <= 0:
        return 1.0
    if days_to_expiry >= URGENT_HORIZON_DAYS:
        return 0.0
    return round(1.0 - (days_to_expiry / URGENT_HORIZON_DAYS), 4)


def recommended_markdown_pct(urgency: float) -> Decimal:
    """A steeper discount as expiry nears — enough to actually clear the stock.

    Capped at 50%: below that a markdown still recovers more than a total
    write-off, which is the whole economic case. Zero urgency, zero markdown.
    """
    if urgency <= 0:
        return ZERO
    return money(Decimal(str(urgency)) * Decimal("50"))


async def record_batch(
    db: AsyncSession, *, tenant_id: int, store_id: int, item_id: int,
    batch_ref: str, units: int, received_on: date, expires_on: date,
    unit_cost_aed: Decimal = ZERO,
) -> Dict[str, Any]:
    await db.execute(
        text("""INSERT INTO flywheel_shelf_life
                   (tenant_id, store_id, item_id, batch_ref, units, received_on,
                    expires_on, unit_cost_aed)
                VALUES (:t, :s, :i, :b, :u, :r, :e, :cost)
                ON CONFLICT (tenant_id, store_id, item_id, batch_ref)
                DO UPDATE SET units = EXCLUDED.units, expires_on = EXCLUDED.expires_on,
                              unit_cost_aed = EXCLUDED.unit_cost_aed, updated_at = now()"""),
        {"t": tenant_id, "s": store_id, "i": item_id, "b": batch_ref, "u": units,
         "r": received_on, "e": expires_on, "cost": money4(unit_cost_aed)},
    )
    return {"batch_ref": batch_ref, "units": units, "expires_on": str(expires_on)}


async def markdown_candidates(
    db: AsyncSession, *, tenant_id: int, store_id: Optional[int] = None,
    horizon_days: int = URGENT_HORIZON_DAYS,
) -> Dict[str, Any]:
    """Near-expiry batches, ranked by value at risk, with a recommended markdown.

    This is the operational surface: what to promote before it is written off,
    and how much value each recommendation protects.
    """
    today = date.today()
    store_clause = "AND store_id = :store" if store_id is not None else ""
    params: Dict[str, Any] = {"t": tenant_id, "horizon": horizon_days, "today": today}
    if store_id is not None:
        params["store"] = store_id

    rows = (await db.execute(
        text(f"""SELECT sl.id, sl.store_id, s.name, sl.item_id, i.name, i.category,
                        sl.batch_ref, sl.units, sl.expires_on, sl.unit_cost_aed,
                        (sl.expires_on - :today) AS days_left
                   FROM flywheel_shelf_life sl
                   JOIN stores s ON s.id = sl.store_id
                   JOIN items i ON i.id = sl.item_id
                  WHERE sl.tenant_id = :t AND sl.status = 'active'
                    AND sl.expires_on <= :today + make_interval(days => :horizon)
                    {store_clause}
                  ORDER BY sl.expires_on, sl.units * sl.unit_cost_aed DESC"""),
        params,
    )).fetchall()

    candidates = []
    total_at_risk = ZERO
    for r in rows:
        days_left = int(r[10])
        urgency = urgency_for(days_left)
        value_at_risk = money(Decimal(int(r[7])) * money4(r[9]))
        total_at_risk = money(total_at_risk + value_at_risk)
        candidates.append({
            "batch_id": int(r[0]), "store_id": int(r[1]), "store_name": r[2],
            "item_id": int(r[3]), "item_name": r[4], "category": r[5],
            "batch_ref": r[6], "units": int(r[7]), "expires_on": str(r[8]),
            "days_to_expiry": days_left,
            "urgency": urgency,
            "value_at_risk_aed": str(value_at_risk),
            "recommended_markdown_pct": str(recommended_markdown_pct(urgency)),
            "recommendation": _recommend(days_left, int(r[7]), value_at_risk),
        })

    return {
        "candidates": candidates,
        "count": len(candidates),
        "total_value_at_risk_aed": str(total_at_risk),
        "note": ("Value at risk is the cost written off if the batch is not sold "
                 "before expiry. A markdown that clears it recovers most of that — "
                 "which is why, for a grocer, this can outrank a retention offer."),
    }


async def markdown_boost_for(
    db: AsyncSession, *, tenant_id: int, store_id: int, item_id: int
) -> Decimal:
    """The extra AED value of promoting THIS SKU at THIS store because it has
    near-expiry stock — an explicit input the allocator can add to a candidate.

    It is the value at risk on the most urgent active batch, scaled by urgency:
    a batch one day from expiry contributes almost its whole cost as upside for
    clearing it now, because the counterfactual is a full write-off.
    """
    row = (await db.execute(
        text("""SELECT units, unit_cost_aed, (expires_on - CURRENT_DATE) AS days_left
                  FROM flywheel_shelf_life
                 WHERE tenant_id = :t AND store_id = :s AND item_id = :i
                   AND status = 'active' AND expires_on >= CURRENT_DATE
                 ORDER BY expires_on LIMIT 1"""),
        {"t": tenant_id, "s": store_id, "i": item_id},
    )).fetchone()
    if not row:
        return ZERO
    units, unit_cost, days_left = int(row[0]), money4(row[1]), int(row[2])
    urgency = Decimal(str(urgency_for(days_left)))
    return money(Decimal(units) * unit_cost * urgency)


def _recommend(days_left: int, units: int, value_at_risk: Decimal) -> str:
    if days_left <= 0:
        return (f"EXPIRED — {units} units already past date. Pull from shelf and "
                f"write off {value_at_risk} AED, or check the date.")
    if days_left <= 2:
        return (f"Promote NOW at a deep markdown — {days_left} day(s) left, "
                f"{value_at_risk} AED at risk of write-off.")
    return (f"Queue a markdown within {days_left} days to recover {value_at_risk} "
            f"AED before expiry.")
