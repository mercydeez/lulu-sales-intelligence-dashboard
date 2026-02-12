"""
Reports API Routes
Generate comprehensive reports from live sales data
"""
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, async_session
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.routes.auth import get_current_user
from app.config import logger

router = APIRouter(tags=["Reports"])


@router.get("/sales")
async def get_sales_report(
    days: int = Query(7, ge=1, le=365),
    store_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get comprehensive sales report from real data"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    # Check cache
    cache_key = generate_cache_key("reports_sales", days=days, store_id=store_id, stores=accessible_stores)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    async with async_session() as session:
        try:
            # Build store filter
            store_filter = ""
            if store_id and store_id in accessible_stores:
                store_filter = f"AND s.store_id = {store_id}"
            elif accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            # Get daily sales trend
            trend_query = await session.execute(text(f"""
                SELECT 
                    date,
                    SUM(sales) as total_sales,
                    COUNT(*) as transactions
                FROM sales s
                WHERE date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY date
                ORDER BY date
            """))
            trend_rows = trend_query.fetchall()
            
            daily_sales = [
                {
                    "date": row.date.isoformat(),
                    "sales": row.total_sales,
                    "transactions": row.transactions
                }
                for row in trend_rows
            ]
            
            # Get category breakdown
            category_query = await session.execute(text(f"""
                SELECT 
                    i.category,
                    SUM(s.sales) as total_sales,
                    COUNT(*) as transactions
                FROM sales s
                JOIN items i ON s.item_id = i.id
                WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY i.category
                ORDER BY total_sales DESC
            """))
            category_rows = category_query.fetchall()
            
            total_sales = sum(row.total_sales for row in category_rows)
            category_breakdown = [
                {
                    "category": row.category,
                    "sales": row.total_sales,
                    "transactions": row.transactions,
                    "percentage": round((row.total_sales / total_sales * 100) if total_sales > 0 else 0, 1)
                }
                for row in category_rows
            ]
            
            # Get store performance
            store_query = await session.execute(text(f"""
                SELECT 
                    s.store_id,
                    st.name as store_name,
                    st.location,
                    SUM(s.sales) as total_sales,
                    COUNT(*) as transactions
                FROM sales s
                JOIN stores st ON s.store_id = st.id
                WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY s.store_id, st.name, st.location
                ORDER BY total_sales DESC
            """))
            store_rows = store_query.fetchall()
            
            store_performance = [
                {
                    "store_id": row.store_id,
                    "store_name": row.store_name,
                    "location": row.location,
                    "sales": row.total_sales,
                    "transactions": row.transactions
                }
                for row in store_rows
            ]
            
            # Get top items
            items_query = await session.execute(text(f"""
                SELECT 
                    s.item_id,
                    i.name as item_name,
                    i.category,
                    SUM(s.sales) as total_sales
                FROM sales s
                JOIN items i ON s.item_id = i.id
                WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY s.item_id, i.name, i.category
                ORDER BY total_sales DESC
                LIMIT 20
            """))
            items_rows = items_query.fetchall()
            
            top_items = [
                {
                    "item_id": row.item_id,
                    "item_name": row.item_name,
                    "category": row.category,
                    "total_sales": row.total_sales
                }
                for row in items_rows
            ]
            
            # Get KPIs
            kpi_query = await session.execute(text(f"""
                SELECT 
                    SUM(sales) as total_sales,
                    COUNT(*) as total_transactions,
                    AVG(sales) as avg_basket_size
                FROM sales s
                WHERE date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
            """))
            kpi_row = kpi_query.fetchone()
            
            # Calculate growth (compare to previous period)
            prev_query = await session.execute(text(f"""
                SELECT SUM(sales) as prev_sales
                FROM sales s
                WHERE date >= CURRENT_DATE - INTERVAL '{days * 2} days'
                AND date < CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
            """))
            prev_row = prev_query.fetchone()
            
            current_sales = kpi_row.total_sales or 0
            prev_sales = prev_row.prev_sales or 0
            growth = round(((current_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0, 1)
            
            result = {
                "period": {
                    "days": days,
                    "start_date": (date.today() - timedelta(days=days)).isoformat(),
                    "end_date": date.today().isoformat()
                },
                "kpis": {
                    "total_sales": current_sales,
                    "total_transactions": kpi_row.total_transactions or 0,
                    "avg_basket_size": round(kpi_row.avg_basket_size or 0, 2),
                    "sales_growth": growth
                },
                "daily_sales": daily_sales,
                "category_breakdown": category_breakdown,
                "store_performance": store_performance,
                "top_items": top_items
            }
            
            await set_cached(cache_key, result, 60)  # Cache for 1 minute
            return result
            
        except Exception as e:
            logger.error(f"Reports error: {e}")
            return {
                "period": {"days": days},
                "kpis": {"total_sales": 0, "total_transactions": 0, "avg_basket_size": 0, "sales_growth": 0},
                "daily_sales": [],
                "category_breakdown": [],
                "store_performance": [],
                "top_items": []
            }


@router.get("/inventory")
async def get_inventory_report(
    store_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get inventory status report"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    cache_key = generate_cache_key("reports_inventory", store_id=store_id, stores=accessible_stores)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    async with async_session() as session:
        try:
            store_filter = ""
            if store_id and store_id in accessible_stores:
                store_filter = f"AND s.store_id = {store_id}"
            elif accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            # Get inventory by category
            query = await session.execute(text(f"""
                WITH inventory AS (
                    SELECT 
                        i.category,
                        s.store_id,
                        s.item_id,
                        SUM(s.sales) as total_sold,
                        1000 - SUM(s.sales) % 1000 as estimated_stock
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '30 days'
                    {store_filter}
                    GROUP BY i.category, s.store_id, s.item_id
                )
                SELECT 
                    category,
                    COUNT(DISTINCT item_id) as item_count,
                    SUM(estimated_stock) as total_stock,
                    SUM(CASE WHEN estimated_stock < 100 THEN 1 ELSE 0 END) as low_stock_count
                FROM inventory
                GROUP BY category
                ORDER BY total_stock DESC
            """))
            rows = query.fetchall()
            
            result = {
                "categories": [
                    {
                        "category": row.category,
                        "item_count": row.item_count,
                        "total_stock": row.total_stock,
                        "low_stock_count": row.low_stock_count
                    }
                    for row in rows
                ]
            }
            
            await set_cached(cache_key, result, 60)
            return result
            
        except Exception as e:
            logger.error(f"Inventory report error: {e}")
            return {"categories": []}


@router.get("/performance")
async def get_performance_report(
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(get_current_user)
):
    """Get store performance comparison report"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    cache_key = generate_cache_key("reports_performance", days=days, stores=accessible_stores)
    cached = await get_cached(cache_key)
    if cached:
        return cached
    
    async with async_session() as session:
        try:
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            query = await session.execute(text(f"""
                WITH current_period AS (
                    SELECT 
                        s.store_id,
                        st.name as store_name,
                        st.location,
                        SUM(s.sales) as current_sales
                    FROM sales s
                    JOIN stores st ON s.store_id = st.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                    {store_filter}
                    GROUP BY s.store_id, st.name, st.location
                ),
                previous_period AS (
                    SELECT 
                        store_id,
                        SUM(sales) as previous_sales
                    FROM sales s
                    WHERE s.date >= CURRENT_DATE - INTERVAL '{days * 2} days'
                    AND s.date < CURRENT_DATE - INTERVAL '{days} days'
                    {store_filter}
                    GROUP BY store_id
                )
                SELECT 
                    cp.store_id,
                    cp.store_name,
                    cp.location,
                    cp.current_sales,
                    COALESCE(pp.previous_sales, 0) as previous_sales,
                    CASE 
                        WHEN COALESCE(pp.previous_sales, 0) > 0 
                        THEN ROUND((cp.current_sales - COALESCE(pp.previous_sales, 0)) / COALESCE(pp.previous_sales, 1) * 100, 1)
                        ELSE 0 
                    END as growth_rate
                FROM current_period cp
                LEFT JOIN previous_period pp ON cp.store_id = pp.store_id
                ORDER BY cp.current_sales DESC
            """))
            rows = query.fetchall()
            
            result = {
                "period_days": days,
                "stores": [
                    {
                        "store_id": row.store_id,
                        "store_name": row.store_name,
                        "location": row.location,
                        "current_sales": row.current_sales,
                        "previous_sales": row.previous_sales,
                        "growth_rate": float(row.growth_rate)
                    }
                    for row in rows
                ]
            }
            
            await set_cached(cache_key, result, 120)
            return result
            
        except Exception as e:
            logger.error(f"Performance report error: {e}")
            return {"period_days": days, "stores": []}
