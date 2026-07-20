"""Stage 4 — the approval engine. Policies are CONFIGURATION, not hard-coded.

WHY CONFIGURATION. Every retailer has different thresholds, and they change more
often than software ships. Hard-coding "CFO signs off above 25,000 AED" means a
code change (and a deploy) when finance revises the limit. Here the ladder lives
in `flywheel_approval_policies` rows, seeded with sensible demo thresholds in
migration 075 and editable by an admin.

STACKED AND PARALLEL. Steps sharing a `step_order` run in PARALLEL — inventory
review and procurement review both happen after simulation and neither waits for
the other. Steps with a higher order are sequential gates. A request is approved
only when EVERY step is approved; ONE rejection rejects the whole request, which
is the correct default for spending money.

WHAT THIS ENGINE REFUSES TO DO: it never approves anything itself, never emails
anyone, and never bypasses the existing RBAC. `can_decide` checks the acting
user against the step's required role AND permission using the platform's own
`user['permissions']` dict — Flywheel does not get its own parallel authorization.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: How long an approval stays valid before it must be re-sought. An approval
#: given against three-week-old numbers is not an approval of today's campaign
#: (§22 lists an expired approval as a guardrail breach).
APPROVAL_TTL_DAYS = 14


async def required_steps(
    db: AsyncSession, *, tenant_id: int, applies_to: str,
    discount_exposure: Decimal, procurement_exposure: Decimal, store_count: int,
) -> List[Dict[str, Any]]:
    """Which policy steps apply to this request's numbers.

    A policy applies when ALL of its thresholds are met. Thresholds default to 0,
    so a policy with no thresholds always applies (e.g. marketing sign-off).
    """
    rows = (await db.execute(
        text("""SELECT id, step_order, step_label, required_role, required_permission,
                       min_discount_aed, min_procurement_aed, min_store_count
                  FROM flywheel_approval_policies
                 WHERE tenant_id = :t AND applies_to = :a AND is_active = TRUE
                 ORDER BY step_order, id"""),
        {"t": tenant_id, "a": applies_to},
    )).fetchall()

    steps: List[Dict[str, Any]] = []
    for (pid, order, label, role, permission,
         min_discount, min_procurement, min_stores) in rows:
        if money(discount_exposure) < money(min_discount):
            continue
        if money(procurement_exposure) < money(min_procurement):
            continue
        if store_count < int(min_stores or 0):
            continue
        steps.append({
            "policy_id": int(pid), "step_order": int(order), "step_label": label,
            "required_role": role, "required_permission": permission,
        })
    return steps


async def create_request(
    db: AsyncSession, *, tenant_id: int, request_type: str,
    campaign_id: Optional[int] = None, requisition_id: Optional[int] = None,
    discount_exposure: Decimal = ZERO, procurement_exposure: Decimal = ZERO,
    store_count: int = 0, expected_roi: Optional[float] = None,
    summary: Optional[Dict[str, Any]] = None, requested_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Open an approval request and materialise its step chain.

    Idempotent per subject: an existing PENDING request for the same campaign or
    requisition is returned rather than duplicated, so a double-click on
    "Submit for approval" cannot create two competing chains.
    """
    subject_clause = "campaign_id = :cid" if campaign_id else "requisition_id = :rid"
    existing = (await db.execute(
        text(f"""SELECT id FROM flywheel_approval_requests
                  WHERE tenant_id = :t AND status = 'pending' AND {subject_clause}
                  LIMIT 1"""),
        {"t": tenant_id, "cid": campaign_id, "rid": requisition_id},
    )).fetchone()
    if existing:
        return {"request_id": int(existing[0]), "created": False,
                "detail": "A pending approval request already exists for this subject"}

    applies_to = "campaign" if campaign_id else "requisition"
    steps = await required_steps(
        db, tenant_id=tenant_id, applies_to=applies_to,
        discount_exposure=discount_exposure,
        procurement_exposure=procurement_exposure, store_count=store_count)

    if not steps:
        # No policy matched. Rather than silently auto-approving spend, we
        # require an explicit marketing step — absence of policy is not consent.
        steps = [{"policy_id": None, "step_order": 1, "step_label": "Marketing",
                  "required_role": "regional_manager",
                  "required_permission": "can_manage_promotions"}]

    row = (await db.execute(
        text("""INSERT INTO flywheel_approval_requests
                   (tenant_id, campaign_id, requisition_id, request_type, status,
                    discount_exposure_aed, procurement_exposure_aed, expected_roi,
                    summary, requested_by, expires_at)
                VALUES (:t, :cid, :rid, :rt, 'pending', :de, :pe, :roi,
                        CAST(:s AS JSONB), :by, now() + (:ttl || ' days')::interval)
                RETURNING id"""),
        {"t": tenant_id, "cid": campaign_id, "rid": requisition_id, "rt": request_type,
         "de": money(discount_exposure), "pe": money(procurement_exposure),
         "roi": expected_roi, "s": json.dumps(summary or {}), "by": requested_by,
         "ttl": str(APPROVAL_TTL_DAYS)},
    )).fetchone()
    request_id = int(row[0])

    for step in steps:
        await db.execute(
            text("""INSERT INTO flywheel_approval_steps
                       (tenant_id, request_id, policy_id, step_order, step_label,
                        required_role, required_permission, status)
                    VALUES (:t, :r, :p, :o, :l, :role, :perm, 'pending')"""),
            {"t": tenant_id, "r": request_id, "p": step["policy_id"],
             "o": step["step_order"], "l": step["step_label"],
             "role": step["required_role"], "perm": step["required_permission"]},
        )

    parallel_groups = len({s["step_order"] for s in steps})
    logger.info("flywheel.approval created request=%s steps=%s groups=%s",
                request_id, len(steps), parallel_groups)
    return {
        "request_id": request_id, "created": True,
        "steps": steps, "step_count": len(steps),
        "sequential_stages": parallel_groups,
        "detail": f"{len(steps)} approval step(s) across {parallel_groups} stage(s); "
                  f"steps sharing a stage run in parallel",
    }


def can_decide(user: Dict[str, Any], step: Dict[str, Any]) -> bool:
    """May this user decide this step?

    Reuses the platform's role + permission model exactly. super_admin passes any
    step — consistent with `auth_deps.can_access_store`, where super_admin is the
    platform's break-glass role.
    """
    if user.get("role") == "super_admin":
        return True
    if step.get("required_role") and user.get("role") != step["required_role"]:
        return False
    permission = step.get("required_permission")
    if permission and not user.get("permissions", {}).get(permission):
        return False
    return True


async def decide_step(
    db: AsyncSession, *, tenant_id: int, step_id: int, user: Dict[str, Any],
    decision: str, comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Record approve / reject / request-changes on one step.

    Locks the step row so two approvers clicking simultaneously cannot both
    record a decision on the same step. Returns the resulting REQUEST state,
    since that is what the caller acts on.
    """
    if decision not in ("approved", "rejected", "changes_requested"):
        raise ValueError(f"Invalid decision '{decision}'")

    row = (await db.execute(
        text("""SELECT s.request_id, s.status, s.required_role, s.required_permission,
                       s.step_label, r.campaign_id, r.requisition_id, r.expires_at
                  FROM flywheel_approval_steps s
                  JOIN flywheel_approval_requests r ON r.id = s.request_id
                 WHERE s.id = :s AND s.tenant_id = :t
                 FOR UPDATE OF s"""),
        {"s": step_id, "t": tenant_id},
    )).fetchone()
    if not row:
        raise ValueError(f"Approval step {step_id} not found")

    request_id, status, role, permission, label, campaign_id, requisition_id, expires_at = row

    if status != "pending":
        return {"applied": False, "detail": f"Step '{label}' is already {status}",
                "request_id": int(request_id)}

    if not can_decide(user, {"required_role": role, "required_permission": permission}):
        raise PermissionError(
            f"Step '{label}' requires role '{role}'"
            + (f" with permission '{permission}'" if permission else ""))

    # An expired approval window means the numbers are stale — refuse rather
    # than let someone approve a fortnight-old exposure figure.
    from datetime import datetime, timezone
    if expires_at and expires_at < datetime.now(timezone.utc):
        await db.execute(
            text("UPDATE flywheel_approval_requests SET status = 'expired' WHERE id = :r"),
            {"r": request_id})
        return {"applied": False, "detail": "Approval window has expired; resubmit",
                "request_id": int(request_id), "request_status": "expired"}

    await db.execute(
        text("""UPDATE flywheel_approval_steps
                   SET status = :d, decided_by = :u, decided_at = now(), comment = :c
                 WHERE id = :s AND tenant_id = :t"""),
        {"d": decision, "u": user.get("id"), "c": comment, "s": step_id, "t": tenant_id},
    )

    return await _reconcile_request(db, tenant_id=tenant_id, request_id=int(request_id),
                                    campaign_id=campaign_id, requisition_id=requisition_id)


async def _reconcile_request(
    db: AsyncSession, *, tenant_id: int, request_id: int,
    campaign_id: Optional[int], requisition_id: Optional[int],
) -> Dict[str, Any]:
    """Recompute the request's status from its steps.

    ONE rejection rejects the whole request. ALL approvals approve it. Anything
    else leaves it pending. Deliberately strict: partial approval of spending
    is not a state a finance team would recognise.
    """
    rows = (await db.execute(
        text("""SELECT status, COUNT(*) FROM flywheel_approval_steps
                 WHERE request_id = :r AND tenant_id = :t GROUP BY status"""),
        {"r": request_id, "t": tenant_id},
    )).fetchall()
    counts = {status: int(count) for status, count in rows}
    total = sum(counts.values())

    if counts.get("rejected"):
        new_status = "rejected"
    elif counts.get("changes_requested"):
        new_status = "changes_requested"
    elif counts.get("approved", 0) + counts.get("skipped", 0) == total:
        new_status = "approved"
    else:
        new_status = "pending"

    if new_status != "pending":
        await db.execute(
            text("""UPDATE flywheel_approval_requests
                       SET status = :s, resolved_at = now() WHERE id = :r AND tenant_id = :t"""),
            {"s": new_status, "r": request_id, "t": tenant_id},
        )
        if requisition_id and new_status in ("approved", "rejected"):
            await db.execute(
                text("""UPDATE flywheel_procurement_requisitions
                           SET status = :s, updated_at = now()
                         WHERE id = :rid AND tenant_id = :t"""),
                {"s": new_status, "rid": requisition_id, "t": tenant_id},
            )

    return {
        "applied": True, "request_id": request_id, "request_status": new_status,
        "campaign_id": campaign_id, "requisition_id": requisition_id,
        "steps_total": total, "steps_approved": counts.get("approved", 0),
        "steps_pending": counts.get("pending", 0),
        "fully_approved": new_status == "approved",
    }


async def request_detail(
    db: AsyncSession, *, tenant_id: int, request_id: int
) -> Optional[Dict[str, Any]]:
    """Full request + ordered step chain, for the Approval Inbox."""
    header = (await db.execute(
        text("""SELECT r.id, r.request_type, r.status, r.discount_exposure_aed,
                       r.procurement_exposure_aed, r.expected_roi, r.summary,
                       r.created_at, r.expires_at, r.campaign_id, r.requisition_id,
                       c.name, u.email
                  FROM flywheel_approval_requests r
                  LEFT JOIN flywheel_campaigns c ON c.id = r.campaign_id
                  LEFT JOIN users u ON u.id = r.requested_by
                 WHERE r.id = :r AND r.tenant_id = :t"""),
        {"r": request_id, "t": tenant_id},
    )).fetchone()
    if not header:
        return None

    steps = (await db.execute(
        text("""SELECT s.id, s.step_order, s.step_label, s.required_role,
                       s.required_permission, s.status, s.comment, s.decided_at, u.email
                  FROM flywheel_approval_steps s
                  LEFT JOIN users u ON u.id = s.decided_by
                 WHERE s.request_id = :r AND s.tenant_id = :t
                 ORDER BY s.step_order, s.id"""),
        {"r": request_id, "t": tenant_id},
    )).fetchall()

    step_list = [{
        "step_id": int(s[0]), "step_order": int(s[1]), "label": s[2],
        "required_role": s[3], "required_permission": s[4], "status": s[5],
        "comment": s[6], "decided_at": s[7].isoformat() if s[7] else None,
        "decided_by": s[8],
        # Steps sharing an order run at the same time — the UI draws them side by side.
        "parallel_group": int(s[1]),
    } for s in steps]

    approved = sum(1 for s in step_list if s["status"] == "approved")
    return {
        "request_id": int(header[0]), "request_type": header[1], "status": header[2],
        "discount_exposure_aed": str(money(header[3])),
        "procurement_exposure_aed": str(money(header[4])),
        "expected_roi": float(header[5]) if header[5] is not None else None,
        "summary": header[6] or {},
        "created_at": header[7].isoformat() if header[7] else None,
        "expires_at": header[8].isoformat() if header[8] else None,
        "campaign_id": header[9], "requisition_id": header[10],
        "campaign_name": header[11], "requested_by": header[12],
        "steps": step_list,
        "progress": {"approved": approved, "total": len(step_list),
                     "pct": round(approved / len(step_list) * 100) if step_list else 0},
    }


async def list_inbox(
    db: AsyncSession, *, tenant_id: int, user: Dict[str, Any],
    status: str = "pending", limit: int = 50,
) -> List[Dict[str, Any]]:
    """Approval requests visible to this user, flagged with whether THEY can act.

    Everyone in scope sees the queue (transparency), but `can_act` tells the UI
    which rows to make actionable — showing a disabled button with a reason is
    friendlier than hiding work that exists.
    """
    rows = (await db.execute(
        text("""SELECT r.id, r.request_type, r.status, r.discount_exposure_aed,
                       r.procurement_exposure_aed, r.expected_roi, r.created_at,
                       r.expires_at, r.campaign_id, c.name
                  FROM flywheel_approval_requests r
                  LEFT JOIN flywheel_campaigns c ON c.id = r.campaign_id
                 WHERE r.tenant_id = :t AND (:st = 'all' OR r.status = :st)
                 ORDER BY r.created_at DESC LIMIT :lim"""),
        {"t": tenant_id, "st": status, "lim": limit},
    )).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        pending_steps = (await db.execute(
            text("""SELECT step_label, required_role, required_permission
                      FROM flywheel_approval_steps
                     WHERE request_id = :r AND status = 'pending'
                     ORDER BY step_order"""),
            {"r": int(r[0])},
        )).fetchall()

        actionable = [{"label": s[0], "required_role": s[1], "required_permission": s[2]}
                      for s in pending_steps]
        can_act = any(can_decide(user, s) for s in actionable)

        out.append({
            "request_id": int(r[0]), "request_type": r[1], "status": r[2],
            "discount_exposure_aed": str(money(r[3])),
            "procurement_exposure_aed": str(money(r[4])),
            "expected_roi": float(r[5]) if r[5] is not None else None,
            "created_at": r[6].isoformat() if r[6] else None,
            "expires_at": r[7].isoformat() if r[7] else None,
            "campaign_id": r[8], "campaign_name": r[9],
            "awaiting": [s["label"] for s in actionable],
            "can_act": can_act,
        })
    return out
