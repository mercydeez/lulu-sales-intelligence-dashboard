"""
In-app notifications + preferences (UAE SaaS Phase 7).

Notifications are tenant-scoped; user_id NULL = tenant-wide (every user in the
tenant sees it). A user's feed = their own notifications OR tenant-wide ones. Email
is a logged stub (no paid service) gated by the user's preference — wired to a real
provider later. All writes are BEST-EFFORT and never raise: a notification failure
must not break the action that triggered it.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

VALID_TYPES = {"finding", "billing", "lifecycle", "export", "quota", "system"}


async def notify(tenant_id: int, *, type: str, title: str, body: Optional[str] = None,
                 user_id: Optional[int] = None, severity: str = "info",
                 link: Optional[str] = None, metadata: Optional[dict] = None) -> None:
    """Create a notification (best-effort). user_id None => tenant-wide.
    Respects per-user mute preferences when targeted at a specific user."""
    try:
        from app.services.database import async_session
        async with async_session() as session:
            if user_id is not None and await _is_muted(session, user_id, type):
                return
            await session.execute(text("""
                INSERT INTO notifications (tenant_id, user_id, type, title, body, severity, link, metadata)
                VALUES (:tid, :uid, :type, :title, :body, :sev, :link, CAST(:meta AS JSONB))
            """), {"tid": tenant_id, "uid": user_id, "type": type, "title": title,
                   "body": body, "sev": severity, "link": link,
                   "meta": json.dumps(metadata or {})})
            await session.commit()
            await _maybe_email(session, tenant_id, user_id, type, title, body)
    except Exception as e:
        logger.debug(f"notify skipped ({type}): {e}")


async def notify_tenant_admins(tenant_id: int, **kwargs) -> None:
    """Notify every admin/owner of a tenant individually (so it respects each
    admin's mute prefs). Falls back to a tenant-wide note if the lookup fails."""
    try:
        from app.services.database import async_session
        async with async_session() as session:
            rows = (await session.execute(text("""
                SELECT id FROM users
                WHERE tenant_id = :tid AND role IN ('super_admin','admin') AND status = 'active'
            """), {"tid": tenant_id})).fetchall()
        if not rows:
            await notify(tenant_id, **kwargs)  # tenant-wide fallback
            return
        for r in rows:
            await notify(tenant_id, user_id=r.id, **kwargs)
    except Exception as e:
        logger.debug(f"notify_tenant_admins skipped: {e}")


async def _is_muted(session: AsyncSession, user_id: int, type: str) -> bool:
    row = (await session.execute(text(
        "SELECT muted_types FROM notification_preferences WHERE user_id = :uid"
    ), {"uid": user_id})).fetchone()
    if not row or not row.muted_types:
        return False
    try:
        muted = row.muted_types if isinstance(row.muted_types, list) else json.loads(row.muted_types)
        return type in muted
    except Exception:
        return False


async def _maybe_email(session: AsyncSession, tenant_id: int, user_id: Optional[int],
                       type: str, title: str, body: Optional[str]) -> None:
    """Email stub — logs only (no paid provider). Real provider wired later."""
    if user_id is None:
        return
    row = (await session.execute(text(
        "SELECT email_enabled FROM notification_preferences WHERE user_id = :uid"
    ), {"uid": user_id})).fetchone()
    if row and row.email_enabled:
        logger.info(f"[email-stub] would email user {user_id} (tenant {tenant_id}): {title}")


async def list_for_user(db: AsyncSession, tenant_id: int, user_id: int,
                        unread_only: bool = False, limit: int = 50) -> List[Dict]:
    where = "tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)"
    if unread_only:
        where += " AND read_at IS NULL"
    rows = (await db.execute(text(f"""
        SELECT id, type, title, body, severity, link, read_at, created_at
        FROM notifications WHERE {where}
        ORDER BY created_at DESC LIMIT :lim
    """), {"tid": tenant_id, "uid": user_id, "lim": limit})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["read_at"] = d["read_at"].isoformat() if d["read_at"] else None
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        out.append(d)
    return out


async def unread_count(db: AsyncSession, tenant_id: int, user_id: int) -> int:
    row = (await db.execute(text("""
        SELECT COUNT(*) AS n FROM notifications
        WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL) AND read_at IS NULL
    """), {"tid": tenant_id, "uid": user_id})).fetchone()
    return int(row.n) if row else 0


async def mark_read(db: AsyncSession, tenant_id: int, user_id: int, notif_id: int) -> bool:
    res = await db.execute(text("""
        UPDATE notifications SET read_at = CURRENT_TIMESTAMP
        WHERE id = :nid AND tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)
          AND read_at IS NULL
    """), {"nid": notif_id, "tid": tenant_id, "uid": user_id})
    await db.commit()
    return res.rowcount > 0


async def mark_all_read(db: AsyncSession, tenant_id: int, user_id: int) -> int:
    res = await db.execute(text("""
        UPDATE notifications SET read_at = CURRENT_TIMESTAMP
        WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL) AND read_at IS NULL
    """), {"tid": tenant_id, "uid": user_id})
    await db.commit()
    return res.rowcount


async def get_preferences(db: AsyncSession, tenant_id: int, user_id: int) -> Dict:
    row = (await db.execute(text(
        "SELECT muted_types, email_enabled FROM notification_preferences WHERE user_id = :uid"
    ), {"uid": user_id})).fetchone()
    if not row:
        return {"muted_types": [], "email_enabled": False, "available_types": sorted(VALID_TYPES)}
    muted = row.muted_types if isinstance(row.muted_types, list) else json.loads(row.muted_types or "[]")
    return {"muted_types": muted, "email_enabled": bool(row.email_enabled),
            "available_types": sorted(VALID_TYPES)}


async def update_preferences(db: AsyncSession, tenant_id: int, user_id: int, *,
                             muted_types: Optional[List[str]] = None,
                             email_enabled: Optional[bool] = None) -> Dict:
    muted = [t for t in (muted_types or []) if t in VALID_TYPES]
    await db.execute(text("""
        INSERT INTO notification_preferences (user_id, tenant_id, muted_types, email_enabled)
        VALUES (:uid, :tid, CAST(:muted AS JSONB), COALESCE(:email, FALSE))
        ON CONFLICT (user_id) DO UPDATE SET
            muted_types = CAST(:muted AS JSONB),
            email_enabled = COALESCE(:email, notification_preferences.email_enabled),
            updated_at = CURRENT_TIMESTAMP
    """), {"uid": user_id, "tid": tenant_id, "muted": json.dumps(muted), "email": email_enabled})
    await db.commit()
    return await get_preferences(db, tenant_id, user_id)
