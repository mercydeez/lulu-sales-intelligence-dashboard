"""
Procure-to-pay API (Part III-E) — suppliers, the product↔supplier catalog, and
purchase orders, including the headline forecast → draft-PO generator. Every
endpoint is tenant-scoped; mutations require an inventory-management role.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import procurement_service as proc
from app.routes.auth import get_current_user, get_accessible_store_ids

router = APIRouter()


def _tenant(user: dict) -> int:
    return user.get("tenant_id") or 1


def _require_manage(user: dict) -> None:
    role = user.get("role")
    can = user.get("permissions", {}).get("can_manage_inventory")
    if role not in ("super_admin", "admin") and not can:
        raise HTTPException(status_code=403, detail="Inventory-management role required")


class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    lead_time_days: int = Field(7, ge=1, le=120)


class GenerateRequest(BaseModel):
    lead_time_days: int = Field(7, ge=1, le=60)
    cover_target_days: int = Field(7, ge=0, le=60)


class StatusRequest(BaseModel):
    status: str
    approval_threshold: Optional[float] = None


# --- Suppliers -------------------------------------------------------------
@router.get("/suppliers")
async def list_suppliers(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"suppliers": await proc.list_suppliers(db, _tenant(user))}


@router.post("/suppliers", status_code=201)
async def create_supplier(body: SupplierCreate, user: dict = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _require_manage(user)
    return await proc.create_supplier(
        db, _tenant(user), body.name, body.contact_email, body.contact_phone, body.lead_time_days)


# --- Purchase orders -------------------------------------------------------
@router.post("/purchase-orders/generate", status_code=201)
async def generate_from_forecast(body: GenerateRequest, user: dict = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    """Forecast → action: create auto-grouped draft POs from the forecast-driven
    reorder suggestions (one PO per supplier, MOQ-respected)."""
    _require_manage(user)
    return await proc.generate_draft_pos_from_reorder(
        db, _tenant(user), allowed=get_accessible_store_ids(user),
        lead_time_days=body.lead_time_days, cover_target_days=body.cover_target_days,
        created_by=user.get("id"),
    )


@router.get("/purchase-orders")
async def list_pos(status: Optional[str] = Query(None), user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return {"purchase_orders": await proc.list_purchase_orders(db, _tenant(user), status)}


@router.get("/purchase-orders/{po_id}")
async def get_po(po_id: int, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    po = await proc.get_purchase_order(db, _tenant(user), po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


@router.post("/purchase-orders/{po_id}/status")
async def set_po_status(po_id: int, body: StatusRequest, user: dict = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Advance a PO (draft→pending_approval→approved→sent→received, or cancel).
    Approving over `approval_threshold` is rejected."""
    _require_manage(user)
    try:
        return await proc.transition_status(
            db, _tenant(user), po_id, body.status,
            user_id=user.get("id"), approval_threshold=body.approval_threshold)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
