from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from datetime import date, datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field

from app.services.database import get_db
from app.services.predictor import SalesPredictor
from app.models.sales import Sale, Store, Item
from app.routes.auth import get_current_user, can_access_store, get_accessible_store_ids


# Pydantic schemas
class SaleBase(BaseModel):
    date: date
    store_id: int = Field(..., gt=0)
    item_id: int = Field(..., gt=0)
    sales: int = Field(...)  # Can be negative for returns


class SaleResponse(SaleBase):
    id: int
    is_streaming: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class SalesAggregation(BaseModel):
    date: date
    total_sales: int
    store_id: Optional[int] = None
    item_id: Optional[int] = None


class PredictionResponse(BaseModel):
    prediction_date: date
    predicted_sales: float
    confidence_lower: Optional[float]
    confidence_upper: Optional[float]
    
    class Config:
        from_attributes = True


class DashboardMetrics(BaseModel):
    total_sales_today: int
    total_sales_week: int
    total_sales_month: int
    average_daily_sales: float
    sales_trend: str  # "up", "down", "stable"
    streaming_records_count: int


router = APIRouter()
predictor = SalesPredictor()


@router.get("/", response_model=List[SaleResponse])
async def get_sales(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    store_id: Optional[int] = Query(None),
    item_id: Optional[int] = Query(None),
    streaming_only: bool = Query(False),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get sales data with optional filters"""
    # Enforce RBAC
    if store_id:
        if not can_access_store(current_user, store_id):
            raise HTTPException(status_code=403, detail="Access denied to this store")
            
    query = select(Sale)
    
    conditions = []
    if start_date:
        conditions.append(Sale.date >= start_date)
    if end_date:
        conditions.append(Sale.date <= end_date)
    if store_id:
        conditions.append(Sale.store_id == store_id)
    else:
        allowed_stores = get_accessible_store_ids(current_user)
        if allowed_stores:
            conditions.append(Sale.store_id.in_(allowed_stores))
    if item_id:
        conditions.append(Sale.item_id == item_id)
    if streaming_only:
        conditions.append(Sale.is_streaming == True)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.order_by(Sale.date.desc(), Sale.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/aggregated", response_model=List[SalesAggregation])
async def get_aggregated_sales(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    store_id: Optional[int] = Query(None),
    item_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get aggregated sales by date"""
    # Enforce RBAC
    if store_id:
        if not can_access_store(current_user, store_id):
            raise HTTPException(status_code=403, detail="Access denied to this store")
            
    query = select(
        Sale.date,
        func.sum(Sale.sales).label('total_sales')
    )
    
    conditions = []
    if start_date:
        conditions.append(Sale.date >= start_date)
    if end_date:
        conditions.append(Sale.date <= end_date)
    if store_id:
        conditions.append(Sale.store_id == store_id)
    else:
        allowed_stores = get_accessible_store_ids(current_user)
        if allowed_stores:
            conditions.append(Sale.store_id.in_(allowed_stores))
    if item_id:
        conditions.append(Sale.item_id == item_id)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.group_by(Sale.date).order_by(Sale.date)
    
    result = await db.execute(query)
    rows = result.fetchall()
    
    return [
        SalesAggregation(date=row.date, total_sales=row.total_sales)
        for row in rows
    ]


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    store_id: int = Query(1),
    item_id: int = Query(1),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get dashboard metrics"""
    # Enforce RBAC
    if not can_access_store(current_user, store_id):
        raise HTTPException(status_code=403, detail="Access denied to this store")
        
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Today's sales
    today_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sales), 0))
        .where(Sale.date == today)
        .where(Sale.store_id == store_id)
        .where(Sale.item_id == item_id)
    )
    total_today = today_result.scalar() or 0
    
    # Week's sales
    week_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sales), 0))
        .where(Sale.date >= week_ago)
        .where(Sale.store_id == store_id)
        .where(Sale.item_id == item_id)
    )
    total_week = week_result.scalar() or 0
    
    # Month's sales
    month_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sales), 0))
        .where(Sale.date >= month_ago)
        .where(Sale.store_id == store_id)
        .where(Sale.item_id == item_id)
    )
    total_month = month_result.scalar() or 0
    
    # Average daily sales
    avg_result = await db.execute(
        select(func.avg(Sale.sales))
        .where(Sale.store_id == store_id)
        .where(Sale.item_id == item_id)
    )
    avg_daily = avg_result.scalar() or 0
    
    # Streaming records count (scoped to allowed stores)
    streaming_query = select(func.count(Sale.id)).where(Sale.is_streaming == True)
    allowed_stores = get_accessible_store_ids(current_user)
    if allowed_stores:
        streaming_query = streaming_query.where(Sale.store_id.in_(allowed_stores))
    streaming_result = await db.execute(streaming_query)
    streaming_count = streaming_result.scalar() or 0
    
    # Trend calculation (compare last 7 days with previous 7 days)
    prev_week_start = week_ago - timedelta(days=7)
    prev_week_result = await db.execute(
        select(func.coalesce(func.sum(Sale.sales), 0))
        .where(Sale.date >= prev_week_start)
        .where(Sale.date < week_ago)
        .where(Sale.store_id == store_id)
        .where(Sale.item_id == item_id)
    )
    prev_week_total = prev_week_result.scalar() or 0
    
    if prev_week_total > 0:
        change = (total_week - prev_week_total) / prev_week_total
        trend = "up" if change > 0.05 else "down" if change < -0.05 else "stable"
    else:
        trend = "stable"
    
    return DashboardMetrics(
        total_sales_today=total_today,
        total_sales_week=total_week,
        total_sales_month=total_month,
        average_daily_sales=round(float(avg_daily), 2),
        sales_trend=trend,
        streaming_records_count=streaming_count
    )


@router.get("/predictions", response_model=List[PredictionResponse])
async def get_predictions(
    store_id: int = Query(1),
    item_id: int = Query(1),
    days: int = Query(30, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Get sales predictions"""
    # Enforce RBAC
    if not can_access_store(current_user, store_id):
        raise HTTPException(status_code=403, detail="Access denied to this store")
        
    predictions = await predictor.predict(store_id, item_id, days)

    if not predictions:
        raise HTTPException(
            status_code=404,
            detail="Not enough historical data for predictions"
        )

    return predictions


class BacktestPoint(BaseModel):
    date: date
    actual: float
    predicted: float
    baseline: float


class BacktestResponse(BaseModel):
    model_config = {"protected_namespaces": ()}  # allow the model_version field

    model_version: str
    holdout_days: int
    mape: Optional[float]
    baseline_mape: Optional[float]
    points: List[BacktestPoint]


@router.get("/predictions/backtest", response_model=BacktestResponse)
async def backtest_predictions(
    store_id: int = Query(1),
    item_id: int = Query(1),
    holdout_days: int = Query(28, ge=7, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Evaluate forecast accuracy: hold out the last N days, fit on the rest,
    and report MAPE against the actuals plus a seasonal-naive baseline."""
    if not can_access_store(current_user, store_id):
        raise HTTPException(status_code=403, detail="Access denied to this store")

    result = await predictor.backtest(store_id, item_id, holdout_days)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Not enough historical data for a backtest"
        )

    return result


# Store and Item schemas
class StoreResponse(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    
    class Config:
        from_attributes = True


class ItemResponse(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    unit_price_aed: float
    
    class Config:
        from_attributes = True


@router.get("/stores", response_model=List[StoreResponse])
async def get_stores(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all store locations"""
    # Enforce RBAC: return only accessible stores
    query = select(Store)
    allowed_stores = get_accessible_store_ids(current_user)
    if allowed_stores:
        query = query.where(Store.id.in_(allowed_stores))
    result = await db.execute(query.order_by(Store.id))
    return result.scalars().all()


@router.get("/items", response_model=List[ItemResponse])
async def get_items(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all items"""
    result = await db.execute(select(Item).order_by(Item.id))
    return result.scalars().all()
