"""
KPIs API Routes - Key Performance Indicators
Optimized with Redis caching and efficient queries

The computation/cache layer (compute_and_cache_kpis — the reference revenue
implementation — plus its key builder and serializers) lives in
`app.services.kpi_service`; this module keeps the HTTP endpoints and re-exports
the moved names so the pre-split import path (`app.routes.kpis`) stays valid.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional

from app.services.database import get_db
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.auth_deps import get_current_user, get_accessible_store_ids
from app.services.source_adapters import active_external_source, source_cache_tag, external_kpis
from app.services.kpi_service import (  # noqa: F401 — re-exported for backwards compatibility
    _DATE_FIELDS, _serialize_kpi_dates, _parse_kpi_dates, _NEEDS_COST,
    _safe_defaults, kpis_cache_key, compute_and_cache_kpis,
)

router = APIRouter()


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

    # E2-3 margin (30d). NULL — never 0 — when the tenant has loaded no cost, so
    # the UI shows `needs_cost` instead of a fabricated profit figure. The margin
    # is computed only over the revenue we could actually cost (cost_coverage_pct).
    gross_margin_month: Optional[float] = None
    gross_margin_pct: Optional[float] = None
    cost_coverage_pct: Optional[float] = None
    needs_cost: Optional[str] = None


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

    allowed = get_accessible_store_ids(current_user)

    # Served from Redis when warm; otherwise computed and cached under the
    # same tenant/store-scoped key the cache warmer refreshes.
    cached = await get_cached(kpis_cache_key(allowed, tenant_id))
    if cached:
        return KPIResponse(**_parse_kpi_dates(cached))

    data = await compute_and_cache_kpis(db, allowed, tenant_id)
    return KPIResponse(**data)


@router.get("/projection")
async def get_revenue_projection(
    horizon: int = 14,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Forward revenue projection (B1.7) — the forecasting engine valued at the
    average unit price, scoped to the caller's tenant and stores. Drives the
    dashboard's 'projected revenue' card."""
    from app.services.forecast_service import revenue_projection

    horizon = max(7, min(horizon, 60))
    tenant_id = current_user.get('tenant_id') or 1
    allowed = get_accessible_store_ids(current_user)
    return await revenue_projection(db, tenant_id, allowed, horizon)
