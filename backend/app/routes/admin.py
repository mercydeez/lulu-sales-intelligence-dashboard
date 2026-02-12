"""
Admin API Routes
Handles user management, store configuration, and system settings
"""
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.services.database import async_session
from app.routes.auth import get_current_user
from app.config import logger

router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class UserCreate(BaseModel):
    model_config = ConfigDict(strict=True)
    email: str
    first_name: str
    last_name: str
    password: str
    role: str
    store_ids: Optional[List[int]] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    store_ids: Optional[List[int]] = None


class StoreUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    manager_id: Optional[int] = None
    is_active: Optional[bool] = None


# =============================================================================
# ADMIN ROUTES
# =============================================================================

@router.get("/users")
async def get_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get all users (admin only)"""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    async with async_session() as session:
        try:
            # Build query filters
            filters = []
            params = {"limit": limit, "offset": (page - 1) * limit}
            
            if search:
                filters.append("(u.email ILIKE :search OR u.first_name ILIKE :search OR u.last_name ILIKE :search)")
                params["search"] = f"%{search}%"
            
            if role:
                filters.append("u.role = :role")
                params["role"] = role
            
            if is_active is not None:
                filters.append("u.is_active = :is_active")
                params["is_active"] = is_active
            
            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            
            query = f"""
                SELECT 
                    u.id, u.email, u.first_name, u.last_name, u.role,
                    u.is_active, u.created_at, u.last_login
                FROM users u
                {where_clause}
                ORDER BY u.created_at DESC
                LIMIT :limit OFFSET :offset
            """
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            users = []
            for row in rows:
                users.append({
                    "id": row[0],
                    "email": row[1],
                    "first_name": row[2],
                    "last_name": row[3],
                    "role": row[4],
                    "is_active": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                    "last_login": row[7].isoformat() if row[7] else None
                })
            
            # Get total count
            count_query = f"SELECT COUNT(*) FROM users u {where_clause}"
            count_params = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
            count_result = await session.execute(text(count_query), count_params)
            total = count_result.scalar() or 0
            
            return {
                "users": users,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": max(1, (total + limit - 1) // limit)
            }
            
        except Exception as e:
            logger.error(f"Get users error: {e}")
            return {
                "users": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "pages": 0
            }


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get user details (admin only)"""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    async with async_session() as session:
        try:
            result = await session.execute(
                text("""
                    SELECT 
                        u.id, u.email, u.first_name, u.last_name, u.role,
                        u.is_active, u.created_at, u.last_login,
                        up.accessible_stores, up.can_view_all_stores,
                        up.can_manage_inventory, up.can_manage_promotions,
                        up.can_view_financials, up.can_export
                    FROM users u
                    LEFT JOIN user_permissions up ON u.id = up.user_id
                    WHERE u.id = :user_id
                """),
                {"user_id": user_id}
            )
            row = result.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            
            return {
                "id": row[0],
                "email": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "role": row[4],
                "is_active": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
                "last_login": row[7].isoformat() if row[7] else None,
                "permissions": {
                    "accessible_stores": row[8] or [],
                    "can_view_all_stores": row[9] or False,
                    "can_manage_inventory": row[10] or False,
                    "can_manage_promotions": row[11] or False,
                    "can_view_financials": row[12] or False,
                    "can_export": row[13] or False
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Get user error: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch user")


@router.get("/stores")
async def get_stores(
    current_user: dict = Depends(get_current_user)
):
    """Get all stores with sales data"""
    async with async_session() as session:
        try:
            accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
            
            # Get stores with recent sales data
            query = """
                SELECT 
                    s.id, s.name, s.location,
                    COALESCE(SUM(sl.sales), 0) as total_sales_30d,
                    COUNT(DISTINCT sl.item_id) as items_sold,
                    MAX(sl.date) as last_sale_date
                FROM stores s
                LEFT JOIN sales sl ON s.id = sl.store_id 
                    AND sl.date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY s.id, s.name, s.location
                ORDER BY s.id
            """
            
            result = await session.execute(text(query))
            rows = result.fetchall()
            
            stores = []
            for row in rows:
                # Only show stores user has access to (or all if admin)
                if current_user.get("role") == "super_admin" or row[0] in accessible_stores:
                    stores.append({
                        "id": row[0],
                        "name": row[1],
                        "location": row[2],
                        "total_sales_30d": int(row[3]) if row[3] else 0,
                        "items_sold": int(row[4]) if row[4] else 0,
                        "last_sale_date": row[5].isoformat() if row[5] else None,
                        "status": "active"
                    })
            
            return {"stores": stores, "total": len(stores)}
            
        except Exception as e:
            logger.error(f"Get stores error: {e}")
            return {"stores": [], "total": 0}


@router.get("/stores/{store_id}")
async def get_store_details(
    store_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get store details with performance metrics"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    if current_user.get("role") != "super_admin" and store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to this store")
    
    async with async_session() as session:
        try:
            # Get store info
            store_result = await session.execute(
                text("SELECT id, name, location FROM stores WHERE id = :store_id"),
                {"store_id": store_id}
            )
            store = store_result.fetchone()
            
            if not store:
                raise HTTPException(status_code=404, detail="Store not found")
            
            # Get performance metrics
            metrics_result = await session.execute(
                text("""
                    SELECT 
                        SUM(CASE WHEN date >= CURRENT_DATE - INTERVAL '7 days' THEN sales ELSE 0 END) as this_week,
                        SUM(CASE WHEN date >= CURRENT_DATE - INTERVAL '14 days' 
                                 AND date < CURRENT_DATE - INTERVAL '7 days' THEN sales ELSE 0 END) as last_week,
                        SUM(CASE WHEN date >= CURRENT_DATE - INTERVAL '30 days' THEN sales ELSE 0 END) as this_month,
                        COUNT(DISTINCT item_id) as unique_items,
                        AVG(sales) as avg_daily_sales
                    FROM sales
                    WHERE store_id = :store_id AND date >= CURRENT_DATE - INTERVAL '30 days'
                """),
                {"store_id": store_id}
            )
            metrics = metrics_result.fetchone()
            
            # Calculate growth
            this_week = int(metrics[0]) if metrics[0] else 0
            last_week = int(metrics[1]) if metrics[1] else 0
            growth = ((this_week - last_week) / last_week * 100) if last_week > 0 else 0
            
            # Get top categories
            cat_result = await session.execute(
                text("""
                    SELECT i.category, SUM(s.sales) as total
                    FROM sales s
                    JOIN items i ON s.item_id = i.id
                    WHERE s.store_id = :store_id AND s.date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY i.category
                    ORDER BY total DESC
                    LIMIT 5
                """),
                {"store_id": store_id}
            )
            top_categories = [{"category": r[0], "sales": int(r[1])} for r in cat_result.fetchall()]
            
            return {
                "id": store[0],
                "name": store[1],
                "location": store[2],
                "status": "active",
                "metrics": {
                    "this_week_sales": this_week,
                    "last_week_sales": last_week,
                    "this_month_sales": int(metrics[2]) if metrics[2] else 0,
                    "growth_rate": round(growth, 1),
                    "unique_items_sold": int(metrics[3]) if metrics[3] else 0,
                    "avg_daily_sales": float(metrics[4]) if metrics[4] else 0
                },
                "top_categories": top_categories
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Get store details error: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch store details")


@router.get("/dashboard")
async def get_admin_dashboard(
    current_user: dict = Depends(get_current_user)
):
    """Get admin dashboard overview from real data"""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    async with async_session() as session:
        try:
            # Get user counts
            user_result = await session.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN is_active THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN role = 'super_admin' THEN 1 ELSE 0 END) as admins,
                    SUM(CASE WHEN role = 'regional_manager' THEN 1 ELSE 0 END) as regional,
                    SUM(CASE WHEN role = 'store_manager' THEN 1 ELSE 0 END) as store_managers
                FROM users
            """))
            user_row = user_result.fetchone()
            
            # Get store counts
            store_result = await session.execute(text("""
                SELECT COUNT(*) FROM stores
            """))
            store_count = store_result.scalar() or 0
            
            # Get today's sales summary
            sales_result = await session.execute(text("""
                SELECT 
                    COALESCE(SUM(sales), 0) as today_sales,
                    COUNT(DISTINCT store_id) as active_stores,
                    COUNT(DISTINCT item_id) as items_sold
                FROM sales
                WHERE date = CURRENT_DATE
            """))
            sales_row = sales_result.fetchone()
            
            # Get 7-day trend
            trend_result = await session.execute(text("""
                SELECT date, SUM(sales) as total
                FROM sales
                WHERE date >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY date
                ORDER BY date
            """))
            daily_trend = [{"date": r[0].isoformat(), "sales": int(r[1])} for r in trend_result.fetchall()]
            
            return {
                "users": {
                    "total": int(user_row[0]) if user_row[0] else 0,
                    "active": int(user_row[1]) if user_row[1] else 0,
                    "admins": int(user_row[2]) if user_row[2] else 0,
                    "regional_managers": int(user_row[3]) if user_row[3] else 0,
                    "store_managers": int(user_row[4]) if user_row[4] else 0
                },
                "stores": {
                    "total": store_count,
                    "active": store_count
                },
                "today": {
                    "total_sales": int(sales_row[0]) if sales_row[0] else 0,
                    "active_stores": int(sales_row[1]) if sales_row[1] else 0,
                    "items_sold": int(sales_row[2]) if sales_row[2] else 0
                },
                "daily_trend": daily_trend
            }
            
        except Exception as e:
            logger.error(f"Admin dashboard error: {e}")
            return {
                "users": {"total": 0, "active": 0, "admins": 0, "regional_managers": 0, "store_managers": 0},
                "stores": {"total": 0, "active": 0},
                "today": {"total_sales": 0, "active_stores": 0, "items_sold": 0},
                "daily_trend": []
            }


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get recent system activity from real sales data"""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    async with async_session() as session:
        try:
            # Get recent sales activity
            result = await session.execute(text("""
                SELECT 
                    s.date,
                    st.name as store_name,
                    i.name as item_name,
                    s.sales,
                    s.created_at
                FROM sales s
                JOIN stores st ON s.store_id = st.id
                JOIN items i ON s.item_id = i.id
                ORDER BY s.created_at DESC
                LIMIT :limit
            """), {"limit": limit})
            
            activities = []
            for row in result.fetchall():
                activities.append({
                    "type": "sale",
                    "message": f"Sale of {row[3]} units of {row[2]} at {row[1]}",
                    "date": row[0].isoformat() if row[0] else None,
                    "timestamp": row[4].isoformat() if row[4] else None
                })
            
            return {"activities": activities, "total": len(activities)}
            
        except Exception as e:
            logger.error(f"Get activity error: {e}")
            return {"activities": [], "total": 0}
