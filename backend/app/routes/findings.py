"""
Findings (Diagnostics) API — reads the explainable findings the BullMQ worker
writes (A3), and lets operators acknowledge / resolve them. Tenant-scoped.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.routes.auth import get_current_user

router = APIRouter()


class ResolveRequest(BaseModel):
    note: Optional[str] = None


@router.get("")
async def list_findings(
    status: Optional[str] = Query(None, pattern="^(open|acknowledged|resolved)$"),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    category: Optional[str] = None,
    outcome: Optional[str] = Query(None, pattern="^(pending|improved|unchanged|worsened)$"),
    measured: Optional[bool] = Query(None, description="true = only findings with a recorded outcome"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List findings for the caller's tenant, newest first."""
    tenant_id = current_user.get("tenant_id") or 1
    where = ["tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "limit": limit}
    if status:
        where.append("status = :status"); params["status"] = status
    if severity:
        where.append("severity = :severity"); params["severity"] = severity
    if category:
        where.append("category = :category"); params["category"] = category
    if outcome:
        where.append("outcome_status = :outcome"); params["outcome"] = outcome
    if measured is True:
        where.append("measured_at IS NOT NULL")
    elif measured is False:
        where.append("measured_at IS NULL")
    sql = (
        "SELECT id, rule, category, severity, title, detail, evidence, entity_type, "
        "entity_id, entity_name, metric_value, status, recommended_action, action_type, "
        "action_accepted_at, action_accepted_by, outcome_status, metric_before, metric_after, "
        "measured_at, detected_at, updated_at, resolved_at "
        f"FROM findings WHERE {' AND '.join(where)} "
        "ORDER BY (status='open') DESC, "
        "CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, "
        "detected_at DESC LIMIT :limit"
    )
    rows = (await db.execute(text(sql), params)).mappings().all()
    return {"data": [dict(r) for r in rows], "count": len(rows)}


@router.get("/summary")
async def findings_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Counts by severity and status for the Insights header."""
    tenant_id = current_user.get("tenant_id") or 1
    rows = (await db.execute(text(
        "SELECT severity, status, COUNT(*) AS n FROM findings "
        "WHERE tenant_id = :tid GROUP BY severity, status"
    ), {"tid": tenant_id})).mappings().all()
    by_severity: dict = {}
    by_status: dict = {}
    open_count = 0
    for r in rows:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + r["n"]
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["n"]
        if r["status"] == "open":
            open_count += r["n"]
    # Outcome counts for accepted findings (the measure loop) — drives the Outcomes view.
    orows = (await db.execute(text(
        "SELECT outcome_status, COUNT(*) AS n FROM findings "
        "WHERE tenant_id = :tid AND action_accepted_at IS NOT NULL GROUP BY outcome_status"
    ), {"tid": tenant_id})).mappings().all()
    by_outcome = {r["outcome_status"]: r["n"] for r in orows}
    return {
        "open": open_count,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_outcome": by_outcome,
    }


async def _set_status(db: AsyncSession, tenant_id: int, finding_id: int, status: str, user: dict):
    resolved_at = "now()" if status == "resolved" else "NULL"
    resolved_by = user.get("email") if status == "resolved" else None
    res = await db.execute(text(
        f"UPDATE findings SET status = :status, updated_at = now(), "
        f"resolved_at = {resolved_at}, resolved_by = :rby "
        "WHERE id = :id AND tenant_id = :tid RETURNING id"
    ), {"status": status, "rby": resolved_by, "id": finding_id, "tid": tenant_id})
    if not res.fetchone():
        raise HTTPException(status_code=404, detail="Finding not found")
    await db.commit()
    return {"id": finding_id, "status": status, "updated_at": datetime.now(timezone.utc).isoformat()}


@router.post("/{finding_id}/acknowledge")
async def acknowledge_finding(
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _set_status(db, current_user.get("tenant_id") or 1, finding_id, "acknowledged", current_user)


@router.post("/{finding_id}/resolve")
async def resolve_finding(
    finding_id: int,
    body: ResolveRequest = ResolveRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await _set_status(db, current_user.get("tenant_id") or 1, finding_id, "resolved", current_user)


@router.post("/{finding_id}/accept-action")
async def accept_action(
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Agentic layer, autonomy level 0 (A4): the operator ACCEPTS the finding's
    recommended action. We record the decision and acknowledge the finding — the
    system never executes on its own. Higher autonomy (auto-drafting a PO/alert
    from action_type) builds on this human-gated decision later."""
    tenant_id = current_user.get("tenant_id") or 1
    row = (await db.execute(text(
        "UPDATE findings SET action_accepted_at = now(), action_accepted_by = :who, "
        "status = CASE WHEN status = 'open' THEN 'acknowledged' ELSE status END, updated_at = now() "
        "WHERE id = :id AND tenant_id = :tid "
        "RETURNING id, action_type, recommended_action"
    ), {"who": current_user.get("email"), "id": finding_id, "tid": tenant_id})).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    await db.commit()
    return {
        "id": row[0],
        "action_type": row[1],
        "recommended_action": row[2],
        "accepted": True,
        "accepted_by": current_user.get("email"),
    }
