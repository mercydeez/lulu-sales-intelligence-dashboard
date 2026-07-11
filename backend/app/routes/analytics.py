"""
Analytics API Routes - C-Level Insights and Forecasting
Provides aggregated data for charts and executive dashboards
Optimized with Redis caching for performance
"""
import asyncio

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta
from typing import Optional, List
from pydantic import BaseModel

from app.services.database import get_read_db
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.models.sales import Sale, Store, Item
from app.config import logger
from app.auth_deps import get_current_user, get_accessible_store_ids
from app.services import root_cause as _rc
from app.services.source_adapters import (
    active_external_source,
    source_cache_tag,
    external_store_distribution,
    external_category_breakdown,
    external_top_items,
    external_sales_trend,
)

from app.services.forecast_lab import (  # noqa: F401 — re-exported for backwards compatibility
    MODEL_METRICS_TTL, _INFLIGHT_METRICS_TTL, _inflight_key,
    _try_claim_metrics_warm, _release_metrics_warm, _empty_model_metrics,
    model_metrics_cache_key, _compute_model_metrics_sync,
    compute_and_cache_model_metrics, _warm_model_metrics_in_background,
    store_distribution_cache_key, compute_and_cache_store_distribution,
)

router = APIRouter()


# Response Models
# Convention (see PRODUCT_BUILD_PLAN.md / kpis.py): VALUE metrics are AED revenue
# floats; VOLUME metrics are integer units. These analytics endpoints are all
# revenue (AED), so the money field is `total_revenue: float`, never `total_sales`.
class SalesTrendPoint(BaseModel):
    date: str
    revenue: float  # AED (units × unit_price_aed)
    forecast: Optional[float] = None


class StoreSalesData(BaseModel):
    store_id: int
    store_name: str
    total_revenue: float  # AED
    percentage: float


class ItemSalesData(BaseModel):
    item_id: int
    item_name: str
    category: str
    total_revenue: float  # AED


class CategorySalesData(BaseModel):
    category: str
    total_revenue: float  # AED
    percentage: float


class HourlySalesData(BaseModel):
    hour: int
    sales: int


class AnalyticsSummary(BaseModel):
    sales_trend: List[SalesTrendPoint]
    store_distribution: List[StoreSalesData]
    top_items: List[ItemSalesData]
    category_breakdown: List[CategorySalesData]
    hourly_pattern: List[HourlySalesData]


@router.get("/trend")
async def get_sales_trend(
    days: int = Query(30, ge=7, le=365, description="Number of days for trend"),
    include_forecast: bool = Query(True, description="Include forecast data"),
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get daily sales trend with optional forecasting.
    Returns historical data + 7-day forecast.
    """
    allowed_stores = get_accessible_store_ids(current_user)

    ext = await active_external_source()
    if ext:
        key = generate_cache_key(f"analytics_trend_{source_cache_tag(ext)}", days=days, forecast=include_forecast)
        cached = await get_cached(key)
        if cached:
            return cached
        data = await external_sales_trend(ext["connection"], ext["mapping"], days, include_forecast)
        await set_cached(key, data, CACHE_TTL['analytics'])
        return data

    # Check cache first
    stores_suffix = f"_stores_{','.join(map(str, sorted(allowed_stores)))}" if allowed_stores else "_all"
    cache_key = generate_cache_key(f"analytics_trend{stores_suffix}", days=days, forecast=include_forecast)
    cached = await get_cached(cache_key)
    if cached:
        return cached

    # Get historical daily sales (AED revenue). Explicit tenant filter (defense in
    # depth) so the result is correct even if RLS is disabled.
    tenant_id = current_user.get('tenant_id') or 1
    query = select(
        Sale.date,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.is_streaming == False,
        Sale.tenant_id == tenant_id,
    )

    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))
        
    query = query.group_by(Sale.date).order_by(Sale.date.desc()).limit(days)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    trend_data = []
    sales_values = []
    
    for row in reversed(rows):
        sales_values.append(row.total_sales)
        trend_data.append({
            "date": row.date.isoformat(),
            "sales": float(row.total_sales),
            "forecast": None
        })
    
    # Simple moving average forecast (7-day)
    if include_forecast and len(sales_values) >= 7:
        avg_7d = sum(sales_values[-7:]) / 7
        avg_growth = 0
        if len(sales_values) >= 14:
            prev_avg = sum(sales_values[-14:-7]) / 7
            avg_growth = (avg_7d - prev_avg) / prev_avg if prev_avg > 0 else 0
        
        last_date = rows[0].date if rows else date.today()
        
        for i in range(1, 8):
            forecast_date = last_date + timedelta(days=i)
            # Apply slight growth trend
            forecast_value = int(avg_7d * (1 + avg_growth * 0.3) + (i * avg_growth * avg_7d * 0.1))
            trend_data.append({
                "date": forecast_date.isoformat(),
                "sales": None,
                "forecast": max(0, forecast_value)
            })
    
    response = {"data": trend_data, "days": days}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/stores")
async def get_store_distribution(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get sales distribution by store for pie chart.
    """
    allowed_stores = get_accessible_store_ids(current_user)
    tenant_id = current_user.get('tenant_id') or 1

    ext = await active_external_source()
    if ext:
        key = generate_cache_key(f"analytics_stores_{source_cache_tag(ext)}")
        cached = await get_cached(key)
        if cached:
            return cached
        data = await external_store_distribution(ext["connection"], ext["mapping"])
        await set_cached(key, data, CACHE_TTL['analytics'])
        return data

    cached = await get_cached(store_distribution_cache_key(allowed_stores, tenant_id))
    if cached:
        return cached

    return await compute_and_cache_store_distribution(db, allowed_stores, tenant_id)


@router.get("/top-items")
async def get_top_items(
    limit: int = Query(10, ge=5, le=50),
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get top selling items for bar chart.
    """
    allowed_stores = get_accessible_store_ids(current_user)

    ext = await active_external_source()
    if ext:
        key = generate_cache_key(f"analytics_top_items_{source_cache_tag(ext)}", limit=limit)
        cached = await get_cached(key)
        if cached:
            return cached
        data = await external_top_items(ext["connection"], ext["mapping"], limit)
        await set_cached(key, data, CACHE_TTL['analytics'])
        return data

    # Check cache first
    stores_suffix = f"_stores_{','.join(map(str, sorted(allowed_stores)))}" if allowed_stores else "_all"
    cache_key = generate_cache_key(f"analytics_top_items{stores_suffix}", limit=limit)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    tenant_id = current_user.get('tenant_id') or 1
    query = select(
        Sale.item_id,
        Item.name.label('item_name'),
        Item.category,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(
        Item, Sale.item_id == Item.id
    ).where(Sale.tenant_id == tenant_id)

    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))

    query = query.group_by(
        Sale.item_id, Item.name, Item.category
    ).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc()).limit(limit)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    items_data = []
    for row in rows:
        items_data.append({
            "item_id": row.item_id,
            "item_name": row.item_name,
            "category": row.category,
            "total_revenue": float(row.total_sales)
        })
    
    response = {"data": items_data}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/categories")
async def get_category_breakdown(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get sales breakdown by category for donut chart.
    """
    allowed_stores = get_accessible_store_ids(current_user)

    ext = await active_external_source()
    if ext:
        key = generate_cache_key(f"analytics_categories_{source_cache_tag(ext)}")
        cached = await get_cached(key)
        if cached:
            return cached
        data = await external_category_breakdown(ext["connection"], ext["mapping"])
        await set_cached(key, data, CACHE_TTL['analytics'])
        return data

    # Check cache first
    stores_suffix = f"_stores_{','.join(map(str, sorted(allowed_stores)))}" if allowed_stores else "_all"
    cache_key = generate_cache_key(f"analytics_categories{stores_suffix}")
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    tenant_id = current_user.get('tenant_id') or 1
    query = select(
        Item.category,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(
        Item, Sale.item_id == Item.id
    ).where(Sale.tenant_id == tenant_id)

    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))

    query = query.group_by(
        Item.category
    ).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total = float(sum(row.total_sales for row in rows))
    
    category_data = []
    for row in rows:
        category_data.append({
            "category": row.category,
            "total_revenue": float(row.total_sales),
            "percentage": round((float(row.total_sales) / total * 100) if total > 0 else 0, 2)
        })
    
    response = {"data": category_data, "total": total}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/streaming-trend")
async def get_streaming_trend(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get streaming sales trend (today's live data).
    """
    allowed_stores = get_accessible_store_ids(current_user)
    
    query = select(
        Sale.created_at,
        Sale.store_id,
        Store.name.label('store_name'),
        Sale.item_id,
        Item.name.label('item_name'),
        (Sale.sales * Item.unit_price_aed).label('sales')
    ).join(
        Store, Sale.store_id == Store.id
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.is_streaming == True
    )
    
    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))
        
    query = query.order_by(Sale.created_at.asc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    trend_data = []
    cumulative = 0.0
    for row in rows:
        val = float(row.sales)
        cumulative += val
        trend_data.append({
            "timestamp": row.created_at.isoformat(),
            "store_name": row.store_name,
            "item_name": row.item_name,
            "sales": val,
            "cumulative": round(cumulative, 2)
        })
    
    return {"data": trend_data, "total_streaming": round(cumulative, 2)}


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get comprehensive analytics summary for executive dashboard.
    Four full-history aggregate scans live below (~1s cold) — served through
    the tenant-scoped cache with the caller's store scope + role folded into
    the key, so the analytics tab paints in ms and a cached payload can never
    be served across differently-scoped users (same doctrine as the RAG
    answer cache, services/rag/cache.py).
    """
    allowed_stores = get_accessible_store_ids(current_user)
    key = generate_cache_key(
        "analytics_summary",
        stores=sorted(allowed_stores or []),
        role=current_user.get("role") or "",
    )
    cached = await get_cached(key)
    if cached is not None:
        return cached
    result = await _compute_analytics_summary(db, allowed_stores)
    await set_cached(key, result, CACHE_TTL['analytics'])
    return result


async def _compute_analytics_summary(db: AsyncSession, allowed_stores):
    # Get sales trend (last 30 days)
    trend_query = select(
        Sale.date,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(Item, Sale.item_id == Item.id).where(Sale.is_streaming == False)
    if allowed_stores:
        trend_query = trend_query.where(Sale.store_id.in_(allowed_stores))
    trend_query = trend_query.group_by(Sale.date).order_by(Sale.date.desc()).limit(30)
    trend_result = await db.execute(trend_query)
    trend_rows = trend_result.fetchall()
    
    # Get store distribution
    store_query = select(
        Sale.store_id,
        Store.name.label('store_name'),
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(Store, Sale.store_id == Store.id).join(Item, Sale.item_id == Item.id)
    if allowed_stores:
        store_query = store_query.where(Sale.store_id.in_(allowed_stores))
    store_query = store_query.group_by(Sale.store_id, Store.name).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc())
    store_result = await db.execute(store_query)
    store_rows = store_result.fetchall()
    
    # Get top items
    items_query = select(
        Sale.item_id,
        Item.name.label('item_name'),
        Item.category,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(Item, Sale.item_id == Item.id)
    if allowed_stores:
        items_query = items_query.where(Sale.store_id.in_(allowed_stores))
    items_query = items_query.group_by(Sale.item_id, Item.name, Item.category).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc()).limit(10)
    items_result = await db.execute(items_query)
    items_rows = items_result.fetchall()
    
    # Get category breakdown
    cat_query = select(
        Item.category,
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(Item, Sale.item_id == Item.id)
    if allowed_stores:
        cat_query = cat_query.where(Sale.store_id.in_(allowed_stores))
    cat_query = cat_query.group_by(Item.category).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc())
    cat_result = await db.execute(cat_query)
    cat_rows = cat_result.fetchall()
    
    # Build response
    store_total = float(sum(row.total_sales for row in store_rows))
    cat_total = float(sum(row.total_sales for row in cat_rows))
    
    return {
        "sales_trend": [{"date": row.date.isoformat(), "sales": float(row.total_sales)} for row in reversed(trend_rows)],
        "store_distribution": [
            {"store_id": row.store_id, "store_name": row.store_name, "total_revenue": float(row.total_sales),
             "percentage": round((float(row.total_sales) / store_total * 100) if store_total > 0 else 0, 2)}
            for row in store_rows
        ],
        "top_items": [
            {"item_id": row.item_id, "item_name": row.item_name, "category": row.category, "total_revenue": float(row.total_sales)}
            for row in items_rows
        ],
        "category_breakdown": [
            {"category": row.category, "total_revenue": float(row.total_sales),
             "percentage": round((float(row.total_sales) / cat_total * 100) if cat_total > 0 else 0, 2)}
            for row in cat_rows
        ]
    }


@router.get("/returns-by-category")
async def get_returns_by_category(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get returns (negative sales) breakdown by category for donut chart.
    Shows which product categories have the most returns.
    """
    allowed_stores = get_accessible_store_ids(current_user)
    
    # Query returns (negative sales) grouped by category
    query = select(
        Item.category,
        func.count(Sale.id).label('return_count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('return_value')
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.sales < 0  # Returns have negative sales values
    )
    
    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))
        
    query = query.group_by(
        Item.category
    ).order_by(func.count(Sale.id).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total_count = sum(row.return_count for row in rows)
    total_value = sum(row.return_value for row in rows) if rows else 0
    
    category_data = []
    for row in rows:
        category_data.append({
            "category": row.category,
            "count": row.return_count,
            "value": float(row.return_value),
            "percentage": round((row.return_count / total_count * 100) if total_count > 0 else 0, 2)
        })
    
    return {
        "data": category_data,
        "total_count": total_count,
        "total_value": float(total_value)
    }


@router.get("/returns-by-store")
async def get_returns_by_store(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get returns (negative sales) breakdown by store for bar chart.
    Shows which stores have the most returns.
    """
    allowed_stores = get_accessible_store_ids(current_user)
    
    query = select(
        Store.name.label('store_name'),
        func.count(Sale.id).label('return_count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('return_value')
    ).join(
        Store, Sale.store_id == Store.id
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.sales < 0
    )
    
    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))
        
    query = query.group_by(
        Store.name
    ).order_by(func.count(Sale.id).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total_count = sum(row.return_count for row in rows)
    total_value = sum(row.return_value for row in rows) if rows else 0
    
    store_data = []
    for row in rows:
        store_data.append({
            "store_name": row.store_name,
            "count": row.return_count,
            "value": float(row.return_value),
            "percentage": round((row.return_count / total_count * 100) if total_count > 0 else 0, 2)
        })
    
    return {
        "data": store_data,
        "total_count": total_count,
        "total_value": float(total_value)
    }


@router.get("/returns-summary")
async def get_returns_summary(
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get comprehensive returns summary for the live returns feed component.
    Includes today's returns, all-time stats, and recent return items.
    """
    from datetime import date
    today = date.today()
    allowed_stores = get_accessible_store_ids(current_user)
    
    # Today's returns count and value
    today_query = select(
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('value')
    ).join(Item, Sale.item_id == Item.id).where(
        and_(
            Sale.sales < 0,
            Sale.date == today
        )
    )
    if allowed_stores:
        today_query = today_query.where(Sale.store_id.in_(allowed_stores))
    today_result = await db.execute(today_query)
    today_row = today_result.fetchone()
    
    # All-time returns
    alltime_query = select(
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('value')
    ).join(Item, Sale.item_id == Item.id).where(Sale.sales < 0)
    if allowed_stores:
        alltime_query = alltime_query.where(Sale.store_id.in_(allowed_stores))
    alltime_result = await db.execute(alltime_query)
    alltime_row = alltime_result.fetchone()
    
    # Returns by store (top 5)
    store_query = select(
        Store.name.label('store'),
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('value')
    ).join(Store, Sale.store_id == Store.id).join(Item, Sale.item_id == Item.id).where(Sale.sales < 0)
    if allowed_stores:
        store_query = store_query.where(Sale.store_id.in_(allowed_stores))
    store_query = store_query.group_by(Store.name).order_by(func.count(Sale.id).desc()).limit(5)
    store_result = await db.execute(store_query)
    store_rows = store_result.fetchall()
    
    # Returns by category (top 5)
    cat_query = select(
        Item.category,
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales * Item.unit_price_aed)).label('value')
    ).join(Item, Sale.item_id == Item.id).where(Sale.sales < 0)
    if allowed_stores:
        cat_query = cat_query.where(Sale.store_id.in_(allowed_stores))
    cat_query = cat_query.group_by(Item.category).order_by(func.count(Sale.id).desc()).limit(5)
    cat_result = await db.execute(cat_query)
    cat_rows = cat_result.fetchall()
    
    # Recent return items (last 20)
    recent_query = select(
        Sale.id,
        Store.name.label('store_name'),
        Item.name.label('item_name'),
        Item.category,
        func.abs(Sale.sales).label('quantity'),
        func.abs(Sale.sales * Item.unit_price_aed).label('amount_aed'),
        Sale.created_at
    ).join(Store, Sale.store_id == Store.id).join(Item, Sale.item_id == Item.id).where(
        Sale.sales < 0
    )
    if allowed_stores:
        recent_query = recent_query.where(Sale.store_id.in_(allowed_stores))
    recent_query = recent_query.order_by(Sale.created_at.desc()).limit(20)
    recent_result = await db.execute(recent_query)
    recent_rows = recent_result.fetchall()
    
    return {
        "today_count": today_row.count if today_row.count else 0,
        "today_value": float(today_row.value) if today_row.value else 0.0,
        "all_time_count": alltime_row.count if alltime_row.count else 0,
        "all_time_value": float(alltime_row.value) if alltime_row.value else 0.0,
        "by_store": [{"store": r.store, "count": r.count, "value": float(r.value)} for r in store_rows],
        "by_category": [{"category": r.category, "count": r.count, "value": float(r.value)} for r in cat_rows],
        "recent_items": [
            {
                "id": r.id,
                "store_name": r.store_name,
                "item_name": r.item_name,
                "category": r.category,
                "quantity": int(r.quantity),
                "amount_aed": float(r.amount_aed),
                "timestamp": r.created_at.isoformat() if r.created_at else None
            }
            for r in recent_rows
        ]
    }


@router.get("/model-metrics")
async def get_model_metrics(
    horizon: int = Query(14, ge=7, le=60),
    current_user: dict = Depends(get_current_user),
):
    """
    Forecast Lab metrics (READ-ONLY). Executive view: forecast accuracy + model
    leaderboard. Technical view: forecast-vs-history points, LightGBM feature
    importance, a stockout-risk confusion matrix, and per-store accuracy heatmap.

    Model training happens off the request path: a background trainer
    (services/forecast_trainer.py) keeps the default scope hot, and a cold cache
    for any other scope schedules a one-off background warm. This endpoint never
    trains, so it always returns instantly — with `status: "warming"` on a cold
    scope, which fills in on the next refresh.
    """
    tenant_id = current_user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(current_user)
    cache_key = model_metrics_cache_key(tenant_id, allowed, horizon)

    cached = await get_cached(cache_key)
    if cached:
        return cached

    # Always schedule; the Redis SET NX inside the warm dedupes across workers (and
    # a same-worker double-schedule just no-ops on the second claim). Cheap.
    asyncio.create_task(_warm_model_metrics_in_background(tenant_id, allowed, horizon))
    return _empty_model_metrics("warming")


@router.post("/model-metrics/recompute")
async def recompute_model_metrics(
    horizon: int = Query(14, ge=7, le=60),
    current_user: dict = Depends(get_current_user),
):
    """Real-time retrain: train every forecasting model NOW (synchronously) for
    this caller's scope and return the fresh metrics — the "Retrain now" action in
    the Forecast Lab. Unlike GET (which reads cache + warms in the background),
    this awaits the CPU-bound training (offloaded to a thread inside
    compute_and_cache_model_metrics) so the response carries the just-computed
    result. Bounded by the same horizon guard; the standard rate limiter caps abuse.
    """
    tenant_id = current_user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(current_user)
    try:
        from app.services.database import async_session
        async with async_session() as session:
            result = await compute_and_cache_model_metrics(
                session, tenant_id=tenant_id, allowed=allowed, horizon=horizon)
    except Exception as exc:  # noqa: BLE001 — never 500 the Lab; report honestly
        logger.error(f"[analytics] real-time model recompute failed: {exc!r}")
        raise HTTPException(status_code=503, detail="Model retraining failed — try again shortly")
    return result or _empty_model_metrics("warming")


# =============================================================================
# Root-cause decomposition (E7-4) — the deterministic "Diagnose" layer.
# Explains why a metric changed vs a comparison window, attributing each
# store/category/item/day contributor's share of the total change. Pure SQL over
# the canonical E6-1 view `metric_sales_fact`; no LLM. Logic lives in
# app.services.root_cause so it is unit-testable without the web layer.
# =============================================================================
@router.get("/root-cause", response_model=_rc.RootCauseResult)
async def get_root_cause(
    start_date: date = Query(..., description="Current period start (inclusive)"),
    end_date: date = Query(..., description="Current period end (inclusive)"),
    metric: str = Query("revenue_aed", description="revenue_aed | units_sold | return_units | return_value_aed"),
    comparison: str = Query("previous_period", description="previous_period | previous_week | previous_year"),
    compare_start_date: Optional[date] = Query(None, description="Explicit comparison start (overrides comparison)"),
    compare_end_date: Optional[date] = Query(None, description="Explicit comparison end (overrides comparison)"),
    dimensions: Optional[str] = Query(None, description="CSV of store,category,item,day (default all)"),
    limit: int = Query(10, ge=1, le=50, description="Top-N contributors per dimension"),
    min_abs_delta: Optional[float] = Query(None, description="Drop contributors whose |delta| is below this"),
    store_id: Optional[int] = Query(None, description="Optional single-store filter"),
    category: Optional[str] = Query(None, description="Optional single-category filter"),
    db: AsyncSession = Depends(get_read_db),
    current_user: dict = Depends(get_current_user),
):
    """Decompose the change in a metric between the current and comparison periods.

    Deterministic and tenant-scoped: reads only `metric_sales_fact`, filters the
    caller's tenant, and honours the caller's accessible-store scope. Returns the
    period totals, the total delta, and per-dimension contributors ranked by the
    size of their movement with each one's `share_of_change_pct`.
    """
    try:
        norm = _rc.validate_params(metric, start_date, end_date, comparison, dimensions, limit)
        # Validate the comparison window early so bad compare dates -> 400 (not 500).
        _rc.resolve_comparison_period(
            start_date, end_date, norm["comparison"], compare_start_date, compare_end_date
        )
    except _rc.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tenant_id = current_user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(current_user)

    try:
        return await _rc.decompose(
            db, tenant_id, allowed,
            metric=norm["metric"],
            start_date=start_date,
            end_date=end_date,
            comparison=norm["comparison"],
            dimensions=norm["dimensions"],
            limit=norm["limit"],
            compare_start_date=compare_start_date,
            compare_end_date=compare_end_date,
            store_id=store_id,
            category=category,
            min_abs_delta=min_abs_delta,
        )
    except _rc.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # never leak raw SQL errors to the client
        logger.error(f"root-cause decomposition failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to compute root-cause decomposition")
