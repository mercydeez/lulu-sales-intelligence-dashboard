"""
Analytics API Routes - C-Level Insights and Forecasting
Provides aggregated data for charts and executive dashboards
Optimized with Redis caching for performance
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel

from app.services.database import get_db
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.models.sales import Sale, Store, Item
from app.config import logger

router = APIRouter()


# Response Models
class SalesTrendPoint(BaseModel):
    date: str
    sales: int
    forecast: Optional[int] = None


class StoreSalesData(BaseModel):
    store_id: int
    store_name: str
    total_sales: int
    percentage: float


class ItemSalesData(BaseModel):
    item_id: int
    item_name: str
    category: str
    total_sales: int


class CategorySalesData(BaseModel):
    category: str
    total_sales: int
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
    db: AsyncSession = Depends(get_db)
):
    """
    Get daily sales trend with optional forecasting.
    Returns historical data + 7-day forecast.
    """
    # Check cache first
    cache_key = generate_cache_key("analytics_trend", days=days, forecast=include_forecast)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    # Get historical daily sales
    query = select(
        Sale.date,
        func.sum(Sale.sales).label('total_sales')
    ).where(
        Sale.is_streaming == False
    ).group_by(Sale.date).order_by(Sale.date.desc()).limit(days)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    trend_data = []
    sales_values = []
    
    for row in reversed(rows):
        sales_values.append(row.total_sales)
        trend_data.append({
            "date": row.date.isoformat(),
            "sales": row.total_sales,
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
    db: AsyncSession = Depends(get_db)
):
    """
    Get sales distribution by store for pie chart.
    """
    # Check cache first
    cache_key = generate_cache_key("analytics_stores")
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    query = select(
        Sale.store_id,
        Store.name.label('store_name'),
        func.sum(Sale.sales).label('total_sales')
    ).join(
        Store, Sale.store_id == Store.id
    ).group_by(
        Sale.store_id, Store.name
    ).order_by(func.sum(Sale.sales).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total = sum(row.total_sales for row in rows)
    
    store_data = []
    for row in rows:
        store_data.append({
            "store_id": row.store_id,
            "store_name": row.store_name,
            "total_sales": row.total_sales,
            "percentage": round((row.total_sales / total * 100) if total > 0 else 0, 2)
        })
    
    response = {"data": store_data, "total": total}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/top-items")
async def get_top_items(
    limit: int = Query(10, ge=5, le=50),
    db: AsyncSession = Depends(get_db)
):
    """
    Get top selling items for bar chart.
    """
    # Check cache first
    cache_key = generate_cache_key("analytics_top_items", limit=limit)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    query = select(
        Sale.item_id,
        Item.name.label('item_name'),
        Item.category,
        func.sum(Sale.sales).label('total_sales')
    ).join(
        Item, Sale.item_id == Item.id
    ).group_by(
        Sale.item_id, Item.name, Item.category
    ).order_by(func.sum(Sale.sales).desc()).limit(limit)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    items_data = []
    for row in rows:
        items_data.append({
            "item_id": row.item_id,
            "item_name": row.item_name,
            "category": row.category,
            "total_sales": row.total_sales
        })
    
    response = {"data": items_data}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/categories")
async def get_category_breakdown(
    db: AsyncSession = Depends(get_db)
):
    """
    Get sales breakdown by category for donut chart.
    """
    # Check cache first
    cache_key = generate_cache_key("analytics_categories")
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    query = select(
        Item.category,
        func.sum(Sale.sales).label('total_sales')
    ).join(
        Item, Sale.item_id == Item.id
    ).group_by(
        Item.category
    ).order_by(func.sum(Sale.sales).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total = sum(row.total_sales for row in rows)
    
    category_data = []
    for row in rows:
        category_data.append({
            "category": row.category,
            "total_sales": row.total_sales,
            "percentage": round((row.total_sales / total * 100) if total > 0 else 0, 2)
        })
    
    response = {"data": category_data, "total": total}
    await set_cached(cache_key, response, CACHE_TTL['analytics'])
    return response


@router.get("/streaming-trend")
async def get_streaming_trend(
    db: AsyncSession = Depends(get_db)
):
    """
    Get streaming sales trend (today's live data).
    """
    query = select(
        Sale.created_at,
        Sale.store_id,
        Store.name.label('store_name'),
        Sale.item_id,
        Item.name.label('item_name'),
        Sale.sales
    ).join(
        Store, Sale.store_id == Store.id
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.is_streaming == True
    ).order_by(Sale.created_at.asc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    trend_data = []
    cumulative = 0
    for row in rows:
        cumulative += row.sales
        trend_data.append({
            "timestamp": row.created_at.isoformat(),
            "store_name": row.store_name,
            "item_name": row.item_name,
            "sales": row.sales,
            "cumulative": cumulative
        })
    
    return {"data": trend_data, "total_streaming": cumulative}


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive analytics summary for executive dashboard.
    """
    # Get sales trend (last 30 days)
    trend_query = select(
        Sale.date,
        func.sum(Sale.sales).label('total_sales')
    ).where(Sale.is_streaming == False).group_by(Sale.date).order_by(Sale.date.desc()).limit(30)
    trend_result = await db.execute(trend_query)
    trend_rows = trend_result.fetchall()
    
    # Get store distribution
    store_query = select(
        Sale.store_id,
        Store.name.label('store_name'),
        func.sum(Sale.sales).label('total_sales')
    ).join(Store, Sale.store_id == Store.id).group_by(Sale.store_id, Store.name).order_by(func.sum(Sale.sales).desc())
    store_result = await db.execute(store_query)
    store_rows = store_result.fetchall()
    
    # Get top items
    items_query = select(
        Sale.item_id,
        Item.name.label('item_name'),
        Item.category,
        func.sum(Sale.sales).label('total_sales')
    ).join(Item, Sale.item_id == Item.id).group_by(Sale.item_id, Item.name, Item.category).order_by(func.sum(Sale.sales).desc()).limit(10)
    items_result = await db.execute(items_query)
    items_rows = items_result.fetchall()
    
    # Get category breakdown
    cat_query = select(
        Item.category,
        func.sum(Sale.sales).label('total_sales')
    ).join(Item, Sale.item_id == Item.id).group_by(Item.category).order_by(func.sum(Sale.sales).desc())
    cat_result = await db.execute(cat_query)
    cat_rows = cat_result.fetchall()
    
    # Build response
    store_total = sum(row.total_sales for row in store_rows)
    cat_total = sum(row.total_sales for row in cat_rows)
    
    return {
        "sales_trend": [{"date": row.date.isoformat(), "sales": row.total_sales} for row in reversed(trend_rows)],
        "store_distribution": [
            {"store_id": row.store_id, "store_name": row.store_name, "total_sales": row.total_sales, 
             "percentage": round((row.total_sales / store_total * 100) if store_total > 0 else 0, 2)}
            for row in store_rows
        ],
        "top_items": [
            {"item_id": row.item_id, "item_name": row.item_name, "category": row.category, "total_sales": row.total_sales}
            for row in items_rows
        ],
        "category_breakdown": [
            {"category": row.category, "total_sales": row.total_sales,
             "percentage": round((row.total_sales / cat_total * 100) if cat_total > 0 else 0, 2)}
            for row in cat_rows
        ]
    }


@router.get("/returns-by-category")
async def get_returns_by_category(
    db: AsyncSession = Depends(get_db)
):
    """
    Get returns (negative sales) breakdown by category for donut chart.
    Shows which product categories have the most returns.
    """
    # Query returns (negative sales) grouped by category
    query = select(
        Item.category,
        func.count(Sale.id).label('return_count'),
        func.sum(func.abs(Sale.sales)).label('return_value')
    ).join(
        Item, Sale.item_id == Item.id
    ).where(
        Sale.sales < 0  # Returns have negative sales values
    ).group_by(
        Item.category
    ).order_by(func.count(Sale.id).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total_count = sum(row.return_count for row in rows)
    total_value = sum(row.return_value for row in rows)
    
    category_data = []
    for row in rows:
        category_data.append({
            "category": row.category,
            "count": row.return_count,
            "value": int(row.return_value),
            "percentage": round((row.return_count / total_count * 100) if total_count > 0 else 0, 2)
        })
    
    return {
        "data": category_data,
        "total_count": total_count,
        "total_value": int(total_value)
    }


@router.get("/returns-by-store")
async def get_returns_by_store(
    db: AsyncSession = Depends(get_db)
):
    """
    Get returns (negative sales) breakdown by store for bar chart.
    Shows which stores have the most returns.
    """
    query = select(
        Store.name.label('store_name'),
        func.count(Sale.id).label('return_count'),
        func.sum(func.abs(Sale.sales)).label('return_value')
    ).join(
        Store, Sale.store_id == Store.id
    ).where(
        Sale.sales < 0
    ).group_by(
        Store.name
    ).order_by(func.count(Sale.id).desc())
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    total_count = sum(row.return_count for row in rows)
    total_value = sum(row.return_value for row in rows)
    
    store_data = []
    for row in rows:
        store_data.append({
            "store_name": row.store_name,
            "count": row.return_count,
            "value": int(row.return_value),
            "percentage": round((row.return_count / total_count * 100) if total_count > 0 else 0, 2)
        })
    
    return {
        "data": store_data,
        "total_count": total_count,
        "total_value": int(total_value)
    }


@router.get("/returns-summary")
async def get_returns_summary(
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive returns summary for the live returns feed component.
    Includes today's returns, all-time stats, and recent return items.
    """
    from datetime import date
    today = date.today()
    
    # Today's returns count and value
    today_query = select(
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales)).label('value')
    ).where(
        and_(
            Sale.sales < 0,
            Sale.date == today
        )
    )
    today_result = await db.execute(today_query)
    today_row = today_result.fetchone()
    
    # All-time returns
    alltime_query = select(
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales)).label('value')
    ).where(Sale.sales < 0)
    alltime_result = await db.execute(alltime_query)
    alltime_row = alltime_result.fetchone()
    
    # Returns by store (top 5)
    store_query = select(
        Store.name.label('store'),
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales)).label('value')
    ).join(Store, Sale.store_id == Store.id).where(Sale.sales < 0).group_by(Store.name).order_by(func.count(Sale.id).desc()).limit(5)
    store_result = await db.execute(store_query)
    store_rows = store_result.fetchall()
    
    # Returns by category (top 5)
    cat_query = select(
        Item.category,
        func.count(Sale.id).label('count'),
        func.sum(func.abs(Sale.sales)).label('value')
    ).join(Item, Sale.item_id == Item.id).where(Sale.sales < 0).group_by(Item.category).order_by(func.count(Sale.id).desc()).limit(5)
    cat_result = await db.execute(cat_query)
    cat_rows = cat_result.fetchall()
    
    # Recent return items (last 20)
    recent_query = select(
        Sale.id,
        Store.name.label('store_name'),
        Item.name.label('item_name'),
        Item.category,
        func.abs(Sale.sales).label('quantity'),
        Sale.created_at
    ).join(Store, Sale.store_id == Store.id).join(Item, Sale.item_id == Item.id).where(
        Sale.sales < 0
    ).order_by(Sale.created_at.desc()).limit(20)
    recent_result = await db.execute(recent_query)
    recent_rows = recent_result.fetchall()
    
    return {
        "today_count": today_row.count if today_row.count else 0,
        "today_value": int(today_row.value) if today_row.value else 0,
        "all_time_count": alltime_row.count if alltime_row.count else 0,
        "all_time_value": int(alltime_row.value) if alltime_row.value else 0,
        "by_store": [{"store": r.store, "count": r.count, "value": int(r.value)} for r in store_rows],
        "by_category": [{"category": r.category, "count": r.count, "value": int(r.value)} for r in cat_rows],
        "recent_items": [
            {
                "id": r.id,
                "store_name": r.store_name,
                "item_name": r.item_name,
                "category": r.category,
                "quantity": int(r.quantity),
                "timestamp": r.created_at.isoformat() if r.created_at else None
            }
            for r in recent_rows
        ]
    }
