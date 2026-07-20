"""Stage 4 — procurement: aggregated requisitions, never one PO per customer.

THE FOUR TESTS a procurement recommendation must pass (§12). All four, not any:

  1. TIMING       expected arrival <= required-by date. A pallet that lands the
                  day after the campaign ends is worthless, however cheap.
  2. ECONOMICS    EIV must stay POSITIVE after the procurement cost. Buying stock
                  to fund a discount that loses money twice is not a strategy.
  3. SUPPLY TERMS MOQ and pack size respected — you cannot order 7 units from a
                  supplier whose minimum is 50, so the real cost is 50 × unit.
  4. FUNDING      procurement budget available, and approvals obtained.

AGGREGATION. Shortages are summed by (campaign, store, item, required_by) BEFORE
a requisition is drafted. A campaign touching 5,000 customers must produce one
requisition per SKU per store, not 5,000 purchase orders — that is the difference
between a system a procurement manager can use and one that buries them.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money, money4

logger = logging.getLogger(__name__)


async def best_supplier(
    db: AsyncSession, *, tenant_id: int, item_id: int
) -> Optional[Dict[str, Any]]:
    """The preferred supplier for an item, cheapest-then-fastest.

    Preference order is deliberate: `is_preferred` first (a commercial
    relationship the buying team already chose), then cost, then lead time.
    """
    row = (await db.execute(
        text("""SELECT ps.supplier_id, s.name, ps.unit_cost, ps.moq,
                       COALESCE(ps.lead_time_days, s.lead_time_days) AS lead_time
                  FROM product_suppliers ps
                  JOIN suppliers s ON s.id = ps.supplier_id
                 WHERE ps.tenant_id = :t AND ps.item_id = :i
                   AND s.status = 'active'
                 ORDER BY ps.is_preferred DESC, ps.unit_cost ASC, lead_time ASC
                 LIMIT 1"""),
        {"t": tenant_id, "i": item_id},
    )).fetchone()
    if not row:
        return None
    return {
        "supplier_id": int(row[0]), "supplier_name": row[1],
        "unit_cost_aed": money4(row[2]), "moq": int(row[3] or 1),
        "lead_time_days": int(row[4] or 7),
    }


async def assess(
    db: AsyncSession, *, tenant_id: int, item_id: int, units: int,
    required_by: date, expected_eiv_aed: Decimal = ZERO,
) -> Dict[str, Any]:
    """Run the four tests and report the verdict with its arithmetic.

    Always returns a structured answer — a refusal is as informative as an
    approval and is surfaced in the UI, so a planner learns *why* procurement
    was not the answer rather than seeing an empty panel.
    """
    supplier = await best_supplier(db, tenant_id=tenant_id, item_id=item_id)
    if not supplier:
        return {"viable": False, "reason_code": "NO_SUPPLIER",
                "detail": f"No active supplier is registered for item {item_id}"}

    # TEST 3 — MOQ/pack size. You pay for the minimum, not for what you need.
    order_units = max(units, supplier["moq"])
    total_cost = money(supplier["unit_cost_aed"] * Decimal(order_units))

    # TEST 1 — timing.
    expected_arrival = date.today() + timedelta(days=supplier["lead_time_days"])
    if expected_arrival > required_by:
        return {
            "viable": False, "reason_code": "PROCUREMENT_TOO_SLOW",
            "supplier": supplier["supplier_name"],
            "expected_arrival": str(expected_arrival), "required_by": str(required_by),
            "days_late": (expected_arrival - required_by).days,
            "detail": f"{supplier['supplier_name']} needs {supplier['lead_time_days']} days; "
                      f"stock would arrive {(expected_arrival - required_by).days} day(s) "
                      f"after it is needed",
        }

    # TEST 2 — economics. Does the campaign still make money after buying stock?
    remaining_eiv = money(expected_eiv_aed - total_cost)
    if expected_eiv_aed > ZERO and remaining_eiv <= ZERO:
        return {
            "viable": False, "reason_code": "PROCUREMENT_UNECONOMIC",
            "supplier": supplier["supplier_name"],
            "total_cost_aed": str(total_cost),
            "expected_eiv_aed": str(money(expected_eiv_aed)),
            "eiv_after_procurement_aed": str(remaining_eiv),
            "detail": f"Buying {order_units} units costs {total_cost} AED and turns an "
                      f"EIV of {money(expected_eiv_aed)} into {remaining_eiv} — "
                      f"the campaign would lose money on this SKU",
        }

    # TEST 4 — funding.
    from app.services.flywheel import budget as budget_service
    from app.services.flywheel.types import BudgetType
    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.PROCUREMENT)
    budget_ok, available = True, None
    if budget_id:
        snap = await budget_service.snapshot(db, tenant_id=tenant_id, budget_id=budget_id)
        available = money(snap.get("available_aed", 0))
        budget_ok = total_cost <= available

    if not budget_ok:
        return {
            "viable": False, "reason_code": "INSUFFICIENT_PROCUREMENT_BUDGET",
            "total_cost_aed": str(total_cost), "available_aed": str(available),
            "detail": f"Requisition needs {total_cost} AED; only {available} AED of "
                      f"procurement budget remains",
        }

    return {
        "viable": True,
        "supplier_id": supplier["supplier_id"],
        "supplier": supplier["supplier_name"],
        "shortage_units": units,
        "order_units": order_units,
        "moq": supplier["moq"],
        "moq_applied": order_units > units,
        "unit_cost_aed": str(supplier["unit_cost_aed"]),
        "total_cost_aed": str(total_cost),
        "lead_time_days": supplier["lead_time_days"],
        "expected_arrival": str(expected_arrival),
        "required_by": str(required_by),
        "eiv_after_procurement_aed": str(remaining_eiv),
        "detail": (
            f"{supplier['supplier_name']} can deliver {order_units} units "
            f"({'MOQ-rounded from ' + str(units) if order_units > units else 'exact'}) "
            f"for {total_cost} AED, arriving {expected_arrival} — "
            f"{(required_by - expected_arrival).days} day(s) before it is needed"
        ),
    }


async def draft_requisitions(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    shortages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Turn a list of shortages into AGGREGATED requisition rows.

    `shortages` items: {store_id, item_id, units, required_by, expected_eiv_aed}

    Aggregation happens here, before any row is written: multiple customer-level
    shortages for the same (store, item, date) collapse into one requisition.
    """
    aggregated: Dict[tuple, Dict[str, Any]] = {}
    for shortage in shortages:
        key = (int(shortage["store_id"]), int(shortage["item_id"]),
               str(shortage["required_by"]))
        bucket = aggregated.setdefault(key, {
            "store_id": int(shortage["store_id"]),
            "item_id": int(shortage["item_id"]),
            "required_by": shortage["required_by"],
            "units": 0, "expected_eiv_aed": ZERO,
        })
        bucket["units"] += int(shortage["units"])
        bucket["expected_eiv_aed"] = money(
            bucket["expected_eiv_aed"] + money(shortage.get("expected_eiv_aed", 0)))

    created: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    import json

    for bucket in aggregated.values():
        required_by = bucket["required_by"]
        if isinstance(required_by, str):
            required_by = date.fromisoformat(required_by)

        assessment = await assess(
            db, tenant_id=tenant_id, item_id=bucket["item_id"], units=bucket["units"],
            required_by=required_by, expected_eiv_aed=bucket["expected_eiv_aed"])

        if not assessment["viable"]:
            rejected.append({**assessment, "store_id": bucket["store_id"],
                             "item_id": bucket["item_id"]})
            continue

        row = (await db.execute(
            text("""INSERT INTO flywheel_procurement_requisitions
                       (tenant_id, campaign_id, store_id, item_id, supplier_id,
                        shortage_units, order_units, unit_cost_aed, total_cost_aed,
                        lead_time_days, required_by, expected_arrival, status, justification)
                    VALUES (:t, :c, :s, :i, :sup, :short, :order, :uc, :tc,
                            :lt, :req, :arr, 'draft', CAST(:j AS JSONB))
                    RETURNING id"""),
            {"t": tenant_id, "c": campaign_id, "s": bucket["store_id"],
             "i": bucket["item_id"], "sup": assessment["supplier_id"],
             "short": bucket["units"], "order": assessment["order_units"],
             "uc": assessment["unit_cost_aed"], "tc": assessment["total_cost_aed"],
             "lt": assessment["lead_time_days"], "req": required_by,
             "arr": date.fromisoformat(assessment["expected_arrival"]),
             "j": json.dumps(assessment)},
        )).fetchone()

        created.append({
            "requisition_id": int(row[0]),
            "store_id": bucket["store_id"], "item_id": bucket["item_id"],
            "order_units": assessment["order_units"],
            "total_cost_aed": assessment["total_cost_aed"],
            "expected_arrival": assessment["expected_arrival"],
            "supplier": assessment["supplier"],
        })

    total = money(sum(money(r["total_cost_aed"]) for r in created)) if created else ZERO
    logger.info("flywheel.procurement campaign=%s drafted=%s rejected=%s total=%s",
                campaign_id, len(created), len(rejected), total)
    return {
        "requisitions": created,
        "rejected": rejected,
        "total_cost_aed": str(total),
        "aggregated_from": len(shortages),
        "aggregated_to": len(aggregated),
    }


async def convert_to_purchase_order(
    db: AsyncSession, *, tenant_id: int, requisition_id: int,
    actor_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Turn an APPROVED requisition into a draft PO in the existing tables.

    Reuses `purchase_orders` / `purchase_order_lines` rather than inventing a
    Flywheel-specific PO, so procurement staff see Flywheel-originated orders in the
    workflow they already use. `source = 'flywheel_campaign'` marks the origin.

    Refuses unless the requisition is approved — this is the gate that stops a
    campaign committing cash without sign-off.
    """
    row = (await db.execute(
        text("""SELECT status, supplier_id, item_id, order_units, unit_cost_aed,
                       total_cost_aed, expected_arrival, campaign_id, purchase_order_id
                  FROM flywheel_procurement_requisitions
                 WHERE id = :r AND tenant_id = :t FOR UPDATE"""),
        {"r": requisition_id, "t": tenant_id},
    )).fetchone()
    if not row:
        raise ValueError(f"Requisition {requisition_id} not found")

    status, supplier_id, item_id, units, unit_cost, total_cost, arrival, campaign_id, existing_po = row

    # Idempotent: already converted → return the original PO, do not create a second.
    if existing_po:
        return {"purchase_order_id": int(existing_po), "created": False,
                "detail": "Requisition was already converted"}

    if status != "approved":
        raise ValueError(
            f"Requisition {requisition_id} is '{status}' — only an approved "
            f"requisition may become a purchase order")

    # `purchase_orders` has no expected_date column — the expected arrival lives
    # on the Flywheel requisition and is restated in the PO notes so a buyer
    # reading the PO in the existing procurement UI still sees the date the
    # campaign is counting on.
    po_number = f"FLYWHEEL-{campaign_id}-{requisition_id}"
    po = (await db.execute(
        text("""INSERT INTO purchase_orders
                   (tenant_id, supplier_id, po_number, status, total_amount,
                    currency, source, notes, created_by)
                VALUES (:t, :sup, :num, 'draft', :amt, 'AED', 'flywheel_campaign',
                        :notes, :actor)
                RETURNING id"""),
        {"t": tenant_id, "sup": supplier_id, "num": po_number, "amt": total_cost,
         "notes": f"Auto-drafted by Flywheel campaign {campaign_id} from requisition "
                  f"{requisition_id}. Required by {arrival} to serve the campaign.",
         "actor": actor_user_id},
    )).fetchone()
    po_id = int(po[0])

    # Real column name is `po_id`, not `purchase_order_id`.
    await db.execute(
        text("""INSERT INTO purchase_order_lines
                   (po_id, item_id, quantity, unit_cost, line_total)
                VALUES (:po, :i, :q, :uc, :lt)"""),
        {"po": po_id, "i": item_id, "q": units, "uc": unit_cost, "lt": total_cost},
    )

    await db.execute(
        text("""UPDATE flywheel_procurement_requisitions
                   SET status = 'converted_to_po', purchase_order_id = :po,
                       updated_at = now()
                 WHERE id = :r AND tenant_id = :t"""),
        {"po": po_id, "r": requisition_id, "t": tenant_id},
    )

    logger.info("flywheel.procurement requisition=%s → PO %s", requisition_id, po_number)
    return {"purchase_order_id": po_id, "po_number": po_number, "created": True,
            "total_cost_aed": str(money(total_cost))}


async def recommend_transfer(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, to_store_id: int,
    from_store_id: int, item_id: int, units: int, source_surplus: int,
) -> int:
    """Persist an inter-store transfer recommendation (rung c)."""
    row = (await db.execute(
        text("""INSERT INTO flywheel_transfer_recommendations
                   (tenant_id, campaign_id, from_store_id, to_store_id, item_id,
                    units, source_surplus_units, status)
                VALUES (:t, :c, :from, :to, :i, :u, :surplus, 'recommended')
                RETURNING id"""),
        {"t": tenant_id, "c": campaign_id, "from": from_store_id, "to": to_store_id,
         "i": item_id, "u": units, "surplus": source_surplus},
    )).fetchone()
    return int(row[0])
