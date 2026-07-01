"""
UAE retail intelligence — seasonality + emirate analytics + branch transfers.

Differentiation a generic forecaster can't match: the UAE retail calendar (Ramadan,
Eid, DSF, back-to-school, National Day) and emirate-level views. The calendar is
REAL reference data; lunar dates (Ramadan/Eid) shift yearly and are marked APPROXIMATE
— confirm against an official UAE source before operational use. Everything else is
computed from the tenant's real data (no fabrication).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Real UAE retail seasons. Lunar dates (Ramadan/Eid) are APPROXIMATE for 2026.
UAE_CALENDAR: List[Dict] = [
    {"key": "ramadan", "name": "Ramadan", "start": "2026-02-18", "end": "2026-03-19",
     "approx": True, "note": "Grocery/F&B surge (iftar/suhoor); daytime footfall shifts to evening.",
     "categories_up": ["dates", "beverages", "dairy", "grains", "cooking"]},
    {"key": "eid_fitr", "name": "Eid Al-Fitr", "start": "2026-03-20", "end": "2026-03-23",
     "approx": True, "note": "Gifting, sweets, apparel and electronics spike.",
     "categories_up": ["confectionery", "apparel", "electronics", "perfume"]},
    {"key": "eid_adha", "name": "Eid Al-Adha", "start": "2026-05-27", "end": "2026-05-30",
     "approx": True, "note": "Meat, fresh produce and gifting demand.",
     "categories_up": ["meat", "produce", "confectionery"]},
    {"key": "summer", "name": "Summer season", "start": "2026-06-01", "end": "2026-08-31",
     "approx": False, "note": "Indoor/mall footfall, beverages, cooling; tourist low season.",
     "categories_up": ["beverages", "water", "ice_cream"]},
    {"key": "back_to_school", "name": "Back to school", "start": "2026-08-15", "end": "2026-09-15",
     "approx": False, "note": "Stationery, kids' apparel, lunch/snack staples.",
     "categories_up": ["stationery", "apparel", "snacks"]},
    {"key": "national_day", "name": "UAE National Day", "start": "2026-12-02", "end": "2026-12-03",
     "approx": False, "note": "Promotions, flags/merchandise, F&B for gatherings.",
     "categories_up": ["confectionery", "beverages", "household"]},
    {"key": "dsf", "name": "Dubai Shopping Festival", "start": "2026-12-15", "end": "2027-01-31",
     "approx": False, "note": "Major discount-driven demand across electronics, apparel, home.",
     "categories_up": ["electronics", "apparel", "home", "perfume"]},
]


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def upcoming_events(today: Optional[date] = None, horizon_days: int = 60) -> List[Dict]:
    """Events currently active or starting within `horizon_days`. Pure."""
    today = today or datetime.now(timezone.utc).date()
    out = []
    for e in UAE_CALENDAR:
        start, end = _d(e["start"]), _d(e["end"])
        if end < today:
            continue
        days_until = (start - today).days
        if days_until <= horizon_days:
            out.append({**e, "active": start <= today <= end,
                        "days_until": max(0, days_until)})
    return sorted(out, key=lambda x: (not x["active"], x["days_until"]))


async def emirate_performance(db: AsyncSession, tenant_id: int, days: int = 90) -> List[Dict]:
    """Revenue (AED) + units by emirate/region over the window. Real data."""
    rows = (await db.execute(text(f"""
        SELECT COALESCE(r.name, 'Unassigned') AS emirate,
               COALESCE(SUM(s.sales), 0)::bigint AS units,
               COALESCE(SUM(s.sales * it.unit_price_aed), 0)::numeric AS revenue_aed,
               COUNT(DISTINCT s.store_id) AS stores
        FROM sales_fact_view s
        JOIN items it ON it.id = s.item_id
        JOIN stores st ON st.id = s.store_id
        LEFT JOIN regions r ON r.id = st.region_id
        WHERE s.tenant_id = :t AND s.date >= (CURRENT_DATE - {int(days)})
        GROUP BY COALESCE(r.name, 'Unassigned')
        ORDER BY revenue_aed DESC
    """), {"t": tenant_id})).mappings().all()
    return [{"emirate": r["emirate"], "units": int(r["units"]),
             "revenue_aed": round(float(r["revenue_aed"]), 2), "stores": int(r["stores"])}
            for r in rows]


async def branch_transfer_suggestions(db: AsyncSession, tenant_id: int, limit: int = 15) -> List[Dict]:
    """For each item, suggest moving stock from an overstocked store to one that's
    out of stock but still selling. Conservative qty = min(excess, ~2 weeks of the
    needy store's demand). Human-approved (suggestion only). Real inventory data."""
    rows = (await db.execute(text("""
        WITH inv AS (
          SELECT i.item_id, i.store_id, i.current_stock, i.average_daily_sales, i.reorder_point,
                 it.name AS item_name, st.name AS store_name
          FROM inventory i
          JOIN items it ON it.id = i.item_id
          JOIN stores st ON st.id = i.store_id
          WHERE it.tenant_id = :t
        ),
        needy AS (  -- out of stock but still selling
          SELECT item_id, store_id, store_name, average_daily_sales
          FROM inv WHERE current_stock = 0 AND average_daily_sales > 0
        ),
        excess AS ( -- well above reorder with slow movement
          SELECT item_id, store_id, store_name, current_stock, average_daily_sales,
                 (current_stock - reorder_point) AS spare
          FROM inv
          WHERE current_stock > reorder_point * 2
            AND (average_daily_sales = 0 OR current_stock / NULLIF(average_daily_sales,0) > 45)
        )
        SELECT n.item_id, MIN(i.item_name) AS item_name,
               e.store_id AS from_store_id, e.store_name AS from_store,
               n.store_id AS to_store_id, n.store_name AS to_store,
               e.spare, n.average_daily_sales AS to_daily
        FROM needy n
        JOIN excess e ON e.item_id = n.item_id AND e.store_id <> n.store_id
        JOIN inv i ON i.item_id = n.item_id AND i.store_id = n.store_id
        GROUP BY n.item_id, e.store_id, e.store_name, n.store_id, n.store_name, e.spare, n.average_daily_sales
        ORDER BY n.average_daily_sales DESC
        LIMIT :lim
    """), {"t": tenant_id, "lim": limit})).mappings().all()
    out = []
    for r in rows:
        qty = int(min(float(r["spare"] or 0), round(float(r["to_daily"] or 0) * 14)))
        if qty <= 0:
            continue
        out.append({
            "item_id": r["item_id"], "item_name": r["item_name"],
            "from_store_id": r["from_store_id"], "from_store": r["from_store"],
            "to_store_id": r["to_store_id"], "to_store": r["to_store"],
            "suggested_qty": qty,
            "reason": f"{r['to_store']} is out of stock but selling ~{round(float(r['to_daily']),1)}/day; "
                      f"{r['from_store']} has spare stock.",
        })
    return out


async def dead_stock_by_emirate(db: AsyncSession, tenant_id: int) -> List[Dict]:
    """Dead-stock value (AED, at retail) grouped by emirate. Real data."""
    rows = (await db.execute(text("""
        SELECT COALESCE(r.name, 'Unassigned') AS emirate,
               COALESCE(SUM(CASE WHEN i.current_stock > 0
                   AND (i.average_daily_sales = 0 OR i.last_sale_date < (CURRENT_DATE - 60))
                   THEN i.current_stock * it.unit_price_aed ELSE 0 END), 0)::numeric AS dead_value,
               COALESCE(SUM(CASE WHEN i.current_stock > 0
                   AND (i.average_daily_sales = 0 OR i.last_sale_date < (CURRENT_DATE - 60))
                   THEN 1 ELSE 0 END), 0) AS dead_skus
        FROM inventory i
        JOIN items it ON it.id = i.item_id
        JOIN stores st ON st.id = i.store_id
        LEFT JOIN regions r ON r.id = st.region_id
        WHERE it.tenant_id = :t
        GROUP BY COALESCE(r.name, 'Unassigned')
        HAVING SUM(CASE WHEN i.current_stock > 0
                   AND (i.average_daily_sales = 0 OR i.last_sale_date < (CURRENT_DATE - 60))
                   THEN 1 ELSE 0 END) > 0
        ORDER BY dead_value DESC
    """), {"t": tenant_id})).mappings().all()
    return [{"emirate": r["emirate"], "dead_value_aed": round(float(r["dead_value"]), 2),
             "dead_skus": int(r["dead_skus"])} for r in rows]
