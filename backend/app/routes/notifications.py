"""
Notifications API (UAE SaaS Phase 7). Mounted at /api/notifications.

Every endpoint is scoped to the authenticated user within their tenant (RLS via
get_db + an explicit user filter). A user sees their own notifications plus
tenant-wide ones (user_id NULL).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import notifications as svc
from app.auth_deps import get_current_user

router = APIRouter(tags=["Notifications"])


class PreferencesUpdate(BaseModel):
    muted_types: Optional[List[str]] = None
    email_enabled: Optional[bool] = None


def _ctx(user: dict):
    return user.get("tenant_id") or 1, user.get("id")


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid, uid = _ctx(user)
    items = await svc.list_for_user(db, tid, uid, unread_only=unread_only, limit=limit)
    unread = await svc.unread_count(db, tid, uid)
    return {"notifications": items, "unread": unread}


@router.get("/unread-count")
async def get_unread_count(user: dict = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    tid, uid = _ctx(user)
    return {"unread": await svc.unread_count(db, tid, uid)}


@router.post("/{notif_id}/read")
async def mark_one_read(notif_id: int, user: dict = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    tid, uid = _ctx(user)
    return {"updated": await svc.mark_read(db, tid, uid, notif_id)}


@router.post("/read-all")
async def mark_all(user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    tid, uid = _ctx(user)
    return {"updated": await svc.mark_all_read(db, tid, uid)}


@router.get("/preferences")
async def get_prefs(user: dict = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    tid, uid = _ctx(user)
    return await svc.get_preferences(db, tid, uid)


@router.put("/preferences")
async def put_prefs(payload: PreferencesUpdate, user: dict = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    tid, uid = _ctx(user)
    return await svc.update_preferences(db, tid, uid,
                                        muted_types=payload.muted_types,
                                        email_enabled=payload.email_enabled)
