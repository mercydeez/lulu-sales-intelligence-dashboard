"""
Action drafts API (autonomy level 1). Mounted at /api/action-drafts.

The system drafts a human-approvable artifact from a finding's recommendation; a
human approves or rejects. Nothing is ever sent or executed automatically. Gated to
operators (admins or users who can manage inventory). Tenant-scoped (RLS via get_db).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import action_drafting as svc
from app.routes.auth import get_current_user

router = APIRouter(tags=["Action Drafts"])


class ReviewRequest(BaseModel):
    note: Optional[str] = None


def _require_operator(user: dict) -> None:
    """Operators = admins or anyone who can manage inventory/procurement."""
    role = user.get("role")
    perms = user.get("permissions", {}) or {}
    if role in ("super_admin", "admin", "regional_manager", "store_manager"):
        return
    if perms.get("can_manage_inventory"):
        return
    raise HTTPException(status_code=403, detail="Operator role required")


@router.post("/from-finding/{finding_id}", status_code=201)
async def draft_from_finding(finding_id: int, user: dict = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Draft a concrete, human-approvable action from a finding's recommendation."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    draft = await svc.create_draft_from_finding(db, tenant_id, finding_id,
                                                created_by=user.get("email") or "system")
    if draft is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    await db.commit()
    from app.services.security_events import record_event
    await record_event("action_drafted", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Drafted {draft['draft_type']} from finding {finding_id}",
                       evidence={"draft_id": draft["id"], "draft_type": draft["draft_type"]})
    from app.services.notifications import notify
    await notify(tenant_id, type="finding", severity="low",
                 title="A new action draft is ready to review",
                 body=draft.get("title"), link="/action-drafts",
                 metadata={"draft_id": draft["id"]})
    from app.services.webhook_service import dispatch_event_background
    dispatch_event_background(tenant_id, "action.drafted",
                             {"draft_id": draft["id"], "draft_type": draft["draft_type"],
                              "finding_id": finding_id})
    return draft


@router.get("")
async def list_drafts(status: Optional[str] = Query(None),
                      user: dict = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """List the tenant's action drafts (optionally filtered by status)."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    where = ["tenant_id = :tid"]
    p = {"tid": tenant_id}
    if status in ("draft", "approved", "rejected"):
        where.append("status = :st"); p["st"] = status
    rows = (await db.execute(text(f"""
        SELECT id, finding_id, draft_type, status, title, summary, source_action_type,
               created_by, reviewed_by, reviewed_at, created_at
        FROM action_drafts WHERE {' AND '.join(where)}
        ORDER BY created_at DESC LIMIT 200
    """), p)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("reviewed_at", "created_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        out.append(d)
    return {"drafts": out}


@router.get("/{draft_id}")
async def get_draft(draft_id: int, user: dict = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """Full draft including the drafted payload (email body, proposal steps, …)."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    r = (await db.execute(text("""
        SELECT * FROM action_drafts WHERE id = :id AND tenant_id = :tid
    """), {"id": draft_id, "tid": tenant_id})).mappings().fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Draft not found")
    d = dict(r)
    for k in ("reviewed_at", "created_at", "updated_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def _review(draft_id: int, decision: str, payload: ReviewRequest,
                  user: dict, db: AsyncSession):
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    row = await svc.review_draft(db, tenant_id, draft_id, decision=decision,
                                 reviewer=user.get("email") or "operator", note=payload.note)
    if row is None:
        raise HTTPException(status_code=409, detail="Draft not found or not in 'draft' state")
    await db.commit()
    from app.services.security_events import record_event
    await record_event(f"action_draft_{decision}", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Draft {draft_id} ({row['draft_type']}) {decision}",
                       evidence={"draft_id": draft_id, "note": payload.note})
    return {**row, "executed": False,
            "note": "Approval records a human decision. Execution remains manual — "
                    "the system never sends or places anything automatically."}


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: int, payload: ReviewRequest = ReviewRequest(),
                        user: dict = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Human approves a draft. Records the decision; does NOT execute the action."""
    return await _review(draft_id, "approved", payload, user, db)


@router.post("/{draft_id}/reject")
async def reject_draft(draft_id: int, payload: ReviewRequest = ReviewRequest(),
                       user: dict = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Human rejects a draft."""
    return await _review(draft_id, "rejected", payload, user, db)
