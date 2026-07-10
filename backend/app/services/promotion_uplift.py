"""E7-5 — promotion uplift measurement + cannibalisation.

"Did the promotion work?" is two questions:

  1. Did the promoted items sell more than they would have anyway?
  2. Did that lift come from NEW demand, or from the shelf next door?

A promo that lifts one SKU 40% while its category peers drop 35% moved sales
sideways and gave away the margin. Category managers ask for this constantly and
almost no tool answers it.

Method (deliberately simple, entirely reproducible):
  * treated set   = the promotion's items, in the promotion's stores.
  * promo window  = [start_date, end_date] (inclusive), N days.
  * baseline      = the N days immediately BEFORE the promo, same items/stores.
  * peers         = every other item in the treated items' categories, same
                    stores, measured over the same two windows.
  * noise         = how much the peers moved between the two windows *before*
                    the promo (the N days before the baseline). A peer drop is
                    only called cannibalisation when it exceeds that.

Honesty rules, non-negotiable:
  * A baseline window with no sales -> status `insufficient_baseline`, no numbers.
  * Cannibalisation is a FLAG with a basis string, never a causal claim. Two
    series moving together is correlation; we say so.
  * Margin is reported only where a cost period covers the sale (E2-3); otherwise
    `needs: cost` and units-only.

All reads go through metric_sales_fact / metric_margin_fact — the one place
`units` and `revenue_aed` are defined (E6-1) — so uplift can never disagree with
the KPI screens.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger

# A peer decline smaller than this is noise, whatever the arithmetic says.
MIN_CANNIBALISATION_PCT = 5.0
# The baseline window must contain at least this many sold units to compare against.
MIN_BASELINE_UNITS = 1

_NEEDS_COST = "unit cost — import item costs, or an inventory file with a cost column"


def _pct_change(before: float, after: float) -> Optional[float]:
    """Percentage change, or None when there is no base to change from. Never 0.0
    as a stand-in for 'unknown'."""
    if before <= 0:
        return None
    return round((after - before) / before * 100.0, 1)


async def _window_totals(
    db: AsyncSession, tenant_id: int, item_ids: Sequence[int], store_ids: Sequence[int],
    start: date, end: date,
) -> Dict:
    """Units / revenue / margin for a set of items+stores over [start, end]."""
    if not item_ids or not store_ids:
        return {"units": 0.0, "revenue_aed": 0.0, "margin_aed": None, "costed_revenue_aed": 0.0}

    row = (await db.execute(text("""
        SELECT COALESCE(SUM(m.units), 0)::float              AS units,
               COALESCE(SUM(m.revenue_aed), 0)::float        AS revenue_aed,
               COALESCE(SUM(m.gross_margin_aed), 0)::float   AS margin_aed,
               COALESCE(SUM(m.revenue_aed) FILTER (WHERE m.cogs_aed IS NOT NULL), 0)::float
                                                             AS costed_revenue_aed,
               COUNT(*) FILTER (WHERE m.cogs_aed IS NOT NULL) AS costed_rows
          FROM metric_margin_fact m
         WHERE m.tenant_id = :tid
           AND m.item_id   = ANY(:items)
           AND m.store_id  = ANY(:stores)
           AND m.date BETWEEN :start AND :end
    """), {"tid": tenant_id, "items": list(item_ids), "stores": list(store_ids),
           "start": start, "end": end})).mappings().fetchone()

    return {
        "units": float(row["units"] or 0.0),
        "revenue_aed": round(float(row["revenue_aed"] or 0.0), 2),
        # NULL, not 0, when nothing in the window could be costed.
        "margin_aed": round(float(row["margin_aed"]), 2) if row["costed_rows"] else None,
        "costed_revenue_aed": round(float(row["costed_revenue_aed"] or 0.0), 2),
    }


async def _peer_items(
    db: AsyncSession, tenant_id: int, promoted_item_ids: Sequence[int],
) -> List[int]:
    """Every other item in the promoted items' categories. These are the shelves a
    promo can steal from."""
    if not promoted_item_ids:
        return []
    rows = (await db.execute(text("""
        SELECT i.id
          FROM items i
         WHERE i.tenant_id = :tid
           AND i.category IN (SELECT category FROM items
                               WHERE id = ANY(:items) AND category IS NOT NULL)
           AND NOT (i.id = ANY(:items))
    """), {"tid": tenant_id, "items": list(promoted_item_ids)})).fetchall()
    return [r[0] for r in rows]


async def measure_promotion_uplift(
    db: AsyncSession,
    tenant_id: int,
    item_ids: Sequence[int],
    store_ids: Sequence[int],
    start: date,
    end: date,
    allowed: Optional[Sequence[int]] = None,
) -> Dict:
    """Measure a promotion against a matched pre-promo baseline, and check whether
    its category peers paid for the lift."""
    if allowed:
        store_ids = [s for s in store_ids if s in set(allowed)]

    if not item_ids or not store_ids:
        return {"status": "no_scope",
                "reason": "the promotion has no items or no stores you can see"}

    span = (end - start).days + 1
    if span < 1:
        return {"status": "invalid_window", "reason": "end date is before start date"}

    base_end = start - timedelta(days=1)
    base_start = base_end - timedelta(days=span - 1)
    # The window before the baseline: how much peers drift on their own.
    prior_end = base_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=span - 1)

    promo = await _window_totals(db, tenant_id, item_ids, store_ids, start, end)
    base = await _window_totals(db, tenant_id, item_ids, store_ids, base_start, base_end)

    if base["units"] < MIN_BASELINE_UNITS:
        # No baseline, no claim. This is the state the blueprint asks for by name.
        return {
            "status": "insufficient_baseline",
            "reason": (f"no sales for these items in the {span} days before the promo "
                       f"({base_start} to {base_end}) — nothing to compare against"),
            "window": {"start": str(start), "end": str(end), "days": span},
            "baseline_window": {"start": str(base_start), "end": str(base_end)},
        }

    uplift_units = round(promo["units"] - base["units"], 2)
    uplift_pct = _pct_change(base["units"], promo["units"])
    uplift_revenue = round(promo["revenue_aed"] - base["revenue_aed"], 2)

    # Margin uplift only where BOTH windows could be costed (E2-3).
    margin_uplift = needs = None
    if promo["margin_aed"] is not None and base["margin_aed"] is not None:
        margin_uplift = round(promo["margin_aed"] - base["margin_aed"], 2)
    else:
        needs = _NEEDS_COST

    cannibalisation = await _cannibalisation(
        db, tenant_id, item_ids, store_ids,
        start, end, base_start, base_end, prior_start, prior_end,
        promoted_lifted=(uplift_units > 0),
    )

    return {
        "status": "ready",
        "window": {"start": str(start), "end": str(end), "days": span},
        "baseline_window": {"start": str(base_start), "end": str(base_end)},
        "promo": promo,
        "baseline": base,
        "uplift_units": uplift_units,
        "uplift_pct": uplift_pct,
        "uplift_revenue_aed": uplift_revenue,
        "uplift_margin_aed": margin_uplift,
        "needs": needs,
        "cannibalisation": cannibalisation,
        "methodology": (
            f"Promo window {start}..{end} ({span}d) compared with the matched "
            f"{span} days immediately before ({base_start}..{base_end}), same items "
            "and stores. Cannibalisation compares the same two windows for the "
            "promoted items' category peers, and only flags a decline that exceeds "
            "how much those peers already moved between the two windows before the "
            "promo. This is a correlation, not proof of cause."
        ),
    }


async def _cannibalisation(
    db: AsyncSession, tenant_id: int, item_ids: Sequence[int], store_ids: Sequence[int],
    start: date, end: date, base_start: date, base_end: date,
    prior_start: date, prior_end: date, promoted_lifted: bool,
) -> Dict:
    """Did the promoted items' category peers fall while the promo ran — by more
    than those peers already move on their own?"""
    peers = await _peer_items(db, tenant_id, item_ids)
    if not peers:
        return {"flag": False, "status": "no_peers",
                "basis": "no other items share these categories, so nothing could be cannibalised"}

    peer_promo = await _window_totals(db, tenant_id, peers, store_ids, start, end)
    peer_base = await _window_totals(db, tenant_id, peers, store_ids, base_start, base_end)
    peer_prior = await _window_totals(db, tenant_id, peers, store_ids, prior_start, prior_end)

    if peer_base["units"] < MIN_BASELINE_UNITS:
        return {"flag": False, "status": "insufficient_baseline",
                "basis": "the category peers had no sales in the baseline window"}

    peer_change_pct = _pct_change(peer_base["units"], peer_promo["units"])
    # How much the peers moved between two adjacent windows with NO promo running:
    # their own natural drift. Anything inside that band is noise, not theft.
    noise_pct = _pct_change(peer_prior["units"], peer_base["units"])
    noise_band = abs(noise_pct) if noise_pct is not None else 0.0

    if peer_change_pct is None:
        return {"flag": False, "status": "insufficient_baseline",
                "basis": "cannot compute a peer baseline change"}

    drop = -peer_change_pct  # positive when peers declined
    flag = bool(
        promoted_lifted
        and drop > max(MIN_CANNIBALISATION_PCT, noise_band)
    )

    if flag:
        basis = (
            f"category peers fell {drop:.1f}% while the promoted items rose; that "
            f"exceeds both the {MIN_CANNIBALISATION_PCT:.0f}% floor and the {noise_band:.1f}% "
            f"the same peers already drifted between the two pre-promo windows. "
            "Correlation, not proof — check for a concurrent stockout or seasonality."
        )
    elif not promoted_lifted:
        basis = "the promoted items did not lift, so there is no lift to attribute"
    else:
        basis = (
            f"category peers moved {peer_change_pct:+.1f}%, within their own "
            f"{noise_band:.1f}% pre-promo drift — no cannibalisation signal"
        )

    return {
        "flag": flag,
        "status": "ready",
        "peer_item_count": len(peers),
        "peer_units_baseline": peer_base["units"],
        "peer_units_promo": peer_promo["units"],
        "peer_units_delta": round(peer_promo["units"] - peer_base["units"], 2),
        "peer_change_pct": peer_change_pct,
        "peer_noise_pct": round(noise_band, 1),
        "basis": basis,
    }


async def measure_promotion_by_id(
    db: AsyncSession, tenant_id: int, promotion_id: int,
    allowed: Optional[Sequence[int]] = None,
) -> Optional[Dict]:
    """Resolve a stored promotion's items / stores / window, then measure it.
    Returns None when no such promotion exists FOR THIS TENANT (migration 060)."""
    promo = (await db.execute(text("""
        SELECT id, name, start_date::date AS start_date, end_date::date AS end_date,
               applies_to_all_items, applies_to_all_stores
          FROM promotions
         WHERE id = :pid AND tenant_id = :tid
    """), {"pid": promotion_id, "tid": tenant_id})).mappings().fetchone()
    if not promo:
        return None

    if promo["applies_to_all_items"]:
        item_rows = (await db.execute(text(
            "SELECT id FROM items WHERE tenant_id = :tid"), {"tid": tenant_id})).fetchall()
    else:
        item_rows = (await db.execute(text(
            "SELECT item_id FROM promotion_items WHERE promotion_id = :pid"),
            {"pid": promotion_id})).fetchall()

    if promo["applies_to_all_stores"]:
        store_rows = (await db.execute(text(
            "SELECT id FROM stores WHERE tenant_id = :tid"), {"tid": tenant_id})).fetchall()
    else:
        store_rows = (await db.execute(text(
            "SELECT store_id FROM promotion_stores WHERE promotion_id = :pid"),
            {"pid": promotion_id})).fetchall()

    result = await measure_promotion_uplift(
        db, tenant_id,
        item_ids=[r[0] for r in item_rows],
        store_ids=[r[0] for r in store_rows],
        start=promo["start_date"], end=promo["end_date"], allowed=allowed,
    )
    result["promotion"] = {"id": promo["id"], "name": promo["name"]}
    return result
