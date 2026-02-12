"""
History API Routes - Historical data access
Matches README: GET /api/history
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel

from app.services.database import get_db
from app.models.sales import Sale, SalesHistorical, Store, Item

router = APIRouter()


class HistoricalSaleResponse(BaseModel):
    id: int
    date: date
    store_id: int
    item_id: int
    sales: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class HistoricalDataResponse(BaseModel):
    data: List[HistoricalSaleResponse]
    total: int
    page: int
    limit: int


@router.get("", response_model=HistoricalDataResponse)
async def get_history(
    start_date: Optional[date] = Query(None, alias="from", description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, alias="to", description="End date filter (YYYY-MM-DD)"),
    store: Optional[int] = Query(None, description="Store ID filter"),
    item: Optional[int] = Query(None, description="Item ID filter"),
    limit: int = Query(100, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get historical sales data with optional filters.
    
    Example: GET /api/history?from=2024-01-01&to=2024-01-14&store=1&limit=100
    """
    # Build query conditions
    conditions = []
    if start_date:
        conditions.append(Sale.date >= start_date)
    if end_date:
        conditions.append(Sale.date <= end_date)
    if store:
        conditions.append(Sale.store_id == store)
    if item:
        conditions.append(Sale.item_id == item)
    
    # Only get non-streaming (historical) data
    conditions.append(Sale.is_streaming == False)
    
    # Get total count
    count_query = select(func.count(Sale.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get data
    query = select(Sale).where(and_(*conditions)).order_by(Sale.date.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    records = result.scalars().all()
    
    return HistoricalDataResponse(
        data=[HistoricalSaleResponse.model_validate(r) for r in records],
        total=total,
        page=offset // limit + 1,
        limit=limit
    )


@router.get("/range")
async def get_date_range(db: AsyncSession = Depends(get_db)):
    """Get the date range of historical data"""
    query = select(
        func.min(Sale.date).label("min_date"),
        func.max(Sale.date).label("max_date"),
        func.count(Sale.id).label("total_records")
    ).where(Sale.is_streaming == False)
    
    result = await db.execute(query)
    row = result.one()
    
    return {
        "min_date": row.min_date,
        "max_date": row.max_date,
        "total_records": row.total_records
    }


@router.get("/stores")
async def get_stores(db: AsyncSession = Depends(get_db)):
    """Get all stores"""
    result = await db.execute(select(Store))
    stores = result.scalars().all()
    return [{"id": s.id, "name": s.name, "location": s.location} for s in stores]


@router.get("/items")
async def get_items(db: AsyncSession = Depends(get_db)):
    """Get all items"""
    result = await db.execute(select(Item))
    items = result.scalars().all()
    return [{"id": i.id, "name": i.name, "category": i.category} for i in items]
