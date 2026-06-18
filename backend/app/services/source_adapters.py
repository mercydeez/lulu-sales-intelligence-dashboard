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
