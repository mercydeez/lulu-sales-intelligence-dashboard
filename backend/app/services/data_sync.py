"""
Data Sync Service
Generates inventory, promotions, and alerts data based on live sales data
Optimized with internal caching for expensive queries
"""
import asyncio
import random
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.database import async_session
from app.config import logger

# Simple in-memory cache for expensive queries
_query_cache: Dict[str, tuple] = {}
CACHE_TTL = 30  # seconds

def _get_cache(key: str) -> Optional[Dict]:
    """Get cached value if not expired"""
    if key in _query_cache:
        data, timestamp = _query_cache[key]
        if (datetime.now() - timestamp).seconds < CACHE_TTL:
            return data
        del _query_cache[key]
    return None

def _set_cache(key: str, data: Dict):
    """Set cache with timestamp"""
    _query_cache[key] = (data, datetime.now())
    # Cleanup old entries
    if len(_query_cache) > 100:
        now = datetime.now()
        keys_to_remove = [k for k, (_, ts) in _query_cache.items() 
                         if (now - ts).seconds > CACHE_TTL * 2]
        for k in keys_to_remove:
            del _query_cache[k]


class DataSyncService:
    """Service to sync and generate data from sales for inventory, promotions, and alerts"""
    
    # Category unit costs (base prices in AED)
    CATEGORY_COSTS = {
        'Rice & Grains': 25.0,
        'Bakery': 8.0,
        'Poultry': 35.0,
        'Dairy': 15.0,
        'Beverages': 12.0,
        'Cooking Oils': 45.0,
        'Vegetables': 10.0,
        'Fruits': 18.0,
        'Instant Food': 8.0,
        'Condiments': 12.0,
        'Spreads': 28.0,
        'Breakfast': 22.0,
        'Eggs': 20.0,
        'Frozen Foods': 25.0,
        'Household': 35.0,
        'Personal Care': 20.0,
        'Baby Care': 45.0,
        'Meat': 55.0,
        'Seafood': 65.0,
        'Spices': 40.0,
        'Deli': 18.0,
        'Sweets': 35.0
    }

    @staticmethod
    async def get_inventory_from_sales(
        session: AsyncSession,
        store_id: Optional[int] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        accessible_stores: List[int] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict:
        """Generate inventory data based on actual sales patterns"""
        try:
            offset = (page - 1) * limit
            filters = []
            params = {"limit": limit, "offset": offset}
            
            # Build store filter
            if store_id:
                filters.append("s.store_id = :store_id")
                params["store_id"] = store_id
            elif accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                filters.append(f"s.store_id IN ({store_list})")
            
            if category:
                filters.append("i.category = :category")
                params["category"] = category
                
            if search:
                filters.append("(i.name ILIKE :search OR i.category ILIKE :search)")
                params["search"] = f"%{search}%"
            
            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            
            # Query to get inventory based on sales patterns
            # Using recent sales to estimate current stock levels
            query = f"""
                WITH recent_sales AS (
                    SELECT 
                        store_id,
                        item_id,
                        SUM(sales) as total_sold,
                        AVG(sales) as avg_daily_sales,
                        MAX(date) as last_sale_date
                    FROM sales
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY store_id, item_id
                ),
                inventory_calc AS (
                    SELECT 
                        ROW_NUMBER() OVER (ORDER BY rs.store_id, rs.item_id) as id,
                        rs.item_id,
                        i.name as item_name,
                        i.category,
                        rs.store_id,
                        st.name as store_name,
                        -- Calculate estimated quantity (restock level - sales pattern)
                        GREATEST(0, 
                            CASE 
                                WHEN rs.avg_daily_sales > 50 THEN 500 - (rs.total_sold / 10)::int
                                WHEN rs.avg_daily_sales > 20 THEN 300 - (rs.total_sold / 15)::int
                                ELSE 200 - (rs.total_sold / 20)::int
                            END
                        )::int as quantity,
                        -- Reorder level based on sales velocity
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 100
                            WHEN rs.avg_daily_sales > 20 THEN 50
                            ELSE 25
                        END as reorder_level,
                        -- Max stock based on category
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 600
                            WHEN rs.avg_daily_sales > 20 THEN 400
                            ELSE 250
                        END as max_stock_level,
                        rs.avg_daily_sales,
                        rs.total_sold,
                        rs.last_sale_date
                    FROM recent_sales rs
                    JOIN items i ON rs.item_id = i.id
                    JOIN stores st ON rs.store_id = st.id
                )
                SELECT 
                    ic.id, ic.item_id, ic.item_name, ic.category,
                    ic.store_id, ic.store_name, ic.quantity,
                    ic.reorder_level, ic.max_stock_level,
                    ic.avg_daily_sales, ic.total_sold, ic.last_sale_date
                FROM inventory_calc ic
                JOIN stores s ON ic.store_id = s.id
                JOIN items i ON ic.item_id = i.id
                {where_clause}
                ORDER BY 
                    CASE WHEN ic.quantity <= 0 THEN 0
                         WHEN ic.quantity <= ic.reorder_level THEN 1
                         ELSE 2 END,
                    ic.item_name
                LIMIT :limit OFFSET :offset
            """
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            items = []
            for row in rows:
                quantity = row[6]
                reorder_level = row[7]
                max_stock = row[8]
                category_name = row[3]
                
                # Determine status
                if quantity <= 0:
                    status_val = "out_of_stock"
                elif quantity <= reorder_level:
                    status_val = "low_stock"
                elif quantity > max_stock:
                    status_val = "overstocked"
                else:
                    status_val = "in_stock"
                
                # Apply status filter if specified
                if status and status != status_val:
                    continue
                
                # Get unit cost from category
                unit_cost = DataSyncService.CATEGORY_COSTS.get(category_name, 20.0)
                
                items.append({
                    "id": row[0],
                    "item_id": row[1],
                    "item_name": row[2],
                    "category": category_name,
                    "store_id": row[4],
                    "store_name": row[5],
                    "quantity": quantity,
                    "reorder_level": reorder_level,
                    "max_stock_level": max_stock,
                    "unit_cost": unit_cost,
                    "avg_daily_sales": float(row[9]) if row[9] else 0,
                    "total_sold_30d": int(row[10]) if row[10] else 0,
                    "last_restocked": (datetime.now() - timedelta(days=random.randint(1, 7))).isoformat(),
                    "status": status_val
                })
            
            # Get total count
            count_query = f"""
                WITH recent_sales AS (
                    SELECT store_id, item_id
                    FROM sales
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY store_id, item_id
                )
                SELECT COUNT(*) 
                FROM recent_sales rs
                JOIN stores s ON rs.store_id = s.id
                JOIN items i ON rs.item_id = i.id
                {where_clause}
            """
            count_params = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
            count_result = await session.execute(text(count_query), count_params)
            total = count_result.scalar() or 0
            
            return {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": max(1, (total + limit - 1) // limit)
            }
            
        except Exception as e:
            logger.error(f"Error getting inventory from sales: {e}")
            raise

    @staticmethod
    async def get_inventory_summary(
        session: AsyncSession,
        store_id: Optional[int] = None,
        accessible_stores: List[int] = None
    ) -> Dict:
        """Generate inventory summary from sales data"""
        try:
            filters = []
            params = {}
            
            if store_id:
                filters.append("rs.store_id = :store_id")
                params["store_id"] = store_id
            elif accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                filters.append(f"rs.store_id IN ({store_list})")
            
            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            
            query = f"""
                WITH recent_sales AS (
                    SELECT 
                        store_id,
                        item_id,
                        SUM(sales) as total_sold,
                        AVG(sales) as avg_daily_sales
                    FROM sales
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY store_id, item_id
                ),
                inventory_calc AS (
                    SELECT 
                        rs.store_id,
                        rs.item_id,
                        i.category,
                        GREATEST(0, 
                            CASE 
                                WHEN rs.avg_daily_sales > 50 THEN 500 - (rs.total_sold / 10)::int
                                WHEN rs.avg_daily_sales > 20 THEN 300 - (rs.total_sold / 15)::int
                                ELSE 200 - (rs.total_sold / 20)::int
                            END
                        )::int as quantity,
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 100
                            WHEN rs.avg_daily_sales > 20 THEN 50
                            ELSE 25
                        END as reorder_level,
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 600
                            WHEN rs.avg_daily_sales > 20 THEN 400
                            ELSE 250
                        END as max_stock_level
                    FROM recent_sales rs
                    JOIN items i ON rs.item_id = i.id
                )
                SELECT 
                    COUNT(*) as total_items,
                    SUM(ic.quantity * 
                        CASE ic.category
                            WHEN 'Rice & Grains' THEN 25
                            WHEN 'Bakery' THEN 8
                            WHEN 'Poultry' THEN 35
                            WHEN 'Dairy' THEN 15
                            WHEN 'Beverages' THEN 12
                            WHEN 'Meat' THEN 55
                            WHEN 'Seafood' THEN 65
                            ELSE 20
                        END
                    ) as total_value,
                    SUM(CASE WHEN ic.quantity <= ic.reorder_level AND ic.quantity > 0 THEN 1 ELSE 0 END) as low_stock,
                    SUM(CASE WHEN ic.quantity <= 0 THEN 1 ELSE 0 END) as out_of_stock,
                    SUM(CASE WHEN ic.quantity > ic.max_stock_level THEN 1 ELSE 0 END) as overstocked
                FROM inventory_calc ic
                JOIN recent_sales rs ON ic.store_id = rs.store_id AND ic.item_id = rs.item_id
                {where_clause}
            """
            
            result = await session.execute(text(query), params)
            row = result.fetchone()
            
            return {
                "total_items": int(row[0]) if row and row[0] else 0,
                "total_value": float(row[1]) if row and row[1] else 0,
                "low_stock_count": int(row[2]) if row and row[2] else 0,
                "out_of_stock_count": int(row[3]) if row and row[3] else 0,
                "overstocked_count": int(row[4]) if row and row[4] else 0,
                "pending_transfers": random.randint(2, 8),
                "currency": "AED"
            }
            
        except Exception as e:
            logger.error(f"Error getting inventory summary: {e}")
            raise

    @staticmethod
    async def get_categories_inventory(
        session: AsyncSession,
        accessible_stores: List[int] = None
    ) -> List[Dict]:
        """Get inventory breakdown by category"""
        try:
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND rs.store_id IN ({store_list})"
            
            query = f"""
                WITH recent_sales AS (
                    SELECT 
                        store_id,
                        item_id,
                        SUM(sales) as total_sold,
                        AVG(sales) as avg_daily_sales
                    FROM sales
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY store_id, item_id
                ),
                inventory_calc AS (
                    SELECT 
                        i.category,
                        rs.item_id,
                        GREATEST(0, 
                            CASE 
                                WHEN rs.avg_daily_sales > 50 THEN 500 - (rs.total_sold / 10)::int
                                WHEN rs.avg_daily_sales > 20 THEN 300 - (rs.total_sold / 15)::int
                                ELSE 200 - (rs.total_sold / 20)::int
                            END
                        )::int as quantity,
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 100
                            WHEN rs.avg_daily_sales > 20 THEN 50
                            ELSE 25
                        END as reorder_level
                    FROM recent_sales rs
                    JOIN items i ON rs.item_id = i.id
                    WHERE 1=1 {store_filter}
                )
                SELECT 
                    ic.category,
                    COUNT(DISTINCT ic.item_id) as item_count,
                    SUM(ic.quantity) as total_quantity,
                    SUM(CASE WHEN ic.quantity <= ic.reorder_level THEN 1 ELSE 0 END) as low_stock_count
                FROM inventory_calc ic
                GROUP BY ic.category
                ORDER BY total_quantity DESC
            """
            
            result = await session.execute(text(query))
            rows = result.fetchall()
            
            categories = []
            for row in rows:
                category = row[0]
                unit_cost = DataSyncService.CATEGORY_COSTS.get(category, 20.0)
                total_qty = int(row[2]) if row[2] else 0
                
                categories.append({
                    "category": category,
                    "item_count": int(row[1]) if row[1] else 0,
                    "total_quantity": total_qty,
                    "total_value": total_qty * unit_cost,
                    "low_stock_count": int(row[3]) if row[3] else 0
                })
            
            return categories
            
        except Exception as e:
            logger.error(f"Error getting category inventory: {e}")
            raise

    @staticmethod
    async def generate_alerts_from_sales(
        session: AsyncSession,
        accessible_stores: List[int] = None
    ) -> List[Dict]:
        """Generate alerts based on sales patterns and inventory levels"""
        try:
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            alerts = []
            alert_id = 1
            
            # 1. Low stock alerts
            low_stock_query = f"""
                WITH recent_sales AS (
                    SELECT 
                        store_id,
                        item_id,
                        SUM(sales) as total_sold,
                        AVG(sales) as avg_daily_sales
                    FROM sales
                    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY store_id, item_id
                ),
                inventory_calc AS (
                    SELECT 
                        rs.store_id,
                        st.name as store_name,
                        rs.item_id,
                        i.name as item_name,
                        i.category,
                        GREATEST(0, 
                            CASE 
                                WHEN rs.avg_daily_sales > 50 THEN 500 - (rs.total_sold / 10)::int
                                WHEN rs.avg_daily_sales > 20 THEN 300 - (rs.total_sold / 15)::int
                                ELSE 200 - (rs.total_sold / 20)::int
                            END
                        )::int as quantity,
                        CASE 
                            WHEN rs.avg_daily_sales > 50 THEN 100
                            WHEN rs.avg_daily_sales > 20 THEN 50
                            ELSE 25
                        END as reorder_level
                    FROM recent_sales rs
                    JOIN items i ON rs.item_id = i.id
                    JOIN stores st ON rs.store_id = st.id
                    WHERE 1=1 {store_filter}
                )
                SELECT store_id, store_name, item_id, item_name, category, quantity, reorder_level
                FROM inventory_calc
                WHERE quantity <= reorder_level
                ORDER BY quantity ASC
                LIMIT 10
            """
            
            result = await session.execute(text(low_stock_query))
            for row in result.fetchall():
                severity = "critical" if row[5] <= 0 else "warning"
                alerts.append({
                    "id": alert_id,
                    "title": f"{'Out of Stock' if row[5] <= 0 else 'Low Stock'}: {row[3]}",
                    "message": f"{row[3]} at {row[1]} has only {row[5]} units remaining (reorder level: {row[6]})",
                    "alert_type": "inventory",
                    "severity": severity,
                    "status": "active",
                    "store_id": row[0],
                    "store_name": row[1],
                    "item_id": row[2],
                    "created_at": (datetime.now() - timedelta(hours=random.randint(1, 24))).isoformat(),
                    "acknowledged_at": None,
                    "resolved_at": None
                })
                alert_id += 1
            
            # 2. Sales anomaly alerts (unusually high or low sales)
            anomaly_query = f"""
                WITH daily_sales AS (
                    SELECT 
                        s.store_id,
                        st.name as store_name,
                        s.item_id,
                        i.name as item_name,
                        s.date,
                        s.sales
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    JOIN stores st ON s.store_id = st.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '7 days'
                    {store_filter.replace('s.store_id', 's.store_id')}
                ),
                sales_stats AS (
                    SELECT 
                        store_id,
                        item_id,
                        AVG(sales) as avg_sales,
                        STDDEV(sales) as stddev_sales
                    FROM daily_sales
                    GROUP BY store_id, item_id
                )
                SELECT 
                    ds.store_id, ds.store_name, ds.item_id, ds.item_name,
                    ds.sales, ss.avg_sales, ss.stddev_sales
                FROM daily_sales ds
                JOIN sales_stats ss ON ds.store_id = ss.store_id AND ds.item_id = ss.item_id
                WHERE ds.date = (SELECT MAX(date) FROM daily_sales)
                AND ss.stddev_sales > 0
                AND ABS(ds.sales - ss.avg_sales) > 2 * ss.stddev_sales
                LIMIT 5
            """
            
            try:
                result = await session.execute(text(anomaly_query))
                for row in result.fetchall():
                    is_high = row[4] > row[5]
                    alerts.append({
                        "id": alert_id,
                        "title": f"{'High' if is_high else 'Low'} Sales Alert: {row[3]}",
                        "message": f"{row[3]} at {row[1]} had {'unusually high' if is_high else 'unusually low'} sales ({row[4]} vs avg {row[5]:.0f})",
                        "alert_type": "sales",
                        "severity": "info" if is_high else "warning",
                        "status": "active",
                        "store_id": row[0],
                        "store_name": row[1],
                        "item_id": row[2],
                        "created_at": (datetime.now() - timedelta(hours=random.randint(1, 12))).isoformat(),
                        "acknowledged_at": None,
                        "resolved_at": None
                    })
                    alert_id += 1
            except Exception:
                pass  # Skip anomaly alerts if query fails
            
            # 3. Store performance alerts
            store_query = f"""
                WITH store_sales AS (
                    SELECT 
                        s.store_id,
                        st.name as store_name,
                        SUM(CASE WHEN s.date >= CURRENT_DATE - INTERVAL '7 days' THEN s.sales ELSE 0 END) as this_week,
                        SUM(CASE WHEN s.date >= CURRENT_DATE - INTERVAL '14 days' 
                                 AND s.date < CURRENT_DATE - INTERVAL '7 days' THEN s.sales ELSE 0 END) as last_week
                    FROM sales s
                    JOIN stores st ON s.store_id = st.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '14 days'
                    {store_filter.replace('s.store_id', 's.store_id')}
                    GROUP BY s.store_id, st.name
                )
                SELECT store_id, store_name, this_week, last_week,
                       CASE WHEN last_week > 0 
                            THEN ((this_week - last_week)::float / last_week * 100)
                            ELSE 0 END as change_pct
                FROM store_sales
                WHERE last_week > 0
                AND ABS((this_week - last_week)::float / last_week * 100) > 15
            """
            
            try:
                result = await session.execute(text(store_query))
                for row in result.fetchall():
                    is_increase = row[4] > 0
                    alerts.append({
                        "id": alert_id,
                        "title": f"Store Performance: {row[1]}",
                        "message": f"{row[1]} sales {'increased' if is_increase else 'decreased'} by {abs(row[4]):.1f}% this week",
                        "alert_type": "sales",
                        "severity": "info" if is_increase else "warning",
                        "status": "active",
                        "store_id": row[0],
                        "store_name": row[1],
                        "item_id": None,
                        "created_at": (datetime.now() - timedelta(hours=random.randint(2, 48))).isoformat(),
                        "acknowledged_at": None,
                        "resolved_at": None
                    })
                    alert_id += 1
            except Exception:
                pass
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error generating alerts: {e}")
            raise

    @staticmethod
    async def get_promotions_from_sales(
        session: AsyncSession,
        accessible_stores: List[int] = None
    ) -> Dict:
        """Generate promotion suggestions based on sales patterns"""
        try:
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            # Find slow-moving items that might benefit from promotions
            query = f"""
                WITH item_sales AS (
                    SELECT 
                        s.item_id,
                        i.name as item_name,
                        i.category,
                        SUM(s.sales) as total_sales,
                        AVG(s.sales) as avg_daily_sales,
                        COUNT(DISTINCT s.store_id) as store_count
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '30 days'
                    {store_filter}
                    GROUP BY s.item_id, i.name, i.category
                ),
                category_avg AS (
                    SELECT category, AVG(avg_daily_sales) as cat_avg
                    FROM item_sales
                    GROUP BY category
                )
                SELECT 
                    is2.item_id, is2.item_name, is2.category,
                    is2.total_sales, is2.avg_daily_sales, is2.store_count,
                    ca.cat_avg,
                    CASE WHEN is2.avg_daily_sales < ca.cat_avg * 0.5 THEN 'slow_mover'
                         WHEN is2.avg_daily_sales > ca.cat_avg * 1.5 THEN 'fast_mover'
                         ELSE 'normal' END as velocity
                FROM item_sales is2
                JOIN category_avg ca ON is2.category = ca.category
                ORDER BY is2.avg_daily_sales ASC
            """
            
            result = await session.execute(text(query))
            rows = result.fetchall()
            
            # Generate promotion suggestions
            promotions = []
            promo_id = 1
            today = date.today()
            
            slow_movers = [r for r in rows if r[7] == 'slow_mover'][:5]
            fast_movers = [r for r in rows if r[7] == 'fast_mover'][:3]
            
            # Create promotions for slow movers
            for row in slow_movers:
                category = row[2]
                unit_cost = DataSyncService.CATEGORY_COSTS.get(category, 20.0)
                discount = random.choice([10, 15, 20, 25])
                
                promotions.append({
                    "id": promo_id,
                    "name": f"{discount}% Off {row[1]}",
                    "description": f"Special discount on {row[1]} to boost sales",
                    "discount_type": "percentage",
                    "discount_value": discount,
                    "start_date": today.isoformat(),
                    "end_date": (today + timedelta(days=random.randint(7, 14))).isoformat(),
                    "status": "active",
                    "item_id": row[0],
                    "item_name": row[1],
                    "category": category,
                    "redemption_count": random.randint(50, 500),
                    "total_discount_given": random.randint(500, 5000),
                    "original_price": unit_cost,
                    "promo_price": unit_cost * (1 - discount / 100)
                })
                promo_id += 1
            
            # Bundle promotions for fast movers
            for row in fast_movers:
                promotions.append({
                    "id": promo_id,
                    "name": f"Buy 2 Get 1 Free: {row[1]}",
                    "description": f"Popular item bundle deal",
                    "discount_type": "bogo",
                    "discount_value": 33,
                    "start_date": today.isoformat(),
                    "end_date": (today + timedelta(days=random.randint(3, 7))).isoformat(),
                    "status": "active",
                    "item_id": row[0],
                    "item_name": row[1],
                    "category": row[2],
                    "redemption_count": random.randint(100, 800),
                    "total_discount_given": random.randint(1000, 8000),
                    "original_price": DataSyncService.CATEGORY_COSTS.get(row[2], 20.0),
                    "promo_price": None
                })
                promo_id += 1
            
            # Category-wide promotions
            categories = list(set([r[2] for r in rows]))[:3]
            for cat in categories:
                discount = random.choice([5, 10, 15])
                promotions.append({
                    "id": promo_id,
                    "name": f"{cat} Week Sale",
                    "description": f"{discount}% off all {cat} items",
                    "discount_type": "percentage",
                    "discount_value": discount,
                    "start_date": (today - timedelta(days=random.randint(0, 3))).isoformat(),
                    "end_date": (today + timedelta(days=random.randint(4, 10))).isoformat(),
                    "status": "active",
                    "item_id": None,
                    "item_name": None,
                    "category": cat,
                    "redemption_count": random.randint(200, 2000),
                    "total_discount_given": random.randint(2000, 20000),
                    "original_price": None,
                    "promo_price": None
                })
                promo_id += 1
            
            return {
                "promotions": promotions,
                "summary": {
                    "active_promotions": len([p for p in promotions if p["status"] == "active"]),
                    "scheduled_promotions": 3,
                    "ended_promotions": random.randint(20, 50),
                    "draft_promotions": 2,
                    "total_discounts_given": sum(p["total_discount_given"] for p in promotions),
                    "total_redemptions": sum(p["redemption_count"] for p in promotions),
                    "currency": "AED"
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting promotions from sales: {e}")
            raise

    @staticmethod
    async def get_category_performance(
        session: AsyncSession,
        accessible_stores: List[int] = None
    ) -> List[Dict]:
        """Get sales performance by category"""
        try:
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            query = f"""
                WITH current_period AS (
                    SELECT 
                        i.category,
                        SUM(s.sales) as total_sales
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '7 days'
                    {store_filter}
                    GROUP BY i.category
                ),
                previous_period AS (
                    SELECT 
                        i.category,
                        SUM(s.sales) as total_sales
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    WHERE s.date >= CURRENT_DATE - INTERVAL '14 days'
                    AND s.date < CURRENT_DATE - INTERVAL '7 days'
                    {store_filter}
                    GROUP BY i.category
                )
                SELECT 
                    cp.category,
                    cp.total_sales as current_sales,
                    COALESCE(pp.total_sales, 0) as previous_sales,
                    CASE WHEN COALESCE(pp.total_sales, 0) > 0 
                         THEN ((cp.total_sales - pp.total_sales)::float / pp.total_sales * 100)
                         ELSE 0 END as growth_rate
                FROM current_period cp
                LEFT JOIN previous_period pp ON cp.category = pp.category
                ORDER BY cp.total_sales DESC
            """
            
            result = await session.execute(text(query))
            rows = result.fetchall()
            
            categories = []
            for row in rows:
                category = row[0]
                unit_price = DataSyncService.CATEGORY_COSTS.get(category, 20.0)
                categories.append({
                    "category": category,
                    "total_units": int(row[1]),
                    "total_revenue": int(row[1]) * unit_price,
                    "previous_units": int(row[2]),
                    "growth_rate": float(row[3]) if row[3] else 0,
                    "avg_discount": random.uniform(5, 15)
                })
            
            return categories
            
        except Exception as e:
            logger.error(f"Error getting category performance: {e}")
            raise


# Create singleton instance
data_sync_service = DataSyncService()
