"""
Postgres source adapters (the live-verifiable engines).

* InternalPostgresAdapter — the app's own DB. Reuses Sage's least-privilege
  sage_ro executor against the real sage_* views.
* ExternalPostgresAdapter — a customer-connected Postgres. The source only has a
  raw table + a canonical `mapping` (date/store/item/quantity/category/price), so
  we synthesize the sage_* relations as CTEs from that mapping and run the SAME
  guard-approved canonical SQL on top — read-only, with a statement timeout.

Both speak the canonical contract, so the orchestrator treats them identically.
"""
from __future__ import annotations

import datetime
import decimal
from typing import List, Optional

from app.config import logger
from app.services.data_sources import _plain_dsn, _safe_identifier
from app.services.nl2sql.executor import execute_sage_sql
from ..base import SourceAdapter, SourceDescriptor


def _coerce(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


class InternalPostgresAdapter(SourceAdapter):
    """The app DB — delegates to the existing sage_ro read-only executor."""

    async def run_canonical(self, canonical_sql: str, tenant_id: int,
                            allowed_stores: Optional[List[int]] = None) -> List[dict]:
        return await execute_sage_sql(canonical_sql, tenant_id, allowed_stores)


def build_canonical_ctes(mapping: dict) -> str:
    """Synthesize the sage_* relations from a data-source mapping as a WITH prefix,
    so canonical SQL written for the app DB runs unchanged against the foreign table.
    Missing canonical columns are filled with safe NULL/defaults so any canonical
    query still type-checks."""
    table = _safe_identifier(mapping["table"])
    date_c = _safe_identifier(mapping["date"])
    store_c = _safe_identifier(mapping["store"])
    item_c = _safe_identifier(mapping["item"])
    qty_c = _safe_identifier(mapping["quantity"])
    cat_c = _safe_identifier(mapping["category"]) if mapping.get("category") else None
    price_c = _safe_identifier(mapping["price"]) if mapping.get("price") else None

    category_expr = cat_c if cat_c else "'Uncategorized'"
    price_expr = price_c if price_c else "0"
    revenue_expr = f"({qty_c} * {price_expr})::numeric"

    return f"""
WITH sage_sales AS (
    SELECT
        NULL::bigint        AS id,
        {date_c}            AS date,
        NULL::int           AS store_id,
        {store_c}::text     AS store_name,
        NULL::int           AS item_id,
        {item_c}::text      AS item_name,
        {category_expr}::text AS category,
        {qty_c}::int        AS units,
        {price_expr}::numeric AS unit_price_aed,
        {revenue_expr}      AS revenue_aed,
        FALSE               AS is_streaming,
        ({qty_c} < 0)       AS is_return
    FROM {table}
),
sage_daily_sales AS (
    SELECT date, SUM(units) AS units, SUM(revenue_aed) AS revenue_aed, COUNT(*) AS line_count
    FROM sage_sales GROUP BY date
),
sage_store_performance AS (
    SELECT store_id, store_name, SUM(units) AS units, SUM(revenue_aed) AS revenue_aed, COUNT(*) AS line_count
    FROM sage_sales GROUP BY store_id, store_name
),
sage_category_performance AS (
    SELECT category, SUM(units) AS units, SUM(revenue_aed) AS revenue_aed
    FROM sage_sales GROUP BY category
),
sage_item_performance AS (
    SELECT item_id, item_name, category, MAX(unit_price_aed) AS unit_price_aed,
           SUM(units) AS units, SUM(revenue_aed) AS revenue_aed
    FROM sage_sales GROUP BY item_id, item_name, category
),
sage_stores AS (SELECT DISTINCT store_id, store_name, NULL::text AS location FROM sage_sales),
sage_items  AS (SELECT DISTINCT item_id, item_name, category, unit_price_aed FROM sage_sales)
""".strip()


class ExternalPostgresAdapter(SourceAdapter):
    """A connected customer Postgres, queried through canonical CTEs from its mapping."""

    def __init__(self, descriptor: SourceDescriptor, connection: str, mapping: dict, timeout_ms: int = 5000):
        super().__init__(descriptor)
        self._dsn = _plain_dsn(connection)
        self._mapping = mapping
        self._timeout_ms = timeout_ms

    async def run_canonical(self, canonical_sql: str, tenant_id: int,
                            allowed_stores: Optional[List[int]] = None) -> List[dict]:
        # allowed_stores ignored: a foreign source's synthesized sage_sales has no
        # internal store_id to scope by (see SourceAdapter.run_canonical).
        import asyncpg
        ctes = build_canonical_ctes(self._mapping)
        # canonical_sql is the guard's `SELECT * FROM (<inner>) sage_result LIMIT n`;
        # prepend the synthesized relations so it resolves against this source.
        federated_sql = f"{ctes}\n{canonical_sql}"
        conn = await asyncpg.connect(dsn=self._dsn, timeout=8)
        try:
            await conn.execute(f"SET statement_timeout = {int(self._timeout_ms)}")
            await conn.execute("SET default_transaction_read_only = on")
            rows = await conn.fetch(federated_sql)
            return [{k: _coerce(v) for k, v in dict(r).items()} for r in rows]
        finally:
            await conn.close()
