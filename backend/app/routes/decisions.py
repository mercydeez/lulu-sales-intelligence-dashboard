"""
AI Decision Center API (blueprint E3-2). Mounted at /api/decisions.

Read-only composition layer over the diagnostics loop: turns findings (+ forecast
reorder risks) into an AED-ranked inbox of decisions, each carrying problem,
impact, evidence, confidence, recommended action and expected outcome. The
DECIDE writes intentionally reuse the existing, tested endpoints so the measure
loop keeps working unchanged:
  approve  -> POST /api/findings/{id}/accept-action
  dismiss  -> POST /api/findings/{id}/resolve
  draft    -> POST /api/action-drafts/from-finding/{id}
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services.decision_center import list_decisions, summarize, sort_decisions, triage_view
from app.services.role_experience import decision_scope_for
from app.routes.auth import get_current_user, get_accessible_store_ids

router = APIRouter(tags=["Decisions"])


@router.get("")
async def get_decisions(
    state: str = Query("pending", pattern="^(pending|decided)$"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The decision inbox (pending, AED-ranked) or the decided list with each
    decision's measured outcome — scoped by the caller's role config
    (chain / region / store)."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    scope = decision_scope_for(user.get("role"))
    return await list_decisions(db, tenant_id, allowed, state=state, scope=scope)


@router.get("/triage")
async def get_triage(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Triage: the top decisions that need this caller, plus the rest routed to
    owners with plain-language reasons — filtered to the caller's role scope."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    scope = decision_scope_for(user.get("role"))
    return await triage_view(db, tenant_id, allowed, scope=scope)


@router.get("/summary")
async def decisions_summary(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pending count + AED at stake — powers the nav badge. Role-scoped."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    scope = decision_scope_for(user.get("role"))
    pending = await list_decisions(db, tenant_id, allowed, state="pending", scope=scope)
    return pending.get("summary") or summarize(sort_decisions(pending["decisions"]))
