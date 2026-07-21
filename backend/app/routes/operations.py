"""Operations Copilot API. Mounted at /api/operations.

Turns a verified finding into an evidence-backed, human-approved, auditable
action draft. The route layer is thin: it authenticates, enforces the operator
gate and CSRF/tenant conventions the rest of the app uses, delegates to the
operations services, and publishes each status change to Redis/SSE. All the
safety logic (scope, OCC, revalidation, draft-only execution) lives in the
services so it is testable and cannot be bypassed by a second caller.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_deps import get_current_user
from app.config import logger
from app.services.database import get_db
from app.services.operations import execution as execution_svc
from app.services.operations.execution import ApprovalError
from app.services.operations.runner import recommend_for_finding
from app.services.redis_client import publish_operations_event

router = APIRouter(tags=["Operations Copilot"])


def _require_operator(user: dict) -> None:
    """Operators = managers or anyone who can manage inventory. Approval AUTHORITY
    (who may approve what) is a finer, policy-driven check inside the service —
    this is only the coarse gate onto the surface."""
    role = user.get("role")
    perms = user.get("permissions", {}) or {}
    if role in ("super_admin", "admin", "regional_manager", "store_manager"):
        return
    if perms.get("can_manage_inventory"):
        return
    raise HTTPException(status_code=403, detail="Operator role required")


class DecisionRequest(BaseModel):
    version: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=8, max_length=120)


class RejectRequest(DecisionRequest):
    reason: str = Field(..., min_length=1, max_length=500)


class CancelRequest(BaseModel):
    version: int = Field(..., ge=1)


async def _publish(result: dict, tenant_id: int) -> None:
    try:
        await publish_operations_event({
            "event": "operations",
            "tenant_id": tenant_id,
            "run_id": result.get("run_id"),
            "proposal_id": result.get("proposal_id"),
            "status": result.get("status"),
        })
    except Exception as exc:                       # never fail a request on a publish
        logger.warning("operations SSE publish failed: %s", exc)


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------

@router.post("/findings/{finding_id}/recommend", status_code=201)
async def recommend(finding_id: int, request: Request,
                    user: dict = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """Run the recommend graph for a finding and persist the proposal (or a
    refusal/escalation). Idempotent: a live run for this finding is returned."""
    _require_operator(user)
    result = await recommend_for_finding(db, user=user, finding_id=finding_id)
    await _publish({"run_id": result.get("run_id"), "status": result.get("status"),
                    "proposal_id": result.get("proposal_id")},
                   int(user.get("tenant_id") or 0))
    return result


@router.get("/runs/{run_id}")
async def get_run(run_id: int, user: dict = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 0
    run = (await db.execute(
        text("SELECT id, finding_id, status, phase, refusal_reason, error, "
             "graph_version, prompt_version, created_by, created_at, updated_at "
             "FROM operations_runs WHERE id = :r AND tenant_id = :t"),
        {"r": run_id, "t": tenant_id})).mappings().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    proposals = (await db.execute(
        text("SELECT id, action_type, status, title, risk_level, required_approval_role, "
             "version, expires_at, executed_ref, recommendation, calculated_parameters, "
             "created_at FROM operations_proposals WHERE run_id = :r AND tenant_id = :t "
             "ORDER BY id"),
        {"r": run_id, "t": tenant_id})).mappings().all()
    return {"run": dict(run), "proposals": [dict(p) for p in proposals]}


@router.get("/findings/{finding_id}/recommendations")
async def list_recommendations(finding_id: int, user: dict = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 0
    rows = (await db.execute(
        text("SELECT r.id AS run_id, r.status AS run_status, p.id AS proposal_id, "
             "p.status AS proposal_status, p.action_type, p.title, p.version "
             "FROM operations_runs r "
             "LEFT JOIN operations_proposals p ON p.run_id = r.id AND p.tenant_id = r.tenant_id "
             "WHERE r.finding_id = :f AND r.tenant_id = :t ORDER BY r.id DESC"),
        {"f": finding_id, "t": tenant_id})).mappings().all()
    return {"finding_id": finding_id, "runs": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@router.post("/proposals/{proposal_id}/approve")
async def approve(proposal_id: int, body: DecisionRequest, request: Request,
                  user: dict = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    try:
        result = await execution_svc.approve_proposal(
            db, user=user, proposal_id=proposal_id, expected_version=body.version,
            idempotency_key=body.idempotency_key, request_id=_rid(request))
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    await _publish(result, int(user.get("tenant_id") or 0))
    return result


@router.post("/proposals/{proposal_id}/reject")
async def reject(proposal_id: int, body: RejectRequest, request: Request,
                 user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    try:
        result = await execution_svc.reject_proposal(
            db, user=user, proposal_id=proposal_id, expected_version=body.version,
            reason=body.reason, idempotency_key=body.idempotency_key,
            request_id=_rid(request))
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    await _publish(result, int(user.get("tenant_id") or 0))
    return result


@router.post("/proposals/{proposal_id}/cancel")
async def cancel(proposal_id: int, body: CancelRequest, request: Request,
                 user: dict = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    try:
        result = await execution_svc.cancel_proposal(
            db, user=user, proposal_id=proposal_id, expected_version=body.version,
            request_id=_rid(request))
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    await _publish(result, int(user.get("tenant_id") or 0))
    return result


@router.get("/proposals/{proposal_id}/audit")
async def proposal_audit(proposal_id: int, user: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 0
    prop = (await db.execute(
        text("SELECT run_id FROM operations_proposals WHERE id = :p AND tenant_id = :t"),
        {"p": proposal_id, "t": tenant_id})).mappings().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    events = (await db.execute(
        text("SELECT event_type, actor, actor_user_id, payload, created_at "
             "FROM operations_events WHERE run_id = :r AND tenant_id = :t "
             "ORDER BY id"),
        {"r": prop["run_id"], "t": tenant_id})).mappings().all()
    return {"proposal_id": proposal_id, "run_id": prop["run_id"],
            "events": [dict(e) for e in events]}


# ---------------------------------------------------------------------------
# Queue / metrics
# ---------------------------------------------------------------------------

@router.get("/briefing")
async def briefing(user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    """The operations queue, grouped by status, for the copilot dashboard."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 0
    runs = (await db.execute(
        text("SELECT status, count(*) AS n FROM operations_runs "
             "WHERE tenant_id = :t GROUP BY status"),
        {"t": tenant_id})).mappings().all()
    proposals = (await db.execute(
        text("SELECT status, count(*) AS n FROM operations_proposals "
             "WHERE tenant_id = :t GROUP BY status"),
        {"t": tenant_id})).mappings().all()
    awaiting = (await db.execute(
        text("SELECT id, run_id, action_type, title, risk_level, "
             "required_approval_role, version, expires_at, created_at "
             "FROM operations_proposals WHERE tenant_id = :t AND status = 'awaiting_approval' "
             "ORDER BY created_at DESC LIMIT 50"),
        {"t": tenant_id})).mappings().all()
    return {
        "runs_by_status": {r["status"]: r["n"] for r in runs},
        "proposals_by_status": {p["status"]: p["n"] for p in proposals},
        "awaiting_approval": [dict(p) for p in awaiting],
    }


@router.get("/metrics")
async def metrics(user: dict = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    """Operational metrics — all SQL aggregates, no invented savings figures."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 0
    row = (await db.execute(
        text("""
        SELECT
          (SELECT count(*) FROM operations_runs WHERE tenant_id = :t) AS runs_total,
          (SELECT count(*) FROM operations_runs WHERE tenant_id = :t AND status IN ('refused','escalated')) AS refused_or_escalated,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t) AS proposals_total,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t AND status = 'approved') AS approved,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t AND status = 'rejected') AS rejected,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t AND status = 'executed') AS executed,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t AND status = 'superseded') AS superseded,
          (SELECT count(*) FROM operations_proposals WHERE tenant_id = :t AND status = 'expired') AS expired
        """),
        {"t": tenant_id})).mappings().first()
    return dict(row)
