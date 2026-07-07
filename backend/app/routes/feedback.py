"""
User feedback API (CX feedback loop — Y6, docs/product/CX_LOOPS_PLAN.md).
Mounted at /api/feedback. Two write shapes, one table (migration 051):
NPS pulses (kind='nps', score 0–10) and free-form feedback (kind='feedback').
Reads are admin-only; writes are any authenticated user in their own tenant.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(tags=["Feedback"])


class FeedbackIn(BaseModel):
    kind: str = Field(pattern="^(nps|feedback)$")
    score: Optional[int] = Field(default=None, ge=0, le=10)
    comment: Optional[str] = Field(default=None, max_length=4000)
    page: Optional[str] = Field(default=None, max_length=255)


@router.post("", status_code=201)
async def submit_feedback(
    payload: FeedbackIn,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Mirror the DB payload check with a friendly error before the insert.
    if payload.kind == "nps" and payload.score is None:
        raise HTTPException(status_code=422, detail="NPS submissions need a score (0–10)")
    if payload.kind == "feedback" and not (payload.comment or "").strip():
        raise HTTPException(status_code=422, detail="Feedback submissions need a comment")

    tenant_id = user.get("tenant_id") or 1
    row = (await db.execute(text("""
        INSERT INTO user_feedback (tenant_id, user_id, kind, score, comment, page)
        VALUES (:tid, :uid, :kind, :score, :comment, :page)
        RETURNING id, created_at
    """), {
        "tid": tenant_id,
        "uid": user.get("id"),
        "kind": payload.kind,
        "score": payload.score,
        "comment": (payload.comment or "").strip() or None,
        "page": payload.page,
    })).fetchone()
    await db.commit()
    return {"id": row.id, "created_at": row.created_at.isoformat()}


@router.get("")
async def list_feedback(
    kind: Optional[str] = Query(default=None, pattern="^(nps|feedback)$"),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent feedback for the caller's own tenant (admins only)."""
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = user.get("tenant_id") or 1
    rows = (await db.execute(text(f"""
        SELECT id, user_id, kind, score, comment, page, created_at
        FROM user_feedback
        WHERE tenant_id = :tid {"AND kind = :kind" if kind else ""}
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"tid": tenant_id, "limit": limit, **({"kind": kind} if kind else {})})).fetchall()
    return {
        "feedback": [
            {
                "id": r.id, "user_id": r.user_id, "kind": r.kind, "score": r.score,
                "comment": r.comment, "page": r.page, "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
