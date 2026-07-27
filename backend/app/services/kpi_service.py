"""
KPI computation & cache layer.

WHY THIS MODULE EXISTS (dependency direction): `compute_and_cache_kpis` is the
reference revenue/units implementation (see CLAUDE.md "units vs currency") and
is shared by the KPI route, the public API, and the cache warmer. It used to
live in `app.routes.kpis`, which made two *services* (cache_warmer) and another
route (public_api) import a route module. It now lives here, below the web
layer; `app.routes.kpis` re-exports every name so the old import path keeps
working.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from typing import Optional, List

from app.services.cache import set_cached, generate_cache_key, CACHE_TTL
from app.config import logger


_DATE_FIELDS = ("data_range_start", "data_range_end")


def _serialize_kpi_dates(data: dict) -> dict:
    """Copy with date/datetime values turned into ISO strings (for caching)."""
    out = data.copy()
    for f in _DATE_FIELDS:
        if out.get(f) is not None and not isinstance(out[f], str):
            out[f] = out[f].isoformat()
    if out.get("last_stream_timestamp") is not None and not isinstance(out["last_stream_timestamp"], str):
        out["last_stream_timestamp"] = out["last_stream_timestamp"].isoformat()
    return out


def _parse_kpi_dates(cached: dict) -> dict:
    """Inverse of _serialize_kpi_dates — ISO strings back to date/datetime."""
    if cached.get("data_range_start"):
        cached["data_range_start"] = date.fromisoformat(cached["data_range_start"])
    if cached.get("data_range_end"):
        cached["data_range_end"] = date.fromisoformat(cached["data_range_end"])
    if cached.get("last_stream_timestamp"):
        cached["last_stream_timestamp"] = datetime.fromisoformat(cached["last_stream_timestamp"])
    return cached


# Kept identical to services/roi.py so every cost-gated surface says the same thing.
_NEEDS_COST = "unit cost — import item costs, or an inventory file with a cost column"


def _safe_defaults() -> dict:
    return {
        "gross_margin_month": None,
        "gross_margin_pct": None,
        "cost_coverage_pct": None,
        "needs_cost": _NEEDS_COST,
        "total_historical_records": 0,
        "total_streaming_records": 0,
        "total_sales_today": 0,
        "total_sales_week": 0,
        "total_sales_month": 0,
        "average_daily_sales": 0.0,
        "total_revenue_today": 0.0,
        "total_revenue_week": 0.0,
        "total_revenue_month": 0.0,
        "average_daily_revenue": 0.0,
        "unique_stores": 0,
        "unique_items": 0,
        "data_range_start": None,
        "data_range_end": None,
        "last_stream_timestamp": None,
        "sales_trend": "stable",
        "revenue_trend": "stable",
    }


def kpis_cache_key(allowed_stores: Optional[List[int]], tenant_id: int = 1) -> str:
    """Tenant- and user-aware cache key for a KPI scope (empty/None => all stores)."""
    scope = f"kpis_t{tenant_id}"
    if allowed_stores:
        scope += f"_stores_{','.join(map(str, sorted(allowed_stores)))}"
    else:
        scope += "_all"
    return generate_cache_key(scope)


async def compute_and_cache_kpis(db: AsyncSession, allowed_stores: Optional[List[int]], tenant_id: int = 1) -> dict:
    """
    Run the KPI aggregation, store it in Redis under the scope's key, and return
    it as a dict. Shared by the route (on cache miss) and the cache warmer so the
    warmer always refreshes the exact key the route reads. On query failure it
    returns safe defaults and does NOT cache them.
    """
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    two_weeks_ago = today - timedelta(days=14)

    try:
        query_sql = """
            SELECT
                COUNT(*) FILTER (WHERE s.is_streaming = false) as historical_count,
                COUNT(*) FILTER (WHERE s.is_streaming = true) as streaming_count,
                COALESCE(SUM(s.units) FILTER (WHERE s.date = :today), 0)::integer as sales_today,
                -- "Last 7 days" = 7 COMPLETED days, excluding today. This used to
                -- include today, so the landing page showed two different 7-day
                -- figures side by side: the Sage hero (briefing.py, which excludes
                -- today) said AED 3,050,411 while the card beside it said
                -- AED 3,521,075 -- the gap being today's partial sales. The trend
                -- comparison below already excluded today, so this was also
                -- internally inconsistent. Excluding today additionally keeps the
                -- number stable while presenting instead of drifting as the live
                -- generator writes.
                COALESCE(SUM(s.units) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::integer as sales_week,
                COALESCE(SUM(s.units) FILTER (WHERE s.date >= :month_ago), 0)::integer as sales_month,

                -- Revenue = units * unit_price_aed, defined once in metric_sales_fact (E6-1)
                COALESCE(SUM(s.revenue_aed) FILTER (WHERE s.date = :today), 0)::numeric as revenue_today,
                COALESCE(SUM(s.revenue_aed) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::numeric as revenue_week,
                COALESCE(SUM(s.revenue_aed) FILTER (WHERE s.date >= :month_ago), 0)::numeric as revenue_month,

                -- TRUE per-DAY averages: total over the window / number of days in it.
                -- These were AVG(s.units) / AVG(s.revenue_aed), which average a single
                -- store-item-day ROW (~516 rows/day), not a day. The dashboard renders
                -- them as "Avg: N units/day" and "AED N/day", so that understated daily
                -- volume by roughly 500x (52 units/day shown against ~26,866 actual).
                -- Window is the last 30 completed days: it matches the month figures on
                -- the same card, and excluding today avoids a partial day dragging the
                -- mean down mid-demo.
                COALESCE(
                    SUM(s.units) FILTER (WHERE s.date >= :month_ago AND s.date < :today)::numeric
                    / NULLIF(COUNT(DISTINCT s.date) FILTER (WHERE s.date >= :month_ago AND s.date < :today), 0),
                    0
                )::numeric(18,2) as avg_daily_sales,
                COALESCE(
                    SUM(s.revenue_aed) FILTER (WHERE s.date >= :month_ago AND s.date < :today)
                    / NULLIF(COUNT(DISTINCT s.date) FILTER (WHERE s.date >= :month_ago AND s.date < :today), 0),
                    0
                )::numeric(18,2) as avg_daily_revenue,
                COUNT(DISTINCT s.store_id) as unique_stores,
                COUNT(DISTINCT s.item_id) as unique_items,
                MIN(s.date) FILTER (WHERE s.is_streaming = false) as data_start,
                MAX(s.date) FILTER (WHERE s.is_streaming = false) as data_end,
                MAX(s.created_at) FILTER (WHERE s.is_streaming = true) as last_stream,
                COALESCE(SUM(s.units) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::integer as last_week_sales,
                COALESCE(SUM(s.units) FILTER (WHERE s.date >= :two_weeks_ago AND s.date < :week_ago), 0)::integer as prev_week_sales,
                COALESCE(SUM(s.revenue_aed) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::numeric as last_week_revenue,
                COALESCE(SUM(s.revenue_aed) FILTER (WHERE s.date >= :two_weeks_ago AND s.date < :week_ago), 0)::numeric as prev_week_revenue
            FROM metric_sales_fact s
        """
        params = {
            "today": today,
            "week_ago": week_ago,
            "month_ago": month_ago,
            "two_weeks_ago": two_weeks_ago,
            "tenant_id": tenant_id,
        }
        # Always scope to the caller's tenant; store scope narrows further.
        query_sql += " WHERE s.tenant_id = :tenant_id"
        if allowed_stores:
            query_sql += " AND s.store_id = ANY(:allowed_stores)"
            params["allowed_stores"] = allowed_stores

        result = await db.execute(text(query_sql), params)
        row = result.fetchone()

        # Calculate trend
        if row.prev_week_sales and row.prev_week_sales > 0:
            change = (row.last_week_sales - row.prev_week_sales) / row.prev_week_sales
            if change > 0.05:
                sales_trend = "up"
            elif change < -0.05:
                sales_trend = "down"
            else:
                sales_trend = "stable"
        else:
            sales_trend = "stable"

        # Calculate revenue trend
        if row.prev_week_revenue and row.prev_week_revenue > 0:
            change = (row.last_week_revenue - row.prev_week_revenue) / row.prev_week_revenue
            if change > 0.05:
                revenue_trend = "up"
            elif change < -0.05:
                revenue_trend = "down"
            else:
                revenue_trend = "stable"
        else:
            revenue_trend = "stable"

        # --- E2-3 margin (30d), from metric_margin_fact: each sale costed at the
        # price that was in effect on ITS OWN date. cogs_aed is NULL where no cost
        # period covers the sale, and those rows are excluded from both sums — so
        # margin is over costed revenue only, never diluted by a silent zero.
        margin_sql = """
            SELECT COALESCE(SUM(m.gross_margin_aed), 0)::numeric AS gross_margin_month,
                   COALESCE(SUM(m.revenue_aed), 0)::numeric      AS costed_revenue_month,
                   COUNT(*) FILTER (WHERE m.cogs_aed IS NOT NULL) AS costed_rows
            FROM metric_margin_fact m
            WHERE m.tenant_id = :tenant_id
              AND m.date >= :month_ago
              AND m.cogs_aed IS NOT NULL
        """
        if allowed_stores:
            margin_sql += " AND m.store_id = ANY(:allowed_stores)"
        m = (await db.execute(text(margin_sql), params)).fetchone()

        revenue_month = float(row.revenue_month or 0)
        gross_margin_month = gross_margin_pct = cost_coverage_pct = None
        needs_cost = _NEEDS_COST
        if m and m.costed_rows:
            costed_revenue = float(m.costed_revenue_month or 0)
            if costed_revenue > 0:
                gross_margin_month = round(float(m.gross_margin_month or 0), 2)
                gross_margin_pct = round(100.0 * gross_margin_month / costed_revenue, 1)
                cost_coverage_pct = (
                    round(100.0 * costed_revenue / revenue_month, 1) if revenue_month > 0 else None
                )
                needs_cost = None

        response_data = {
            "total_historical_records": row.historical_count or 0,
            "total_streaming_records": row.streaming_count or 0,
            "total_sales_today": row.sales_today or 0,
            "total_sales_week": row.sales_week or 0,
            "total_sales_month": row.sales_month or 0,
            "average_daily_sales": float(row.avg_daily_sales or 0),
            "total_revenue_today": float(row.revenue_today or 0),
            "total_revenue_week": float(row.revenue_week or 0),
            "total_revenue_month": revenue_month,
            "average_daily_revenue": float(row.avg_daily_revenue or 0),
            "unique_stores": row.unique_stores or 0,
            "unique_items": row.unique_items or 0,
            "data_range_start": row.data_start,
            "data_range_end": row.data_end,
            "last_stream_timestamp": row.last_stream,
            "sales_trend": sales_trend,
            "revenue_trend": revenue_trend,
            "gross_margin_month": gross_margin_month,
            "gross_margin_pct": gross_margin_pct,
            "cost_coverage_pct": cost_coverage_pct,
            "needs_cost": needs_cost,
        }

        # Cache result (serialize dates for caching)
        cache_data = response_data.copy()
        if cache_data['data_range_start']:
            cache_data['data_range_start'] = cache_data['data_range_start'].isoformat()
        if cache_data['data_range_end']:
            cache_data['data_range_end'] = cache_data['data_range_end'].isoformat()
        if cache_data['last_stream_timestamp']:
            cache_data['last_stream_timestamp'] = cache_data['last_stream_timestamp'].isoformat()

        await set_cached(kpis_cache_key(allowed_stores, tenant_id), cache_data, CACHE_TTL['kpis'])

        return response_data

    except Exception as e:
        logger.error(f"KPIs query error: {e}")
        return _safe_defaults()
