"""
UAE retail intelligence API. Mounted at /api/uae-intelligence. Tenant-scoped (RLS).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import uae_intelligence as ui
from app.routes.auth import get_current_user

router = APIRouter(tags=["UAE Intelligence"])


@router.get("/calendar")
async def calendar(user: dict = Depends(get_current_user)):
    """The UAE retail calendar + what's active/upcoming. Lunar dates are approximate."""
    return {"calendar": ui.UAE_CALENDAR, "upcoming": ui.upcoming_events(),
            "note": "Lunar dates (Ramadan/Eid) are approximate for 2026 — confirm against an official source."}


@router.get("/emirate-performance")
async def emirate_performance(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = user.get("tenant_id") or 1
    return {"emirates": await ui.emirate_performance(db, tenant_id)}


@router.get("/transfer-suggestions")
async def transfer_suggestions(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Human-approvable branch-transfer suggestions (overstock → stockout). Suggestion only."""
    tenant_id = user.get("tenant_id") or 1
    return {"suggestions": await ui.branch_transfer_suggestions(db, tenant_id)}


@router.get("/dead-stock-by-emirate")
async def dead_stock(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tenant_id = user.get("tenant_id") or 1
    return {"emirates": await ui.dead_stock_by_emirate(db, tenant_id)}
