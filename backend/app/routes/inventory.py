"""
Inventory Management API Routes
Handles inventory tracking, stock levels, transfers, and alerts
Uses real sales data to compute inventory levels with Redis caching
"""
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, async_session
from app.services.data_sync import DataSyncService
from app.services.cache import get_cached, set_cached, generate_cache_key, CACHE_TTL
from app.auth_deps import get_current_user, require_permission
from app.config import logger

router = APIRouter(tags=["Inventory Management"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class InventoryItem(BaseModel):
    id: int
    item_id: int
    item_name: str
    category: str
    store_id: int
    store_name: str
    quantity: int
    reorder_level: int
    max_stock_level: int
    unit_cost: float
    last_restocked: Optional[datetime]
    status: str  # in_stock, low_stock, out_of_stock, overstocked


class StockTransfer(BaseModel):
    from_store_id: int
    to_store_id: int
    item_id: int
    quantity: int
    reason: str


# =============================================================================
# INVENTORY ROUTES
# =============================================================================

@router.get("/summary")
async def get_inventory_summary(
    store_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get inventory summary with key metrics from real sales data"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    tenant_id = current_user.get("tenant_id") or 1

    # Validate store access
    if store_id and store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    # Check cache first (tenant-scoped)
    cache_key = generate_cache_key("inventory_summary", tenant=tenant_id, store_id=store_id, stores=accessible_stores)
    cached = await get_cached(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        try:
            summary = await DataSyncService.get_inventory_summary(
                session,
                store_id=store_id,
                accessible_stores=accessible_stores,
                tenant_id=tenant_id
            )
            
            # Cache result
            await set_cached(cache_key, summary, CACHE_TTL['inventory_summary'])
            return summary
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting inventory summary: {e}")
            # Fallback to mock data
            return {
                "total_items": 1250,
                "total_value": 2847500.00,
                "low_stock_count": 45,
                "out_of_stock_count": 12,
                "overstocked_count": 8,
                "pending_transfers": 5,
                "currency": "AED"
            }


@router.get("/items")
async def get_inventory_items(
    store_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    # le=500 covers the full derived inventory (10 stores x 50 items) so a
    # single request can return an unpaginated scoped view for any role.
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user)
):
    """Get inventory items with filtering and pagination from real sales data"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    tenant_id = current_user.get("tenant_id") or 1

    # Validate store access
    if store_id and store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    # Check cache first (tenant-scoped)
    cache_key = generate_cache_key(
        "inventory_items",
        tenant=tenant_id,
        store_id=store_id,
        category=category,
        status=status,
        search=search,
        page=page,
        limit=limit,
        stores=accessible_stores
    )
    cached = await get_cached(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        try:
            result = await DataSyncService.get_inventory_from_sales(
                session,
                store_id=store_id,
                category=category,
                status=status,
                search=search,
                accessible_stores=accessible_stores,
                page=page,
                limit=limit,
                tenant_id=tenant_id
            )
            
            # Cache result
            await set_cached(cache_key, result, CACHE_TTL['inventory_items'])
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting inventory items: {e}")
            # Return empty result on error
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "pages": 0
            }


@router.get("/low-stock")
async def get_low_stock_items(
    store_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get low stock and out of stock items"""
    async with async_session() as session:
        try:
            accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
            tenant_id = current_user.get("tenant_id") or 1

            if store_id and store_id not in accessible_stores:
                raise HTTPException(status_code=403, detail="Access denied to this store")

            # Get items with low_stock or out_of_stock status
            result = await DataSyncService.get_inventory_from_sales(
                session,
                store_id=store_id,
                status="low_stock",
                accessible_stores=accessible_stores,
                page=1,
                limit=limit,
                tenant_id=tenant_id
            )

            # Also get out of stock items
            out_of_stock = await DataSyncService.get_inventory_from_sales(
                session,
                store_id=store_id,
                status="out_of_stock",
                accessible_stores=accessible_stores,
                page=1,
                limit=limit,
                tenant_id=tenant_id
            )
            
            # Combine and sort by quantity
            all_items = result.get("items", []) + out_of_stock.get("items", [])
            all_items.sort(key=lambda x: x["quantity"])
            
            return {
                "items": all_items[:limit],
                "total": len(all_items)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting low stock items: {e}")
            return {"items": [], "total": 0}


@router.get("/categories")
async def get_inventory_by_category(
    current_user: dict = Depends(get_current_user)
):
    """Get inventory breakdown by category from real sales data"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    tenant_id = current_user.get("tenant_id") or 1

    # Check cache first (tenant-scoped)
    cache_key = generate_cache_key("inventory_categories", tenant=tenant_id, stores=accessible_stores)
    cached = await get_cached(cache_key)
    if cached:
        return cached

    async with async_session() as session:
        try:
            categories = await DataSyncService.get_categories_inventory(
                session,
                accessible_stores=accessible_stores,
                tenant_id=tenant_id
            )
            result = {"categories": categories}
            
            # Cache result
            await set_cached(cache_key, result, CACHE_TTL['inventory_categories'])
            return result
            
        except Exception as e:
            logger.error(f"Error getting category inventory: {e}")
            return {"categories": []}


@router.get("/stores/{store_id}")
async def get_store_inventory(
    store_id: int,
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get inventory for a specific store"""
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    tenant_id = current_user.get("tenant_id") or 1

    if store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    async with async_session() as session:
        try:
            # Get store info (tenant-scoped)
            store_query = await session.execute(
                text("SELECT id, name, location FROM stores WHERE id = :store_id AND tenant_id = :tenant_id"),
                {"store_id": store_id, "tenant_id": tenant_id}
            )
            store_row = store_query.fetchone()

            if not store_row:
                raise HTTPException(status_code=404, detail="Store not found")

            # Get inventory for this store
            result = await DataSyncService.get_inventory_from_sales(
                session,
                store_id=store_id,
                category=category,
                accessible_stores=accessible_stores,
                page=1,
                limit=100,
                tenant_id=tenant_id
            )

            # Get summary for this store
            summary = await DataSyncService.get_inventory_summary(
                session,
                store_id=store_id,
                accessible_stores=accessible_stores,
                tenant_id=tenant_id
            )
            
            return {
                "store": {
                    "id": store_row[0],
                    "name": store_row[1],
                    "location": store_row[2]
                },
                "summary": summary,
                "items": result.get("items", []),
                "total_items": result.get("total", 0)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting store inventory: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch store inventory")


@router.get("/transfers")
async def get_stock_transfers(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user)
):
    """Get stock transfer history (simulated based on sales patterns)"""
    import random
    from datetime import datetime, timedelta
    
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    async with async_session() as session:
        try:
            # Get store and item info for generating transfers
            stores_query = await session.execute(
                text(f"SELECT id, name FROM stores WHERE id IN ({','.join(map(str, accessible_stores))})")
            )
            stores = stores_query.fetchall()
            
            items_query = await session.execute(
                text("SELECT id, name, category FROM items LIMIT 50")
            )
            items = items_query.fetchall()
            
            # Generate realistic transfers
            transfers = []
            statuses = ["pending", "in_transit", "completed", "cancelled"]
            status_weights = [0.15, 0.15, 0.6, 0.1]
            
            for i in range(min(limit, 20)):
                if len(stores) < 2:
                    break
                    
                from_store = random.choice(stores)
                to_store = random.choice([s for s in stores if s[0] != from_store[0]])
                item = random.choice(items)
                
                transfer_status = random.choices(statuses, weights=status_weights)[0]
                
                # Apply status filter if specified
                if status and transfer_status != status:
                    continue
                
                created = datetime.now() - timedelta(days=random.randint(0, 7))
                
                transfers.append({
                    "id": i + 1,
                    "from_store_id": from_store[0],
                    "from_store_name": from_store[1],
                    "to_store_id": to_store[0],
                    "to_store_name": to_store[1],
                    "item_id": item[0],
                    "item_name": item[1],
                    "category": item[2],
                    "quantity": random.randint(20, 200),
                    "status": transfer_status,
                    "reason": random.choice([
                        "Stock rebalancing",
                        "Low stock alert",
                        "Customer demand",
                        "Seasonal adjustment"
                    ]),
                    "created_at": created.isoformat(),
                    "completed_at": (created + timedelta(days=random.randint(1, 3))).isoformat() if transfer_status == "completed" else None
                })
            
            return {
                "transfers": transfers,
                "total": len(transfers),
                "page": page,
                "limit": limit
            }
            
        except Exception as e:
            logger.error(f"Error getting transfers: {e}")
            return {"transfers": [], "total": 0, "page": page, "limit": limit}


@router.post("/transfer")
async def create_stock_transfer(
    transfer: StockTransfer,
    current_user: dict = Depends(get_current_user)
):
    """Create a new stock transfer request"""
    # Check permissions
    if not current_user.get("permissions", {}).get("can_manage_inventory"):
        raise HTTPException(status_code=403, detail="Not authorized to create transfers")
    
    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    
    # Verify access to both stores
    if transfer.from_store_id not in accessible_stores or transfer.to_store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to one or both stores")
    
    # In a real implementation, this would create a database record
    # For now, return success response
    return {
        "success": True,
        "message": "Transfer request created successfully",
        "transfer_id": 1,
        "status": "pending",
        "from_store_id": transfer.from_store_id,
        "to_store_id": transfer.to_store_id,
        "item_id": transfer.item_id,
        "quantity": transfer.quantity
    }


@router.get("/analytics")
async def get_inventory_analytics(
    days: int = Query(30, ge=7, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Get inventory analytics and trends from real sales data"""
    async with async_session() as session:
        try:
            accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
            store_filter = ""
            if accessible_stores:
                store_list = ','.join(map(str, accessible_stores))
                store_filter = f"AND s.store_id IN ({store_list})"
            
            # Get daily sales trend
            trend_query = f"""
                SELECT 
                    s.date,
                    COUNT(DISTINCT s.item_id) as items_sold,
                    SUM(s.sales) as total_units
                FROM sales_fact_view s
                WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY s.date
                ORDER BY s.date
            """
            
            result = await session.execute(text(trend_query))
            rows = result.fetchall()
            
            daily_trend = []
            for row in rows:
                daily_trend.append({
                    "date": row[0].isoformat(),
                    "items_sold": int(row[1]),
                    "total_units": int(row[2])
                })
            
            # Get top categories by movement
            category_query = f"""
                SELECT 
                    i.category,
                    SUM(s.sales) as total_units,
                    COUNT(DISTINCT s.item_id) as item_count
                FROM sales_fact_view s
                JOIN items i ON s.item_id = i.id
                WHERE s.date >= CURRENT_DATE - INTERVAL '{days} days'
                {store_filter}
                GROUP BY i.category
                ORDER BY total_units DESC
                LIMIT 10
            """
            
            cat_result = await session.execute(text(category_query))
            cat_rows = cat_result.fetchall()
            
            top_categories = []
            for row in cat_rows:
                top_categories.append({
                    "category": row[0],
                    "total_units": int(row[1]),
                    "item_count": int(row[2])
                })
            
            return {
                "period_days": days,
                "daily_trend": daily_trend,
                "top_categories": top_categories,
                "total_movement": sum(d["total_units"] for d in daily_trend)
            }
            
        except Exception as e:
            logger.error(f"Error getting inventory analytics: {e}")
            return {
                "period_days": days,
                "daily_trend": [],
                "top_categories": [],
                "total_movement": 0
            }


@router.get("/reorder-suggestions")
async def get_reorder_suggestions(
    store_id: Optional[int] = None,
    lead_time_days: int = Query(7, ge=1, le=60, description="Fallback when the supplier's own lead time is unknown"),
    cover_target_days: int = Query(7, ge=0, le=60),
    limit: int = Query(20, ge=1, le=100),
    service_level: float = Query(0.95, ge=0.50, le=0.9999,
                                 description="Target chance of not stocking out within a lead time (E7-6)"),
    current_user: dict = Depends(get_current_user),
):
    """Forecast-driven reorder list (B1.7 + E7-6): the forecasting engine projects
    each item's demand, safety stock is sized from the OBSERVED demand variability
    at the requested service level, and items at or below their reorder point are
    surfaced with a recommended order quantity plus the formula that produced it.

    Where an item has too little history to measure σ, no safety stock is claimed —
    the suggestion falls back to days-of-cover and says so (`needs`)."""
    from app.auth_deps import get_accessible_store_ids
    from app.services.forecast_service import reorder_suggestions

    accessible_stores = current_user.get("permissions", {}).get("accessible_stores", [])
    if store_id and accessible_stores and store_id not in accessible_stores:
        raise HTTPException(status_code=403, detail="Access denied to this store")

    tenant_id = current_user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(current_user)
    async with async_session() as session:
        try:
            return await reorder_suggestions(
                session, tenant_id=tenant_id, allowed=allowed, store_id=store_id,
                lead_time_days=lead_time_days, cover_target_days=cover_target_days,
                limit=limit, service_level=service_level,
            )
        except Exception as e:
            logger.error(f"Error computing reorder suggestions: {e}")
            return {"suggestions": [], "count": 0, "critical_count": 0,
                    "lead_time_days": lead_time_days}


# =============================================================================
# INVENTORY BATCHES & EXPIRY (Phase 2.2)
# =============================================================================

class BatchCreate(BaseModel):
    store_id: int
    item_id: int
    batch_number: str
    quantity: int
    expiry_date: Optional[date] = None
    unit_cost: float = 0.0


def _scoped_store_filter(current_user: dict, store_id: Optional[int],
                         column: str = "b.store_id"):
    """Build (sql_fragment, params) enforcing the user's store scope."""
    accessible = current_user.get("permissions", {}).get("accessible_stores", [])
    if store_id:
        if store_id not in accessible:
            raise HTTPException(status_code=403, detail="Access denied to this store")
        return f"AND {column} = :store_id", {"store_id": store_id}
    if accessible:
        return f"AND {column} = ANY(:stores)", {"stores": accessible}
    return "", {}


@router.get("/batches")
async def get_inventory_batches(
    store_id: Optional[int] = None,
    item_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(active|expired|sold_out|disposed)$"),
    expiring_within: Optional[int] = Query(None, ge=0, le=365,
                                           description="Only batches expiring within N days"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user)
):
    """List stock batches with expiry information"""
    async with async_session() as session:
        store_sql, params = _scoped_store_filter(current_user, store_id)
        params.update({"limit": limit, "offset": (page - 1) * limit})

        filters = ""
        if item_id:
            filters += " AND b.item_id = :item_id"
            params["item_id"] = item_id
        if status:
            filters += " AND b.status = :status"
            params["status"] = status
        if expiring_within is not None:
            filters += (" AND b.expiry_date IS NOT NULL"
                        " AND b.expiry_date <= CURRENT_DATE + make_interval(days => :within)")
            params["within"] = expiring_within

        rows = (await session.execute(text(f"""
            SELECT b.id, b.store_id, st.name AS store_name, b.item_id,
                   i.name AS item_name, i.category, b.batch_number,
                   b.quantity, b.initial_quantity, b.received_date,
                   b.expiry_date, b.unit_cost, b.status,
                   CASE WHEN b.expiry_date IS NOT NULL
                        THEN (b.expiry_date - CURRENT_DATE)
                   END AS days_to_expiry
            FROM inventory_batches b
            JOIN stores st ON b.store_id = st.id
            JOIN items i ON b.item_id = i.id
            WHERE 1=1 {store_sql} {filters}
            ORDER BY b.expiry_date ASC NULLS LAST, b.id
            LIMIT :limit OFFSET :offset
        """), params)).fetchall()

        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = (await session.execute(text(f"""
            SELECT COUNT(*) FROM inventory_batches b
            WHERE 1=1 {store_sql} {filters}
        """), count_params)).scalar() or 0

        batches = [{
            "id": r.id,
            "store_id": r.store_id,
            "store_name": r.store_name,
            "item_id": r.item_id,
            "item_name": r.item_name,
            "category": r.category,
            "batch_number": r.batch_number,
            "quantity": r.quantity,
            "initial_quantity": r.initial_quantity,
            "received_date": r.received_date.isoformat(),
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
            "days_to_expiry": r.days_to_expiry,
            "unit_cost": float(r.unit_cost),
            "value_at_risk": round(r.quantity * float(r.unit_cost), 2),
            "status": r.status,
        } for r in rows]

        return {
            "batches": batches,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit),
        }


@router.get("/expiry-summary")
async def get_expiry_summary(
    store_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Expiry risk overview: batch counts and value at risk by time window"""
    async with async_session() as session:
        store_sql, params = _scoped_store_filter(current_user, store_id)

        row = (await session.execute(text(f"""
            SELECT
                COUNT(*) FILTER (WHERE b.expiry_date < CURRENT_DATE) AS expired,
                COUNT(*) FILTER (WHERE b.expiry_date >= CURRENT_DATE
                                 AND b.expiry_date <= CURRENT_DATE + 3) AS within_3d,
                COUNT(*) FILTER (WHERE b.expiry_date > CURRENT_DATE + 3
                                 AND b.expiry_date <= CURRENT_DATE + 7) AS within_7d,
                COUNT(*) FILTER (WHERE b.expiry_date > CURRENT_DATE + 7
                                 AND b.expiry_date <= CURRENT_DATE + 30) AS within_30d,
                COALESCE(SUM(b.quantity * b.unit_cost)
                    FILTER (WHERE b.expiry_date <= CURRENT_DATE + 7), 0) AS value_at_risk_7d,
                COALESCE(SUM(b.quantity * b.unit_cost)
                    FILTER (WHERE b.expiry_date < CURRENT_DATE), 0) AS expired_value
            FROM inventory_batches b
            WHERE b.status = 'active' AND b.quantity > 0
              AND b.expiry_date IS NOT NULL
              {store_sql}
        """), params)).fetchone()

        return {
            "expired_batches": row.expired or 0,
            "expiring_3_days": row.within_3d or 0,
            "expiring_7_days": row.within_7d or 0,
            "expiring_30_days": row.within_30d or 0,
            "value_at_risk_7d": float(row.value_at_risk_7d),
            "expired_value": float(row.expired_value),
            "currency": "AED",
        }


@router.post("/batches")
async def create_inventory_batch(
    batch: BatchCreate,
    current_user: dict = Depends(require_permission('can_manage_inventory'))
):
    """Register a received stock batch"""
    accessible = current_user.get("permissions", {}).get("accessible_stores", [])
    if current_user["role"] != "super_admin" and batch.store_id not in accessible:
        raise HTTPException(status_code=403, detail="Access denied to this store")
    if batch.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    async with async_session() as session:
        try:
            row = (await session.execute(text("""
                INSERT INTO inventory_batches
                    (store_id, item_id, batch_number, quantity, initial_quantity,
                     expiry_date, unit_cost, status)
                VALUES (:store_id, :item_id, :batch_number, :quantity, :quantity,
                        :expiry_date, :unit_cost, 'active')
                RETURNING id
            """), {
                "store_id": batch.store_id,
                "item_id": batch.item_id,
                "batch_number": batch.batch_number,
                "quantity": batch.quantity,
                "expiry_date": batch.expiry_date,
                "unit_cost": batch.unit_cost,
            })).fetchone()
            await session.commit()
        except Exception as e:
            if "unique_store_item_batch" in str(e):
                raise HTTPException(status_code=409,
                                    detail="Batch number already exists for this store/item")
            logger.error(f"Error creating batch: {e}")
            raise HTTPException(status_code=500, detail="Failed to create batch")

        return {"success": True, "batch_id": row.id, "message": "Batch registered"}


@router.post("/batches/{batch_id}/dispose")
async def dispose_batch(
    batch_id: int,
    current_user: dict = Depends(require_permission('can_manage_inventory'))
):
    """Mark a batch as disposed (e.g., after expiry) — zeroes its quantity"""
    async with async_session() as session:
        batch = (await session.execute(
            text("SELECT id, store_id, status FROM inventory_batches WHERE id = :id"),
            {"id": batch_id}
        )).fetchone()

        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        accessible = current_user.get("permissions", {}).get("accessible_stores", [])
        if current_user["role"] != "super_admin" and batch.store_id not in accessible:
            raise HTTPException(status_code=403, detail="Access denied to this store")
        if batch.status == "disposed":
            raise HTTPException(status_code=409, detail="Batch already disposed")

        await session.execute(text("""
            UPDATE inventory_batches
            SET status = 'disposed', quantity = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": batch_id})
        await session.commit()

        return {"success": True, "batch_id": batch_id, "message": "Batch disposed"}
