"""Operations Copilot — approval and execution (invocation B).

Resumes a run from its checkpoint (an awaiting_approval proposal) after a human
decides. Everything money-adjacent lives here, so the guarantees are strict:

  * OPTIMISTIC CONCURRENCY. Every decision carries the version it saw; the update
    is a compare-and-swap on that version. A stale or racing decision gets a 409,
    never a silent overwrite.
  * IDEMPOTENT. A retried approval/rejection carrying the same idempotency key
    returns the first result; a second execution is a no-op that returns the
    existing executed_ref.
  * RE-AUTHORISED AT DECISION TIME. can_approve runs again here, from the
    server-verified auth context — a user who lost scope between recommend and
    approve is refused.
  * REVALIDATED BEFORE EXECUTION. The key quantity is recomputed against live
    inventory; if it moved past the tenant tolerance the proposal is SUPERSEDED
    and a fresh approval is required — we never execute a stale number.
  * DRAFT-ONLY. Execution writes an INTERNAL action_drafts row and schedules
    measurement by stamping the finding. It never submits to a supplier or a
    warehouse — is_draft_only is always true until a real connector exists.
  * IMMUTABLE AUDIT. Every transition appends an operations_events row.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operations.calculations import (
    calculate_replenishment,
    calculate_transfer,
)
from app.services.operations.contracts import ActionType, RiskLevel
from app.services.operations.policy import (
    OperationsPolicy,
    can_approve,
    get_policy,
    is_expired,
    materially_changed,
)
from app.services.operations.tools_read import get_inventory_state

logger = logging.getLogger(__name__)


class ApprovalError(Exception):
    """Base for decision failures. `code` maps to an HTTP status in the route."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


class NotFound(ApprovalError):
    def __init__(self, message="proposal not found"):
        super().__init__(message, code=404)


class Conflict(ApprovalError):
    def __init__(self, message="the proposal changed since you loaded it"):
        super().__init__(message, code=409)


class Forbidden(ApprovalError):
    def __init__(self, message="not authorised to decide this proposal"):
        super().__init__(message, code=403)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_PROPOSAL_COLS = (
    "id, tenant_id, run_id, finding_id, action_type, status, title, recommendation, "
    "calculated_parameters, target_store_ids, target_item_ids, risk_level, "
    "required_approval_role, expires_at, version, idempotency_key, approved_by, "
    "executed_ref, created_at")


async def _load_proposal(db: AsyncSession, tenant_id: int, proposal_id: int,
                         for_update: bool = False) -> Optional[Dict]:
    lock = " FOR UPDATE" if for_update else ""
    row = (await db.execute(
        text(f"SELECT {_PROPOSAL_COLS} FROM operations_proposals "
             f"WHERE id = :id AND tenant_id = :t" + lock),
        {"id": proposal_id, "t": tenant_id},
    )).mappings().first()
    return dict(row) if row else None


async def _event(db: AsyncSession, tenant_id: int, run_id: int, proposal_id: int,
                 event_type: str, actor: str, actor_user_id: Optional[int],
                 payload: Dict, request_id: Optional[str] = None) -> None:
    await db.execute(
        text("INSERT INTO operations_events "
             "(tenant_id, run_id, proposal_id, event_type, actor, actor_user_id, "
             " payload, request_id) VALUES "
             "(:t, :run, :pid, :etype, :actor, :uid, CAST(:payload AS jsonb), :rid)"),
        {"t": tenant_id, "run": run_id, "pid": proposal_id, "etype": event_type,
         "actor": actor, "uid": actor_user_id, "payload": json.dumps(payload or {}),
         "rid": request_id})


def _risk(proposal: Dict) -> RiskLevel:
    try:
        return RiskLevel(str(proposal.get("risk_level") or "medium"))
    except ValueError:
        return RiskLevel.MEDIUM


def _cas_update(db: AsyncSession, proposal_id: int, tenant_id: int, expected_version: int,
                sets: Dict[str, Any]) -> Any:
    """Compare-and-swap the proposal on (id, tenant, version, current status).
    Returns the coroutine for the UPDATE; caller awaits and checks rowcount."""
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    params = dict(sets)
    params.update({"id": proposal_id, "t": tenant_id, "v": expected_version})
    return db.execute(
        text(f"UPDATE operations_proposals SET {assignments} "
             f"WHERE id = :id AND tenant_id = :t AND version = :v"),
        params)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

async def approve_proposal(db: AsyncSession, *, user: Dict[str, Any], proposal_id: int,
                           expected_version: int, idempotency_key: str,
                           request_id: Optional[str] = None) -> Dict[str, Any]:
    """Approve, then execute (invocation B). Returns the outcome dict. Raises
    ApprovalError subclasses the route maps to HTTP codes."""
    tenant_id = int(user.get("tenant_id") or 0)
    prop = await _load_proposal(db, tenant_id, proposal_id, for_update=True)
    if not prop:
        raise NotFound()

    # Already executed -> idempotent return.
    if prop["status"] == "executed" and prop.get("executed_ref"):
        return {"proposal_id": proposal_id, "run_id": prop["run_id"], "status": "executed",
                "executed_ref": prop.get("executed_ref"), "idempotent": True}

    # Approved-but-not-executed (a prior execution crashed, or a replay of the same
    # key): DRIVE EXECUTION rather than returning a stuck 'approved'. This is the
    # retry path — an approved action is never silently dropped.
    if prop["status"] in ("approved", "execution_failed") and \
            prop.get("idempotency_key") == idempotency_key:
        return await execute_proposal(db, user=user, proposal_id=proposal_id,
                                      request_id=request_id)

    if prop["status"] != "awaiting_approval":
        raise Conflict(f"proposal is {prop['status']}, not awaiting approval")

    policy = await get_policy(db, tenant_id)

    if prop.get("expires_at") and is_expired_row(prop["expires_at"]):
        result = await _cas_update(db, proposal_id, tenant_id, expected_version,
                                   {"status": "expired", "version": expected_version + 1})
        if result.rowcount == 0:                 # stale version — nothing changed
            await db.rollback()
            raise Conflict()
        await _event(db, tenant_id, prop["run_id"], proposal_id, "proposal.expired",
                     user.get("email") or "system", user.get("id"), {}, request_id)
        await db.commit()
        raise Conflict("proposal has expired — request a fresh recommendation")

    # RE-AUTHORISE from the server-verified context (scope may have changed).
    allowed, why = can_approve(
        user, policy,
        action_type=ActionType(prop["action_type"]),
        risk_level=_risk(prop),
        target_store_ids=list(prop.get("target_store_ids") or []),
        proposal_tenant_id=tenant_id)
    if not allowed:
        await _event(db, tenant_id, prop["run_id"], proposal_id, "approval.denied",
                     user.get("email") or "system", user.get("id"),
                     {"reason": why}, request_id)
        await db.commit()
        raise Forbidden(why)

    # OCC approve. A cross-proposal idempotency-key collision (tenant-wide unique
    # index) surfaces as a clean 409, never a 500.
    try:
        result = await _cas_update(db, proposal_id, tenant_id, expected_version, {
            "status": "approved", "approved_by": user.get("email"),
            "approved_at": datetime.now(timezone.utc), "idempotency_key": idempotency_key,
            "version": expected_version + 1})
    except IntegrityError:
        await db.rollback()
        raise Conflict("idempotency key already used on another proposal")
    if result.rowcount == 0:
        await db.rollback()
        raise Conflict()
    await _event(db, tenant_id, prop["run_id"], proposal_id, "approval.granted",
                 user.get("email") or "system", user.get("id"),
                 {"role": user.get("role")}, request_id)
    await db.commit()

    # Invocation B: revalidate + execute. A failure here marks the proposal
    # 'execution_failed' (durable, retryable) so the approved action is not lost.
    return await execute_proposal(db, user=user, proposal_id=proposal_id,
                                  request_id=request_id)


async def reject_proposal(db: AsyncSession, *, user: Dict[str, Any], proposal_id: int,
                          expected_version: int, reason: str, idempotency_key: str,
                          request_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = int(user.get("tenant_id") or 0)
    prop = await _load_proposal(db, tenant_id, proposal_id, for_update=True)
    if not prop:
        raise NotFound()
    if prop.get("idempotency_key") == idempotency_key and prop["status"] == "rejected":
        return {"proposal_id": proposal_id, "run_id": prop["run_id"],
                "status": "rejected", "idempotent": True}
    if prop["status"] != "awaiting_approval":
        raise Conflict(f"proposal is {prop['status']}, not awaiting approval")

    policy = await get_policy(db, tenant_id)
    allowed, why = can_approve(
        user, policy, action_type=ActionType(prop["action_type"]),
        risk_level=_risk(prop), target_store_ids=list(prop.get("target_store_ids") or []),
        proposal_tenant_id=tenant_id)
    if not allowed:
        raise Forbidden(why)

    try:
        result = await _cas_update(db, proposal_id, tenant_id, expected_version, {
            "status": "rejected", "rejection_reason": reason,
            "approved_by": user.get("email"), "idempotency_key": idempotency_key,
            "version": expected_version + 1})
    except IntegrityError:
        await db.rollback()
        raise Conflict("idempotency key already used on another proposal")
    if result.rowcount == 0:
        await db.rollback()
        raise Conflict()
    await _finalise_run_status(db, tenant_id, prop["run_id"], "rejected")
    await _event(db, tenant_id, prop["run_id"], proposal_id, "approval.rejected",
                 user.get("email") or "system", user.get("id"), {"reason": reason},
                 request_id)
    await db.commit()
    return {"proposal_id": proposal_id, "run_id": prop["run_id"], "status": "rejected"}


async def cancel_proposal(db: AsyncSession, *, user: Dict[str, Any], proposal_id: int,
                          expected_version: int,
                          request_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_id = int(user.get("tenant_id") or 0)
    prop = await _load_proposal(db, tenant_id, proposal_id, for_update=True)
    if not prop:
        raise NotFound()
    if prop["status"] in ("cancelled",):
        return {"proposal_id": proposal_id, "run_id": prop["run_id"],
                "status": "cancelled", "idempotent": True}
    if prop["status"] not in ("awaiting_approval", "approved"):
        raise Conflict(f"cannot cancel a proposal that is {prop['status']}")

    result = await _cas_update(db, proposal_id, tenant_id, expected_version, {
        "status": "cancelled", "version": expected_version + 1})
    if result.rowcount == 0:
        await db.rollback()
        raise Conflict()
    await _finalise_run_status(db, tenant_id, prop["run_id"], "cancelled")
    await _event(db, tenant_id, prop["run_id"], proposal_id, "proposal.cancelled",
                 user.get("email") or "system", user.get("id"), {}, request_id)
    await db.commit()
    return {"proposal_id": proposal_id, "run_id": prop["run_id"], "status": "cancelled"}


# ---------------------------------------------------------------------------
# Execution (draft-only) + revalidation
# ---------------------------------------------------------------------------

_ACTION_TO_DRAFT_TYPE = {
    ActionType.REPLENISHMENT_DRAFT.value: "purchase_order",
    ActionType.STOCK_TRANSFER_DRAFT.value: "review_task",
    ActionType.INVESTIGATION_TASK.value: "review_task",
}


async def execute_proposal(db: AsyncSession, *, user: Dict[str, Any], proposal_id: int,
                           request_id: Optional[str] = None) -> Dict[str, Any]:
    """Revalidate against live data, then write the INTERNAL draft and schedule
    measurement. Idempotent: an already-executed proposal returns its ref."""
    tenant_id = int(user.get("tenant_id") or 0)
    prop = await _load_proposal(db, tenant_id, proposal_id, for_update=True)
    if not prop:
        raise NotFound()

    if prop["status"] == "executed" and prop.get("executed_ref"):
        return {"proposal_id": proposal_id, "run_id": prop["run_id"], "status": "executed",
                "executed_ref": prop["executed_ref"], "idempotent": True}
    # Only an approved (or previously-failed) proposal is executable — this status
    # gate is the guard that stops an un-approved proposal ever being executed,
    # even though this function is not itself route-mounted.
    if prop["status"] not in ("approved", "execution_failed"):
        raise Conflict(f"proposal is {prop['status']}, not approved for execution")

    policy = await get_policy(db, tenant_id)
    version = prop["version"]

    # --- REVALIDATE ---------------------------------------------------------
    ok, detail = await _revalidate(db, tenant_id, prop, policy)
    if not ok:
        await _cas_update(db, proposal_id, tenant_id, version, {
            "status": "superseded", "version": version + 1})
        await _finalise_run_status(db, tenant_id, prop["run_id"], "escalated")
        await _event(db, tenant_id, prop["run_id"], proposal_id,
                     "execution.aborted_revalidation",
                     user.get("email") or "system", user.get("id"),
                     {"detail": detail}, request_id)
        await db.commit()
        return {"proposal_id": proposal_id, "run_id": prop["run_id"],
                "status": "superseded", "revalidation": detail}

    # --- EXECUTE (draft-only) ----------------------------------------------
    # On any failure the proposal is marked 'execution_failed' (durable + retryable
    # via a replayed approve) rather than left stuck 'approved' with no draft.
    try:
        draft_id = await _create_internal_draft(db, tenant_id, prop, user)
        executed_ref = f"action_draft:{draft_id}"
        result = await _cas_update(db, proposal_id, tenant_id, version, {
            "status": "executed", "executed_ref": executed_ref,
            "executed_at": datetime.now(timezone.utc), "version": version + 1})
        if result.rowcount == 0:
            await db.rollback()
            raise Conflict()
        # Schedule measurement by handing the finding to the existing worker loop.
        await _schedule_measurement(db, tenant_id, prop, user)
        await _finalise_run_status(db, tenant_id, prop["run_id"], "measuring")
        await _event(db, tenant_id, prop["run_id"], proposal_id, "action.executed",
                     user.get("email") or "system", user.get("id"),
                     {"executed_ref": executed_ref, "draft_only": True}, request_id)
        await db.commit()
    except Conflict:
        raise
    except Exception as exc:
        logger.exception("operations execution failed for proposal %s", proposal_id)
        await db.rollback()
        # Durable, retryable marker — the approved action is not silently dropped.
        await _cas_update(db, proposal_id, tenant_id, version, {
            "status": "execution_failed", "version": version + 1})
        await _event(db, tenant_id, prop["run_id"], proposal_id, "execution.failed",
                     user.get("email") or "system", user.get("id"),
                     {"error": str(exc)[:300]}, request_id)
        await db.commit()
        raise ApprovalError("execution failed — the approval stands and can be retried",
                            code=500)
    return {"proposal_id": proposal_id, "run_id": prop["run_id"], "status": "executed",
            "executed_ref": executed_ref, "draft_only": True}


async def _revalidate(db: AsyncSession, tenant_id: int, prop: Dict,
                      policy: OperationsPolicy) -> Tuple[bool, str]:
    """Recompute the key quantity against LIVE inventory and compare to what was
    approved. Investigations have no inventory to drift, so they pass unless the
    finding was resolved in the meantime."""
    action_type = prop["action_type"]
    params = prop.get("calculated_parameters") or {}
    approved_qty = params.get("quantity")

    if action_type == ActionType.INVESTIGATION_TASK.value:
        status = (await db.execute(
            text("SELECT status FROM findings WHERE id = :f AND tenant_id = :t"),
            {"f": prop.get("finding_id"), "t": tenant_id})).scalar_one_or_none()
        if status == "resolved":
            return False, "finding was resolved before the task could be created"
        return True, "no inventory to revalidate"

    item_ids = list(prop.get("target_item_ids") or [])
    store_ids = list(prop.get("target_store_ids") or [])
    if not item_ids or not store_ids or approved_qty is None:
        return False, "cannot revalidate — missing item/store/quantity on the proposal"

    snaps = await get_inventory_state(db, tenant_id=tenant_id, item_id=item_ids[0],
                                      store_ids=store_ids)
    by_store = {s["store_id"]: s for s in snaps}

    if action_type == ActionType.REPLENISHMENT_DRAFT.value:
        dest = by_store.get(store_ids[0])
        if not dest:
            return False, "inventory snapshot for the target store is no longer available"
        calc = calculate_replenishment(
            current_stock=dest.get("current_stock") or 0,
            daily_velocity=dest.get("average_daily_sales") or 0,
            settings=policy.replenishment, reorder_point=dest.get("reorder_point"))
        if not calc.is_actionable:
            return False, "replenishment is no longer justified against current stock"
        if materially_changed(policy, float(approved_qty), float(calc.quantity)):
            return False, (f"quantity moved from {approved_qty} to {calc.quantity} "
                           "since approval — fresh approval required")
        return True, "revalidated"

    if action_type == ActionType.STOCK_TRANSFER_DRAFT.value:
        src_id = params.get("source_store_id")
        dst_id = params.get("destination_store_id")
        src, dst = by_store.get(src_id), by_store.get(dst_id)
        if not src or not dst:
            return False, "inventory for the source or destination store is unavailable"
        calc = calculate_transfer(
            source_stock=src.get("current_stock") or 0,
            source_velocity=src.get("average_daily_sales") or 0,
            destination_stock=dst.get("current_stock") or 0,
            destination_velocity=dst.get("average_daily_sales") or 0,
            settings=policy.transfer)
        if not calc.is_actionable:
            return False, "transfer is no longer safe against current stock"
        if materially_changed(policy, float(approved_qty), float(calc.quantity)):
            return False, (f"transfer quantity moved from {approved_qty} to "
                           f"{calc.quantity} since approval — fresh approval required")
        return True, "revalidated"

    return False, f"unsupported action type {action_type}"


async def _create_internal_draft(db: AsyncSession, tenant_id: int, prop: Dict,
                                 user: Dict[str, Any]) -> int:
    """Write the concrete INTERNAL artifact into the existing action_drafts table.
    Clearly a draft: created_by='copilot', status='draft'. Never external."""
    draft_type = _ACTION_TO_DRAFT_TYPE.get(prop["action_type"], "review_task")
    payload = {
        "operations_proposal_id": prop["id"],
        "calculated_parameters": prop.get("calculated_parameters") or {},
        "draft_only": True,
        "note": "Internal draft created by the Operations Copilot after human "
                "approval. Not submitted to any supplier or external system.",
    }
    return (await db.execute(
        text("INSERT INTO action_drafts "
             "(tenant_id, finding_id, draft_type, status, title, summary, payload, "
             " source_action_type, created_by) VALUES "
             "(:t, :f, :dt, 'draft', :title, :summary, CAST(:payload AS jsonb), "
             " :src, 'copilot') RETURNING id"),
        {"t": tenant_id, "f": prop.get("finding_id"), "dt": draft_type,
         "title": prop.get("title"), "summary": "Approved by the Operations Copilot; "
         "internal draft only.", "payload": json.dumps(payload),
         "src": prop["action_type"]},
    )).scalar_one()


async def _schedule_measurement(db: AsyncSession, tenant_id: int, prop: Dict,
                                user: Dict[str, Any]) -> None:
    """Hand the finding to the worker's existing measure loop by stamping
    action_accepted_at — the same signal the findings loop already uses, so the
    outcome (metric_before/after) is proven by the same job, not a fork."""
    if prop.get("finding_id") is None:
        return
    await db.execute(
        text("UPDATE findings SET action_accepted_at = now(), "
             "action_accepted_by = :by WHERE id = :f AND tenant_id = :t "
             "AND action_accepted_at IS NULL"),
        {"by": user.get("email") or "copilot", "f": prop["finding_id"], "t": tenant_id})


async def _finalise_run_status(db: AsyncSession, tenant_id: int, run_id: int,
                               status: str) -> None:
    await db.execute(
        text("UPDATE operations_runs SET status = :s WHERE id = :r AND tenant_id = :t"),
        {"s": status, "r": run_id, "t": tenant_id})


def is_expired_row(expires_at: datetime, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now >= expires_at
