"""
KPIs API Routes - Key Performance Indicators
Optimized with Redis caching and efficient queries
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List

from app.services.database import get_db
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.config import logger
from app.routes.auth import get_current_user, get_accessible_store_ids
from app.services.source_adapters import active_external_source, source_cache_tag, external_kpis

router = APIRouter()


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


class KPIResponse(BaseModel):
    total_historical_records: int
    total_streaming_records: int
    total_sales_today: int
    total_sales_week: int
    total_sales_month: int
    average_daily_sales: float
    total_revenue_today: float
    total_revenue_week: float
    total_revenue_month: float
    average_daily_revenue: float
    unique_stores: int
    unique_items: int
    data_range_start: Optional[date]
    data_range_end: Optional[date]
    last_stream_timestamp: Optional[datetime]
    sales_trend: str  # "up", "down", "stable"
    revenue_trend: str  # "up", "down", "stable"


def _safe_defaults() -> dict:
    return {
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
                COALESCE(SUM(s.sales) FILTER (WHERE s.date = :today), 0)::integer as sales_today,
                COALESCE(SUM(s.sales) FILTER (WHERE s.date >= :week_ago), 0)::integer as sales_week,
                COALESCE(SUM(s.sales) FILTER (WHERE s.date >= :month_ago), 0)::integer as sales_month,

                -- Compute Revenue (units * price)
                COALESCE(SUM(s.sales * i.unit_price_aed) FILTER (WHERE s.date = :today), 0)::numeric as revenue_today,
                COALESCE(SUM(s.sales * i.unit_price_aed) FILTER (WHERE s.date >= :week_ago), 0)::numeric as revenue_week,
                COALESCE(SUM(s.sales * i.unit_price_aed) FILTER (WHERE s.date >= :month_ago), 0)::numeric as revenue_month,

                ROUND(AVG(s.sales)::numeric, 2) as avg_daily_sales,
                ROUND(AVG(s.sales * i.unit_price_aed)::numeric, 2) as avg_daily_revenue,
                COUNT(DISTINCT s.store_id) as unique_stores,
                COUNT(DISTINCT s.item_id) as unique_items,
                MIN(s.date) FILTER (WHERE s.is_streaming = false) as data_start,
                MAX(s.date) FILTER (WHERE s.is_streaming = false) as data_end,
                MAX(s.created_at) FILTER (WHERE s.is_streaming = true) as last_stream,
                COALESCE(SUM(s.sales) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::integer as last_week_sales,
                COALESCE(SUM(s.sales) FILTER (WHERE s.date >= :two_weeks_ago AND s.date < :week_ago), 0)::integer as prev_week_sales,
                COALESCE(SUM(s.sales * i.unit_price_aed) FILTER (WHERE s.date >= :week_ago AND s.date < :today), 0)::numeric as last_week_revenue,
                COALESCE(SUM(s.sales * i.unit_price_aed) FILTER (WHERE s.date >= :two_weeks_ago AND s.date < :week_ago), 0)::numeric as prev_week_revenue
            FROM sales_fact_view s
            JOIN items i ON s.item_id = i.id
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

        response_data = {
            "total_historical_records": row.historical_count or 0,
            "total_streaming_records": row.streaming_count or 0,
            "total_sales_today": row.sales_today or 0,
            "total_sales_week": row.sales_week or 0,
            "total_sales_month": row.sales_month or 0,
            "average_daily_sales": float(row.avg_daily_sales or 0),
            "total_revenue_today": float(row.revenue_today or 0),
            "total_revenue_week": float(row.revenue_week or 0),
            "total_revenue_month": float(row.revenue_month or 0),
            "average_daily_revenue": float(row.avg_daily_revenue or 0),
            "unique_stores": row.unique_stores or 0,
            "unique_items": row.unique_items or 0,
            "data_range_start": row.data_start,
            "data_range_end": row.data_end,
            "last_stream_timestamp": row.last_stream,
            "sales_trend": sales_trend,
            "revenue_trend": revenue_trend
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


@router.get("", response_model=KPIResponse)
async def get_kpis(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Get key performance indicators for the dashboard.
    Served from Redis when warm; otherwise computed and cached.
    """
    # When an external data source is active, the whole dashboard reads from it.
    ext = await active_external_source()
    if ext:
        key = generate_cache_key(f"kpis_{source_cache_tag(ext)}")
        cached = await get_cached(key)
        if cached:
            return KPIResponse(**_parse_kpi_dates(cached))
        data = await external_kpis(ext["connection"], ext["mapping"])
        await set_cached(key, _serialize_kpi_dates(data), CACHE_TTL['kpis'])
        return KPIResponse(**data)

    tenant_id = current_user.get('tenant_id') or 1
    allowed