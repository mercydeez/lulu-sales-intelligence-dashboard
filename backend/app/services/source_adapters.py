"""
Data source adapters.

Translate the dashboard's canonical analytics queries onto whatever the active
data source is. The built-in synthetic database keeps its existing (warmed,
RBAC-scoped) query path in routes/analytics.py; this module implements the
**external** adapters (Postgres now, Mongo later) used when a non-built-in
source is active.

Canonical mapping (see services/data_sources.py):
    table, date, store, item, quantity, [category], [price]

v1 limitations (documented intentionally):
  * External sources are GLOBAL (one active source for everyone) and are NOT
    filtered by the viewer's accessible_stores — the external store values don't
    map to our store ids. Intended for a super-admin connecting a client DB.
  * One asyncpg connection per request (no pool yet).
"""
from datetime import timedelta
from typing import Optional

import asyncpg

from app.services.data_sources import _plain_dsn, _safe_identifier, get_active_source


def source_cache_tag(source: dict) -> str:
    """Per-source cache namespace so switching sources never serves stale data."""
    return "builtin" if source.get("type") == "builtin" else f"src{source['id']}"


async def active_external_source() -> Optional[dict]:
    """The active source if it's an external (non-built-in) one, else None."""
    src = await get_active_source()
    if src and src.get("type") and src["type"] != "builtin" and src.get("connection"):
        return src
    return None


def _measure(mapping: dict) -> str:
    """Revenue when a price column is mapped, otherwise raw quantity (units)."""
    qty = _safe_identifier(mapping["quantity"])
    price = mapping.get("price")
    return f"SUM({qty} * {_safe_identifier(price)})" if price else f"SUM({qty})"


async def _fetch(connection: str, sql: str):
    conn = await asyncpg.connect(dsn=_plain_dsn(connection), timeout=8)
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


async def external_store_distribution(connection: str, mapping: dict) -> dict:
    table = _safe_identifier(mapping["table"])
    store = _safe_identifier(mapping["store"])
    sql = (
        f"SELECT {store} AS store, {_measure(mapping)} AS total "
        f"FROM {table} GROUP BY {store} ORDER BY total DESC"
    )
    rows = await _fetch(connection, sql)
    total = float(sum((r["total"] or 0) for r in rows))
    data = [
        {
            "store_id": i + 1,
            "store_name": str(r["store"]),
            "total_sales": float(r["total"] or 0),
            "percentage": round((float(r["total"] or 0) / total * 100) if total > 0 else 0, 2),
        }
        for i, r in enumerate(rows)
    ]
    return {"data": data, "total": total}


async def external_category_breakdown(connection: str, mapping: dict) -> dict:
    category = mapping.get("category")
    if not category:
        return {"data": [], "total": 0}
    table = _safe_identifier(mapping["table"])
    cat = _safe_identifier(category)
    sql = (
        f"SELECT {cat} AS category, {_measure(mapping)} AS total "
        f"FROM {table} GROUP BY {cat} ORDER BY total DESC"
    )
    rows = await _fetch(connection, sql)
    total = float(sum((r["total"] or 0) for r in rows))
    data = [
        {
            "category": str(r["category"]),
            "total_sales": float(r["total"] or 0),
            "percentage": round((float(r["total"] or 0) / total * 100) if total > 0 else 0, 2),
        }
        for r in rows
    ]
    return {"data": data, "total": total}


async def external_sales_trend(connection: str, mapping: dict, days: int, include_forecast: bool) -> dict:
    """Daily measure trend over the most recent `days`, + the same 7-day
    moving-average forecast the built-in trend uses. Mirrors /analytics/trend."""
    table = _safe_identifier(mapping["table"])
    datec = f"CAST({_safe_identifier(mapping['date'])} AS date)"
    sql = (
        f"SELECT {datec} AS d, {_measure(mapping)} AS total "
        f"FROM {table} GROUP BY {datec} ORDER BY d DESC LIMIT {int(days)}"
    )
    rows = list(reversed(await _fetch(connection, sql)))  # ascending by date

    trend_data = []
    sales_values = []
    for r in rows:
        val = float(r["total"] or 0)
        sales_values.append(val)
        trend_data.append({"date": r["d"].isoformat(), "sales": val, "forecast": None})

    if include_forecast and len(sales_values) >= 7:
        avg_7d = sum(sales_values[-7:]) / 7
        avg_growth = 0.0
        if len(sales_values) >= 14:
            prev_avg = sum(sales_values[-14:-7]) / 7
            avg_growth = (avg_7d - prev_avg) / prev_avg if prev_avg > 0 else 0.0
        last_date = rows[-1]["d"]
        for i in range(1, 8):
            fdate = last_date + timedelta(days=i)
            fval = int(avg_7d * (1 + avg_growth * 0.3) + (i * avg_growth * avg_7d * 0.1))
            trend_data.append({"date": fdate.isoformat(), "sales": None, "forecast": max(0, fval)})

    return {"data": trend_data, "days": days}


def _empty_kpis() -> dict:
    return {
        "total_historical_records": 0, "total_streaming_records": 0,
        "total_sales_today": 0, "total_sales_week": 0, "total_sales_month": 0,
        "average_daily_sales": 0.0, "total_revenue_today": 0.0,
        "total_revenue_week": 0.0, "total_revenue_month": 0.0,
        "average_daily_revenue": 0.0, "unique_stores": 0, "unique_items": 0,
        "data_range_start": None, "data_range_end": None,
        "last_stream_timestamp": None, "sales_trend": "stable", "revenue_trend": "stable",
    }


async def external_kpis(connection: str, mapping: dict) -> dict:
    """KPI headline numbers for an external source.

    The client's data can be any date range, so 'today/week/month' are measured
    relative to the data's own latest date (its max date = 'today') rather than
    the real calendar — otherwise every card would read zero. Units come from the
    quantity column; revenue uses price when mapped, else equals units.
    """
    table = _safe_identifier(mapping["table"])
    datec = f"CAST({_safe_identifier(mapping['date'])} AS date)"
    qty = _safe_identifier(mapping["quantity"])
    store = _safe_identifier(mapping["store"])
    item = _safe_identifier(mapping["item"])
    price = mapping.get("price")
    meas = _measure(mapping)  # SUM(qty[*price])
    avg_r = f"AVG({qty} * {_safe_identifier(price)})" if price else f"AVG({qty})"

    conn = await asyncpg.connect(dsn=_plain_dsn(connection), timeout=8)
    try:
        maxd = await conn.fetchval(f"SELECT MAX({datec}) FROM {table}")
        if maxd is None:
            return _empty_kpis()
        row = await conn.fetchrow(
            f"""
            SELECT
              MIN({datec}) AS data_start,
              COUNT(*) AS total_records,
              COUNT(DISTINCT {store}) AS unique_stores,
              COUNT(DISTINCT {item}) AS unique_items,
              COALESCE(SUM({qty}) FILTER (WHERE {datec} = $1), 0) AS q_today,
              COALESCE(SUM({qty}) FILTER (WHERE {datec} > $1 - 7), 0) AS q_week,
              COALESCE(SUM({qty}) FILTER (WHERE {datec} > $1 - 30), 0) AS q_month,
              COALESCE({meas} FILTER (WHERE {datec} = $1), 0) AS r_today,
              COALESCE({meas} FILTER (WHERE {datec} > $1 - 7), 0) AS r_week,
              COALESCE({meas} FILTER (WHERE {datec} > $1 - 30), 0) AS r_month,
              COALESCE({avg_r}, 0) AS avg_r,
              COALESCE(AVG({qty}), 0) AS avg_q,
              COALESCE(SUM({qty}) FILTER (WHERE {datec} > $1 - 14 AND {datec} <= $1 - 7), 0) AS prev_week_q,
              COALESCE({meas} FILTER (WHERE {datec} > $1 - 14 AND {datec} <= $1 - 7), 0) AS prev_week_r
            FROM {table}
            """,
            maxd,
        )
    finally:
        await conn.close()

    def _trend(curr: float, prev: float) -> str:
        if prev and prev > 0:
            change = (curr - prev) / prev
            return "up" if change > 0.05 else "down" if change < -0.05 else "stable"
        return "stable"

    return {
        "total_historical_records": int(row["total_records"] or 0),
        "total_streaming_records": 0,
        "total_sales_today": int(row["q_today"] or 0),
        "total_sales_week": int(row["q_week"] or 0),
        "total_sales_month": int(row["q_month"] or 0),
        "average_daily_sales": float(row["avg_q"] or 0),
        "total_revenue_today": float(row["r_today"] or 0),
        "total_revenue_week": float(row["r_week"] or 0),
        "total_revenue_month": float(row["r_month"] or 0),
        "average_daily_revenue": float(row["avg_r"] or 0),
        "unique_stores": int(row["unique_stores"] or 0),
        "unique_items": int(row["unique_items"] or 0),
        "data_range_start": row["data_start"],
        "data_range_end": maxd,
        "last_stream_timestamp": None,
        "sales_trend": _trend(float(row["q_week"] or 0), float(row["prev_week_q"] or 0)),
        "revenue_trend": _trend(float(row["r_week"] or 0), float(row["prev_week_r"] or 0)),
    }


async def external_top_items(connection: str, mapping: dict, limit: int) -> dict:
    table = _safe_identifier(mapping["table"])
    item = _safe_identifier(mapping["item"])
    category = mapping.get("category")
    cat_select = f"{_safe_identifier(category)} AS category, " if category else ""
    cat_group = f", {_safe_identifier(category)}" if category else ""
    sql = (
        f"SELECT {item} AS item, {cat_select}{_measure(mapping)} AS total "
        f"FROM {table} GROUP BY {item}{cat_group} ORDER BY total DESC LIMIT {int(limit)}"
    )
    rows = await _fetch(connection, sql)
    data = [
        {
            "item_id": i + 1,
            "item_name": str(r["item"]),
            "category": str(r["category"]) if category else "",
            "total_sales": float(r["total"] or 0),
        }
        for i, r in enumerate(rows)
    ]
    return {"data": data}
