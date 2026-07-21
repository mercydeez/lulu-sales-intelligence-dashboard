"""Operations Copilot — the recommend runner (persistence + orchestration).

Wraps the recommend graph with the transactional writes: create the run, run the
graph to its checkpoint, then persist the proposal (if any) and the full audit
trail in one place. The graph reads and computes; the runner is the only writer,
which keeps the write surface small and idempotent.

Idempotency: at most one live run per finding (enforced by a partial unique index
in migration 081). If a live run already exists we return it instead of racing a
second graph over the same problem.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operations.contracts import GRAPH_VERSION, PROMPT_VERSION
from app.services.operations.graph import run_recommend_graph
from app.services.operations.policy import (
    MalformedPolicyError,
    OperationsPolicy,
    get_policy,
    is_expired,
    proposal_expiry,
)

logger = logging.getLogger(__name__)

_LIVE_STATUSES = ("analyzing", "awaiting_approval", "executing", "measuring")


async def _existing_live_run(db: AsyncSession, tenant_id: int, finding_id: int) -> Optional[int]:
    row = (await db.execute(
        text("SELECT id FROM operations_runs "
             "WHERE tenant_id = :t AND finding_id = :f AND status = ANY(:live) "
             "ORDER BY id DESC LIMIT 1"),
        {"t": tenant_id, "f": finding_id, "live": list(_LIVE_STATUSES)},
    )).scalar_one_or_none()
    return row


async def recommend_for_finding(db: AsyncSession, *, user: Dict[str, Any],
                                finding_id: int) -> Dict[str, Any]:
    """Produce (and persist) a recommendation for one finding. Returns a summary
    dict: {run_id, status, recommendation, existing}. tenant/user come from the
    server-verified auth context only — never a request body."""
    tenant_id = int(user.get("tenant_id") or 0)
    created_by = user.get("email") or "system"

    existing = await _existing_live_run(db, tenant_id, finding_id)
    if existing is not None:
        return {"run_id": existing, "status": "existing", "existing": True}

    # Policy first: a malformed/unreadable policy REFUSES rather than guessing.
    try:
        policy = await get_policy(db, tenant_id)
    except MalformedPolicyError as exc:
        run_id = await _create_run(db, tenant_id, finding_id, created_by)
        await _finalise_run(db, run_id, tenant_id, status="escalated", phase="policy",
                            refusal_reason=str(exc), error=None)
        await _write_event(db, tenant_id, run_id, None, "policy.invalid",
                           created_by, {"error": str(exc)})
        await db.commit()
        return {"run_id": run_id, "status": "escalated", "existing": False,
                "refusal_reason": str(exc)}

    run_id = await _create_run(db, tenant_id, finding_id, created_by)
    await _write_event(db, tenant_id, run_id, None, "run.created", created_by,
                       {"finding_id": finding_id, "graph_version": GRAPH_VERSION,
                        "prompt_version": PROMPT_VERSION})

    state = await run_recommend_graph(run_id=run_id, tenant_id=tenant_id,
                                      finding_id=finding_id, user=user, db=db,
                                      policy=policy)

    status = state.get("status", "failed")
    rec = state.get("recommendation")
    proposal_id: Optional[int] = None

    if status == "awaiting_approval" and rec and rec.get("proposed_actions"):
        proposal_id = await _persist_proposal(db, tenant_id, run_id, finding_id,
                                              rec, policy, created_by)

    # Persist the audit trail the graph accumulated, then the run's terminal row.
    for ev in state.get("events", []):
        await _write_event(db, tenant_id, run_id, proposal_id, ev["event_type"],
                           ev.get("actor", "system"), ev.get("payload", {}))
    await _finalise_run(db, run_id, tenant_id, status=status,
                        phase=state.get("phase"),
                        refusal_reason=state.get("refusal_reason"),
                        error=state.get("error"))
    await db.commit()

    return {"run_id": run_id, "status": status, "recommendation": rec,
            "proposal_id": proposal_id, "existing": False,
            "refusal_reason": state.get("refusal_reason")}


async def _create_run(db: AsyncSession, tenant_id: int, finding_id: int,
                      created_by: str) -> int:
    return (await db.execute(
        text("INSERT INTO operations_runs "
             "(tenant_id, finding_id, status, phase, graph_version, prompt_version, created_by) "
             "VALUES (:t, :f, 'analyzing', 'created', :gv, :pv, :cb) RETURNING id"),
        {"t": tenant_id, "f": finding_id, "gv": GRAPH_VERSION, "pv": PROMPT_VERSION,
         "cb": created_by},
    )).scalar_one()


async def _finalise_run(db: AsyncSession, run_id: int, tenant_id: int, *, status: str,
                        phase: Optional[str], refusal_reason: Optional[str],
                        error: Optional[str]) -> None:
    await db.execute(
        text("UPDATE operations_runs SET status = :s, phase = :p, "
             "refusal_reason = :r, error = :e WHERE id = :id AND tenant_id = :t"),
        {"s": status, "p": phase, "r": refusal_reason, "e": error,
         "id": run_id, "t": tenant_id})


async def _persist_proposal(db: AsyncSession, tenant_id: int, run_id: int,
                            finding_id: int, rec: Dict[str, Any],
                            policy: OperationsPolicy, created_by: str) -> int:
    action = rec["proposed_actions"][0]
    expires = proposal_expiry(policy)
    return (await db.execute(
        text("INSERT INTO operations_proposals "
             "(tenant_id, run_id, finding_id, action_type, status, title, "
             " recommendation, calculated_parameters, target_store_ids, target_item_ids, "
             " risk_level, required_approval_role, expires_at, created_by) "
             "VALUES (:t, :run, :f, :atype, 'awaiting_approval', :title, "
             " CAST(:rec AS jsonb), CAST(:params AS jsonb), :stores, :items, "
             " :risk, :role, :expires, :cb) RETURNING id"),
        {"t": tenant_id, "run": run_id, "f": finding_id,
         "atype": action["action_type"], "title": action["title"],
         "rec": json.dumps(rec), "params": json.dumps(action["calculated_parameters"]),
         "stores": action.get("target_store_ids") or [],
         "items": action.get("target_item_ids") or [],
         "risk": action["risk_level"], "role": action["required_approval_role"],
         "expires": expires, "cb": created_by},
    )).scalar_one()


async def _write_event(db: AsyncSession, tenant_id: int, run_id: int,
                       proposal_id: Optional[int], event_type: str, actor: str,
                       payload: Dict[str, Any]) -> None:
    await db.execute(
        text("INSERT INTO operations_events "
             "(tenant_id, run_id, proposal_id, event_type, actor, payload) "
             "VALUES (:t, :run, :pid, :etype, :actor, CAST(:payload AS jsonb))"),
        {"t": tenant_id, "run": run_id, "pid": proposal_id, "etype": event_type,
         "actor": actor, "payload": json.dumps(payload or {})})
