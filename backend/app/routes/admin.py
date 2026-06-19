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

# NOTE: main.py mounts this router with prefix="/api/admin", so this router must
# NOT add its own "/admin" prefix (that produced the broken /api/admin/admin/* paths).
router = APIRouter(tags=["Admin"])


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
                filters.append("(u.status = 'active') = :is_active")
                params["is_active"] = is_active

            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

            query = f"""
                SELECT
                    u.id, u.email, u.first_name, u.last_name, u.role,
                    (u.status = 'active') AS is_active, u.created_at, u.last_login_at
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
                        (u.status = 'active') AS is_active, u.created_at, u.last_login_at,
                        COALESCE(array_agg(up.store_id) FILTER (WHERE up.store_id IS NOT NULL), '{}') AS store_ids,
                        bool_or(up.can_manage_inventory) AS can_manage_inventory,
                        bool_or(up.can_manage_promotions) AS can_manage_promotions,
                        bool_or(up.can_view_financials) AS can_view_financials,
                        bool_or(up.can_export) AS can_export
                    FROM users u
                    LEFT JOIN user_permissions up ON u.id = up.user_id
                    WHERE u.id = :user_id
                    GROUP BY u.id
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
                    "accessible_stores": list(row[8]) if row[8] else [],
                    "can_view_all_stores": row[4] == "super_admin",
                    "can_manage_inventory": row[9] or False,
                    "can_manage_promotions": row[10] or False,
                    "can_view_financials": row[11] or False,
                    "can_export": row[12] or False
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Get user error: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch user")


@router.post("/users", status_code=201)
async def create_user(
    payload: UserCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new user (super-admin only)."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    from app.services.auth_service import get_password_hash

    valid_roles = {"super_admin", "regional_manager", "store_manager", "analyst"}
    if payload.role not in valid_roles:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}",
        )
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=422, detail="Invalid email address")
    if not payload.first_name.strip() or not payload.last_name.strip():
        raise HTTPException(status_code=422, detail="First and last name are required")

    async with async_session() as session:
        try:
            existing = await session.execute(
                text("SELECT 1 FROM users WHERE email = :email"), {"email": email}
            )
            if existing.fetchone():
                raise HTTPException(status_code=409, detail="A user with this email already exists")

            result = await session.execute(
                text("""
                    INSERT INTO users (email, password_hash, first_name, last_name, role, status)
                    VALUES (:email, :pw, :first, :last, CAST(:role AS user_role), 'active')
                    RETURNING id, email, first_name, last_name, role, created_at
                """),
                {
                    "email": email,
                    "pw": get_password_hash(payload.password),
                    "first": payload.first_name.strip(),
                    "last": payload.last_name.strip(),
                    "role": payload.role,
                },
            )
            row = result.fetchone()
            user_id = row[0]

            # Optional store-level access grants
            for sid in (payload.store_ids or []):
                await session.execute(
                    text("""
                        INSERT INTO user_permissions (user_id, store_id, can_view, can_edit, can_export)
                        VALUES (:uid, :sid, TRUE, TRUE, TRUE)
                    """),
                    {"uid": user_id, "sid": sid},
                )

            await session.commit()
            logger.info(f"Admin {current_user.get('email')} created user {email} ({payload.role})")

            return {
                "id": row[0],
                "email": row[1],
                "first_name": row[2],
                "last_name": row[3],
                "role": row[4],
                "is_active": True,
                "created_at": row[5].isoformat() if row[5] else None,
                "last_login": None,
            }
        except HTTPException:
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Create user error: {e}")
            raise HTTPException(status_code=500, detail="Failed to create user")


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
                LEFT JOIN sales_fact_view sl ON s.id = sl.store_id 
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
                    FROM sales_fact_view
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
                    FROM sales_fact_view s
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
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
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
      