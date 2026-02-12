"""
KPIs API Routes - Key Performance Indicators
Optimized with Redis caching and efficient queries
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from typing import Optional

from app.services.database import get_db
from app.models.sales import Sale
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.config import logger

router = APIRouter()


class KPIResponse(BaseModel):
    total_historical_records: int
    total_streaming_records: int
    total_sales_today: int
    total_sales_week: int
    total_sales_month: int
    average_daily_sales: float
    unique_stores: int
    unique_items: int
    data_range_start: Optional[date]
    data_range_end: Optional[date]
    last_stream_timestamp: Optional[datetime]
    sales_trend: str  # "up", "down", "stable"


@router.get("", response_model=KPIResponse)
async def get_kpis(db: AsyncSession = Depends(get_db)):
    """
    Get key performance indicators for the dashboard.
    Optimized with single query and caching.
    """
    # Check cache first
    cache_key = generate_cache_key("kpis")
    cached = await get_cached(cache_key)
    if cached:
        # Parse cached datetime strings back to proper types
        if cached.get('data_range_start'):
            cached['data_range_start'] = date.fromisoformat(cached['data_range_start'])
        if cached.get('data_range_end'):
            cached['data_range_end'] = date.fromisoformat(cached['data_range_end'])
        if cached.get('last_stream_timestamp'):
            cached['last_stream_timestamp'] = datetime.fromisoformat(cached['last_stream_timestamp'])
        return KPIResponse(**cached)
    
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    two_weeks_ago = today - timedelta(days=14)
    
    try:
        # Single optimized query for all KPIs
        result = await db.execute(text("""
            SELECT 
                COUNT(*) FILTER (WHERE is_streaming = false) as historical_count,
                COUNT(*) FILTER (WHERE is_streaming = true) as streaming_count,
                COALESCE(SUM(sales) FILTER (WHERE date = :today), 0)::integer as sales_today,
                COALESCE(SUM(sales) FILTER (WHERE date >= :week_ago), 0)::integer as sales_week,
                COALESCE(SUM(sales) FILTER (WHERE date >= :month_ago), 0)::integer as sales_month,
                ROUND(AVG(sales)::numeric, 2) as avg_daily_sales,
                COUNT(DISTINCT store_id) as unique_stores,
                COUNT(DISTINCT item_id) as unique_items,
                MIN(date) FILTER (WHERE is_streaming = false) as data_start,
                MAX(date) FILTER (WHERE is_streaming = false) as data_end,
                MAX(created_at) FILTER (WHERE is_streaming = true) as last_stream,
                COALESCE(SUM(sales) FILTER (WHERE date >= :week_ago AND date < :today), 0)::integer as last_week_sales,
                COALESCE(SUM(sales) FILTER (WHERE date >= :two_weeks_ago AND date < :week_ago), 0)::integer as prev_week_sales
            FROM sales
        """), {
            "today": today,
            "week_ago": week_ago,
            "month_ago": month_ago,
            "two_weeks_ago": two_weeks_ago
        })
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
        
        response_data = {
            "total_historical_records": row.historical_count or 0,
            "total_streaming_records": row.streaming_count or 0,
            "total_sales_today": row.sales_today or 0,
            "total_sales_week": row.sales_week or 0,
            "total_sales_month": row.sales_month or 0,
            "average_daily_sales": float(row.avg_daily_sales or 0),
            "unique_stores": row.unique_stores or 0,
            "unique_items": row.unique_items or 0,
            "data_range_start": row.data_start,
            "data_range_end": row.data_end,
            "last_stream_timestamp": row.last_stream,
            "sales_trend": sales_trend
        }
        
        # Cache result (serialize dates for caching)
        cache_data = response_data.copy()
        if cache_data['data_range_start']:
            cache_data['data_range_start'] = cache_data['data_range_start'].isoformat()
        if cache_data['data_range_end']:
            cache_data['data_range_end'] = cache_data['data_range_end'].isoformat()
        if cache_data['last_stream_timestamp']:
            cache_data['last_stream_timestamp'] = cache_data['last_stream_timestamp'].isoformat()
        
        await set_cached(cache_key, cache_data, CACHE_TTL['kpis'])
        
        return KPIResponse(**response_data)
        
    except Exception as e:
        logger.error(f"KPIs query error: {e}")
        # Return safe defaults on error
        return KPIResponse(
            total_historical_records=0,
            total_streaming_records=0,
            total_sales_today=0,
            total_sales_week=0,
            total_sales_month=0,
            average_daily_sales=0.0,
            unique_stores=0,
            unique_items=0,
            data_range_start=None,
            data_range_end=None,
            last_stream_timestamp=None,
            sales_trend="stable"
        )
