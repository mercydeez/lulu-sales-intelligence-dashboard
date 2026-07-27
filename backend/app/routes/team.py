"""
Team management API (tenant-scoped). Mounted at /api/team.

A tenant admin (super_admin within their tenant) lists their team, changes roles,
disables/re-enables members, and sees seat usage vs plan. Invites go through the
existing /api/auth/invite. Tenant-scoped (explicit tenant_id, like routes/tenants.py).
A user can never change or disable their own account here, and roles stay within the
tenant (you can't invent privileges outside the user_role enum).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.services.database import async_session
from app.services.plan_limits import limits_for_plan
from app.auth_deps import get_current_user
from app.config import logger

router = APIRouter(tags=["Team"])

# Roles a tenant admin may assign (matches the user_role enum; 'analyst' is the floor).
ASSIGNABLE_ROLES = {"super_admin", "regional_manager", "store_manager", "analyst"}
ASSIGNABLE_STATUS = {"active", "inactive"}


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("")
async def list_team(current_user: dict = Depends(get_current_user)):
    """Members of the caller's tenant."""
    _require_admin(current_user)
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, email, first_name, last_name, role::text AS role, status::text AS status,
                   last_login_at, created_at
            FROM users WHERE tenant_id = :t ORDER BY created_at
        """), {"t": tenant_id})).mappings().all()
    members = []
    for r in rows:
        d = dict(r)
        d["is_self"] = (r["id"] == current_user.get("id"))
        for k in ("last_login_at", "created_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        members.append(d)
    return {"members": members, "total": len(members),
            "assignable_roles": sorted(ASSIGNABLE_ROLES)}


@router.get("/seats")
async def seat_usage(current_user: dict = Depends(get_current_user)):
    """Active-seat count vs the plan's user limit (advisory)."""
    _require_admin(current_user)
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        plan_row = (await session.execute(
            text("SELECT plan FROM tenants WHERE id = :t"), {"t": tenant_id})).fetchone()
        used = (await session.execute(text(
            "SELECT COUNT(*) FROM users WHERE tenant_id = :t AND status = 'active'"),
            {"t": tenant_id})).scalar() or 0
    plan = (plan_row.plan if plan_row else None) or "free"
    limit = limits_for_plan(plan).get("users")
    return {"plan": plan, "used": int(used), "limit": limit,
            "remaining": (None if limit is None else max(0, limit - int(used))),
            "over": (False if limit is None else int(used) > limit)}


class RoleChange(BaseModel):
    role: str


class StatusChange(BaseModel):
    status: str


@router.patch("/{user_id}/role")
async def change_role(user_id: int, payload: RoleChange,
                      current_user: dict = Depends(get_current_user)):
    """Change a member's role (within the tenant). Cannot change your own role."""
    _require_admin(current_user)
    role = (payload.role or "").strip().lower()
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role. One of: {', '.join(sorted(ASSIGNABLE_ROLES))}")
    if user_id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        row = (await session.execute(text("""
            UPDATE users SET role = CAST(:role AS user_role), updated_at = now()
            WHERE id = :uid AND tenant_id = :t
            RETURNING id, email, role::text AS role
        """), {"role": role, "uid": user_id, "t": tenant_id})).mappings().fetchone()
        await session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")
    from app.services.security_events import record_event
    await record_event("user_role_changed", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"Set {row['email']} role to {role}")
    logger.info(f"Tenant {tenant_id}: {current_user.get('email')} set {row['email']} -> {role}")
    return dict(row)


@router.patch("/{user_id}/status")
async def change_status(user_id: int, payload: StatusChange,
                        current_user: dict = Depends(get_current_user)):
    """Disable (inactive) or re-enable (active) a member. Cannot disable yourself."""
    _require_admin(current_user)
    status = (payload.status or "").strip().lower()
    if status not in ASSIGNABLE_STATUS:
        raise HTTPException(status_code=422, detail="Status must be 'active' or 'inactive'")
    if user_id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        row = (await session.execute(text("""
            UPDATE users SET status = CAST(:status AS user_status), updated_at = now()
            WHERE id = :uid AND tenant_id = :t
            RETURNING id, email, status::text AS status
        """), {"status": status, "uid": user_id, "t": tenant_id})).mappings().fetchone()
        await session.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")
    from app.services.security_events import record_event
    await record_event("user_status_changed", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"Set {row['email']} status to {status}")
    return dict(row)
