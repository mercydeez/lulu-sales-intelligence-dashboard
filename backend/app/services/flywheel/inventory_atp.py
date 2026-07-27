"""Stage 4 — available-to-promise and the shortage ladder.

    ATP = on_hand + eligible incoming − hard reservations
          − soft campaign allocations − safety stock − forecast demand buffer

WHY A LAYER RATHER THAN A NEW STOCK TABLE. The existing `inventory` table is the
truth about what is on the shelf, and `inventory_transactions` is its history.
Forking either would create two answers to "how much do we have", and the wrong
one would eventually win. So Flywheel adds only what did not exist — campaign
ALLOCATIONS — and subtracts them from the real number.

SOFT vs HARD. During planning a campaign holds a SOFT allocation: a claim on
stock that reduces ATP for other campaigns but has not moved anything. At
redemption the claim becomes HARD — real units leave real inventory, inside the
row-locked transaction in `decisioning.redeem`. Planning must never decrement
stock, or an unapproved campaign would empty the shelves.

THE SHORTAGE LADDER (§6 step 8) is ordered by cost-to-the-business, cheapest
first. Reducing the audience costs nothing; procurement costs cash and time.
Each rung is only tried when the one above it fails.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import AtpResult, ZERO, money

logger = logging.getLogger(__name__)

#: How stale the inventory FEED may be before we refuse to promise against it.
#:
#: Deliberately generous by default, and deliberately measured at the FEED level
#: rather than the row level — see `inventory_freshness_ok` for why. Tighten it
#: to single-digit hours once a real-time inventory feed exists; the env var is
#: there so that is a config change, not a code change.
MAX_INVENTORY_STALENESS_HOURS = int(
    os.environ.get("FLYWHEEL_MAX_INVENTORY_STALENESS_HOURS", "168")  # 7 days
)


async def compute_atp(
    db: AsyncSession, *, tenant_id: int, store_id: int, item_id: int,
    safety_stock_pct: Decimal = Decimal("10"),
    fulfilment_date: Optional[date] = None,
    exclude_campaign_id: Optional[int] = None,
) -> AtpResult:
    """Available-to-promise for one (store, item).

    `exclude_campaign_id` omits a campaign's OWN soft allocation from the
    subtraction — without it, re-simulating a campaign would see its own claim
    as competing demand and progressively starve itself on each run.
    """
    fulfilment_date = fulfilment_date or date.today()

    row = (await db.execute(
        text("""SELECT current_stock, COALESCE(reserved_stock, 0), reorder_point
                  FROM inventory WHERE store_id = :s AND item_id = :i"""),
        {"s": store_id, "i": item_id},
    )).fetchone()

    on_hand = int(row[0]) if row else 0
    hard_reservations = int(row[1]) if row else 0
    reorder_point = int(row[2]) if row and row[2] is not None else 0

    # Incoming supply that will actually ARRIVE IN TIME. A PO landing after the
    # campaign ends is not available to promise, however real it is.
    #
    # `purchase_orders` has no expected-arrival column, so arrival is DERIVED as
    # (sent_at or created_at) + the supplier's lead time. That is an estimate,
    # and it is deliberately the conservative one: we only count stock we
    # believe lands on or before the fulfilment date, so a slow supplier reduces
    # ATP rather than silently inflating it.
    #
    # Column names here are the real ones (pol.po_id, pol.received_qty) — an
    # earlier version guessed `purchase_order_id`/`received_quantity` and failed
    # at runtime. Verify against \d purchase_order_lines before changing.
    incoming = (await db.execute(
        text("""SELECT COALESCE(SUM(GREATEST(0, pol.quantity - COALESCE(pol.received_qty, 0))), 0)
                  FROM purchase_order_lines pol
                  JOIN purchase_orders po ON po.id = pol.po_id
                  LEFT JOIN suppliers s ON s.id = po.supplier_id
                 WHERE po.tenant_id = :t
                   AND pol.item_id = :i
                   AND po.status IN ('approved', 'sent')
                   AND (COALESCE(po.sent_at, po.created_at)
                        + make_interval(days => COALESCE(s.lead_time_days, 7)))
                       <= CAST(:fd AS timestamptz)"""),
        {"t": tenant_id, "i": item_id, "fd": fulfilment_date},
    )).scalar() or 0

    # Other campaigns' outstanding soft claims.
    exclude_clause = "AND campaign_id <> :xc" if exclude_campaign_id else ""
    params: Dict[str, Any] = {"t": tenant_id, "s": store_id, "i": item_id}
    if exclude_campaign_id:
        params["xc"] = exclude_campaign_id
    soft = (await db.execute(
        text(f"""SELECT COALESCE(SUM(allocated_units - consumed_units), 0)
                   FROM flywheel_inventory_allocations
                  WHERE tenant_id = :t AND store_id = :s AND item_id = :i
                    AND status = 'soft' {exclude_clause}"""),
        params,
    )).scalar() or 0

    # Safety stock: the greater of the configured percentage and the existing
    # reorder point. Flywheel may tighten a store's floor but must never LOWER the
    # protection the inventory team already set.
    pct_floor = int((Decimal(on_hand) * safety_stock_pct / Decimal("100")).to_integral_value())
    safety_stock = max(pct_floor, reorder_point)

    # Forecast demand buffer — normal trade during the campaign window that we
    # must not cannibalise. Uses the tenant's own recent sell-through.
    demand_buffer = await _demand_buffer(db, tenant_id=tenant_id, store_id=store_id,
                                         item_id=item_id, horizon_days=14)

    return AtpResult(
        store_id=store_id, item_id=item_id, on_hand=on_hand,
        incoming=int(incoming), hard_reservations=hard_reservations,
        soft_allocations=int(soft), safety_stock=safety_stock,
        demand_buffer=demand_buffer,
    )


async def _demand_buffer(
    db: AsyncSession, *, tenant_id: int, store_id: int, item_id: int, horizon_days: int
) -> int:
    """Expected ordinary demand over the horizon, from recent sell-through.

    Deliberately simple and explainable (mean daily units over 28 days × horizon)
    rather than calling the forecasting engine: this is a RESERVATION, and an
    operator must be able to say why 40 units are held back. Returns 0 when
    there is no history — no evidence of demand means no buffer.
    """
    avg_daily = (await db.execute(
        text("""SELECT COALESCE(AVG(daily_units), 0) FROM (
                    SELECT date, SUM(sales) AS daily_units
                      FROM sales_fact_view
                     WHERE tenant_id = :t AND store_id = :s AND item_id = :i
                       AND date >= CURRENT_DATE - INTERVAL '28 days'
                     GROUP BY date
                ) d"""),
        {"t": tenant_id, "s": store_id, "i": item_id},
    )).scalar() or 0
    return int(float(avg_daily) * horizon_days)


async def inventory_freshness_ok(
    db: AsyncSession, *, store_id: int, item_id: int
) -> bool:
    """Is the inventory data trustworthy enough to promise stock against?

    THE QUESTION THIS ASKS, AND WHY IT CHANGED. The obvious implementation —
    "was THIS row updated recently?" — is wrong, and it was wrong here in a way
    that blocked every single offer in the system.

    An `inventory` row's `updated_at` only moves when the STOCK moves. A
    slow-moving SKU that has not sold in three weeks has a perfectly accurate
    count; its silence is evidence of stability, not of ignorance. Judging that
    row stale refuses to sell exactly the products that most need promoting.

    What actually makes a stock number untrustworthy is the FEED dying: if
    nothing anywhere has updated for days, we have lost sight of the warehouse
    and must not promise. So freshness is measured across the store's inventory
    as a whole. One recently-moved SKU proves the feed is alive, which makes the
    quiet SKUs beside it trustworthy too.

    IS THERE A FEED AT ALL? "The feed died" and "there is no feed, this is
    bulk-loaded reference data" look identical if you only read the newest
    timestamp — both are old — but they demand opposite responses. Refusing to
    trade because a static reference table is static would disable the product
    permanently.

    They are distinguishable: a live feed writes rows at many different moments,
    so its timestamps are SPREAD. A bulk load stamps every row in one
    transaction, so they are IDENTICAL. This counts distinct timestamps: one
    distinct value means a snapshot (trust it, there is nothing to be stale
    relative to); several mean a real feed, and then the age threshold applies.

    Fails OPEN when there is no timestamp at all (a fresh install), because
    absence of a signal is not evidence of a problem — and a system that
    refuses every offer on a new deployment is not shippable.
    """
    row = (await db.execute(
        text("""SELECT
                  EXTRACT(EPOCH FROM (now() - MAX(COALESCE(
                      updated_at, CAST(last_restock_date AS timestamptz))))) / 3600
                    AS age_hours,
                  COUNT(DISTINCT COALESCE(
                      updated_at, CAST(last_restock_date AS timestamptz)))
                    AS distinct_stamps
                  FROM inventory WHERE store_id = :s"""),
        {"s": store_id},
    )).fetchone()

    if not row or row[0] is None:
        return True                      # no signal at all — do not block
    if int(row[1] or 0) <= 1:
        return True                      # a snapshot, not a feed
    return float(row[0]) <= MAX_INVENTORY_STALENESS_HOURS


async def find_substitute(
    db: AsyncSession, *, tenant_id: int, store_id: int, item_id: int,
    required_units: int, safety_stock_pct: Decimal = Decimal("10"),
) -> Optional[Dict[str, Any]]:
    """Rung (b): an in-stock item in the same category at a comparable price.

    Price band is ±25%: a substitute that is much cheaper devalues the offer,
    and one much dearer destroys the margin the offer was built on. Ranked by
    ATP so we pick the one we can most comfortably serve.
    """
    row = (await db.execute(
        text("""SELECT i.id, i.name, i.unit_price_aed, inv.current_stock
                  FROM items i
                  JOIN inventory inv ON inv.item_id = i.id AND inv.store_id = :s
                 WHERE i.category = (SELECT category FROM items WHERE id = :orig)
                   AND i.id <> :orig
                   AND inv.current_stock > 0
                   AND i.unit_price_aed BETWEEN
                       (SELECT unit_price_aed * 0.75 FROM items WHERE id = :orig) AND
                       (SELECT unit_price_aed * 1.25 FROM items WHERE id = :orig)
                 ORDER BY inv.current_stock DESC
                 LIMIT 5"""),
        {"s": store_id, "orig": item_id},
    )).fetchall()

    for candidate_id, name, price, _stock in row:
        atp = await compute_atp(db, tenant_id=tenant_id, store_id=store_id,
                                item_id=int(candidate_id), safety_stock_pct=safety_stock_pct)
        if atp.atp_units >= required_units:
            return {
                "item_id": int(candidate_id), "name": name,
                "unit_price_aed": str(money(price)),
                "atp_units": atp.atp_units,
                "reason": f"Same category, price within 25% of the original, "
                          f"{atp.atp_units} units available to promise",
            }
    return None


async def find_transfer_source(
    db: AsyncSession, *, tenant_id: int, to_store_id: int, item_id: int,
    required_units: int, accessible_store_ids: Optional[List[int]] = None,
    safety_stock_pct: Decimal = Decimal("10"),
) -> Optional[Dict[str, Any]]:
    """Rung (c): another store with a SAFE surplus.

    "Safe" is the whole point: the source keeps its own safety stock and demand
    buffer. Solving one store's shortage by creating another's is not a solution,
    and this is where a naive implementation gets it wrong.
    """
    store_filter = ""
    params: Dict[str, Any] = {"i": item_id, "to": to_store_id}
    if accessible_store_ids:
        store_filter = "AND inv.store_id = ANY(:stores)"
        params["stores"] = accessible_store_ids

    rows = (await db.execute(
        text(f"""SELECT inv.store_id, s.name, inv.current_stock
                   FROM inventory inv
                   JOIN stores s ON s.id = inv.store_id
                  WHERE inv.item_id = :i AND inv.store_id <> :to
                    AND inv.current_stock > 0 {store_filter}
                  ORDER BY inv.current_stock DESC
                  LIMIT 8"""),
        params,
    )).fetchall()

    for from_store_id, store_name, _stock in rows:
        atp = await compute_atp(db, tenant_id=tenant_id, store_id=int(from_store_id),
                                item_id=item_id, safety_stock_pct=safety_stock_pct)
        # Only genuine surplus — what remains after the SOURCE's own protection.
        if atp.atp_units >= required_units:
            return {
                "from_store_id": int(from_store_id),
                "from_store_name": store_name,
                "units": required_units,
                "source_surplus_units": atp.atp_units,
                "reason": f"{store_name} holds {atp.atp_units} units above its own "
                          f"safety stock and demand buffer",
            }
    return None


async def allocate_soft(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, store_id: int,
    item_id: int, units: int,
) -> Dict[str, Any]:
    """Place (or top up) a soft allocation. Planning-time only — moves no stock.

    Upserts so re-simulating a campaign updates its claim rather than stacking
    duplicate rows that would each subtract from ATP.
    """
    if units <= 0:
        return {"allocated": 0}
    await db.execute(
        text("""INSERT INTO flywheel_inventory_allocations
                   (tenant_id, campaign_id, store_id, item_id, allocated_units, status)
                VALUES (:t, :c, :s, :i, :u, 'soft')
                ON CONFLICT (campaign_id, store_id, item_id) DO UPDATE
                    SET allocated_units = EXCLUDED.allocated_units,
                        status = CASE WHEN flywheel_inventory_allocations.status = 'released'
                                      THEN 'soft' ELSE flywheel_inventory_allocations.status END,
                        released_at = NULL"""),
        {"t": tenant_id, "c": campaign_id, "s": store_id, "i": item_id, "u": units},
    )
    return {"allocated": units, "store_id": store_id, "item_id": item_id}


async def release_allocations(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Dict[str, Any]:
    """Hand back every unconsumed allocation (cancellation / completion, §6.18).

    Only unconsumed units are released — consumed units already became real
    stock movements at redemption and cannot be un-consumed here.
    """
    result = await db.execute(
        text("""UPDATE flywheel_inventory_allocations
                   SET status = 'released', released_at = now()
                 WHERE tenant_id = :t AND campaign_id = :c AND status = 'soft'
                 RETURNING allocated_units - consumed_units"""),
        {"t": tenant_id, "c": campaign_id},
    )
    freed = [int(r[0]) for r in result.fetchall()]
    logger.info("flywheel.inventory released campaign=%s rows=%s units=%s",
                campaign_id, len(freed), sum(freed))
    return {"released_rows": len(freed), "released_units": sum(freed)}


async def resolve_shortage(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, store_id: int,
    item_id: int, required_units: int, required_by: date,
    safety_stock_pct: Decimal = Decimal("10"),
    accessible_store_ids: Optional[List[int]] = None,
    allow_procurement: bool = True,
    expected_eiv_aed: Decimal = ZERO,
) -> Dict[str, Any]:
    """Walk the shortage ladder in order and return the first workable rung.

        (a) reduce audience to the highest-value customers
        (b) in-stock substitute
        (c) inter-store transfer
        (d) non-inventory reward
        (e) aggregated procurement requisition — only if economically justified
        (f) suppress the offer

    Returns the chosen rung with its reasoning. It does NOT execute the
    resolution: the caller decides whether to act, so a simulation can show the
    operator what WOULD happen without committing anything.
    """
    atp = await compute_atp(db, tenant_id=tenant_id, store_id=store_id, item_id=item_id,
                            safety_stock_pct=safety_stock_pct,
                            fulfilment_date=required_by, exclude_campaign_id=campaign_id)

    if atp.atp_units >= required_units:
        return {"rung": "none", "resolved": True, "atp": atp.to_snapshot(),
                "detail": "Stock is sufficient; no shortage to resolve"}

    shortfall = required_units - atp.atp_units
    ladder: List[Dict[str, Any]] = []

    # (a) Serve fewer customers — costs nothing, so it is always first.
    if atp.atp_units > 0:
        ladder.append({
            "rung": "a_reduce_audience", "resolved": True,
            "servable_units": atp.atp_units, "shortfall": shortfall,
            "detail": f"Serve the {atp.atp_units} highest-EIV customers and suppress "
                      f"the remaining {shortfall} — costs nothing and protects margin",
        })
        return {**ladder[0], "atp": atp.to_snapshot(), "ladder_considered": ["a"]}

    # (b) Substitute.
    substitute = await find_substitute(
        db, tenant_id=tenant_id, store_id=store_id, item_id=item_id,
        required_units=required_units, safety_stock_pct=safety_stock_pct)
    if substitute:
        return {"rung": "b_substitute", "resolved": True, "substitute": substitute,
                "atp": atp.to_snapshot(), "ladder_considered": ["a", "b"],
                "detail": substitute["reason"]}

    # (c) Transfer.
    transfer = await find_transfer_source(
        db, tenant_id=tenant_id, to_store_id=store_id, item_id=item_id,
        required_units=required_units, accessible_store_ids=accessible_store_ids,
        safety_stock_pct=safety_stock_pct)
    if transfer:
        return {"rung": "c_transfer", "resolved": True, "transfer": transfer,
                "atp": atp.to_snapshot(), "ladder_considered": ["a", "b", "c"],
                "detail": transfer["reason"]}

    # (d) Non-inventory reward — always available, since it consumes no stock.
    non_stock = {
        "rung": "d_non_stock_reward", "resolved": True,
        "suggested_actions": ["LOYALTY_POINTS", "FREE_DELIVERY", "REMINDER"],
        "detail": "No stock path found; offer a reward that consumes no inventory",
    }

    # (e) Procurement — only when it can ARRIVE IN TIME and pays for itself.
    if allow_procurement:
        from app.services.flywheel import procurement
        assessment = await procurement.assess(
            db, tenant_id=tenant_id, item_id=item_id, units=shortfall,
            required_by=required_by, expected_eiv_aed=expected_eiv_aed)
        if assessment["viable"]:
            return {"rung": "e_procurement", "resolved": True,
                    "procurement": assessment, "atp": atp.to_snapshot(),
                    "ladder_considered": ["a", "b", "c", "d", "e"],
                    "detail": assessment["detail"]}
        # Procurement refused — say why, then fall back to the non-stock reward.
        non_stock["procurement_rejected"] = assessment

    non_stock["atp"] = atp.to_snapshot()
    non_stock["ladder_considered"] = ["a", "b", "c", "d", "e"]
    return non_stock
