"""The campaign state machine — persisted, service-validated, append-only history.

WHY A SERVICE AND NOT A STATUS COLUMN. If any writer could `UPDATE campaigns SET
status = 'ACTIVE'`, then a rejected campaign could go live, a cancelled campaign
could re-activate and release budget twice, and the audit trail would be a
sequence of unexplained jumps. The CHECK constraint in migration 075 only
constrains the VALUE SET; legality of a TRANSITION lives here, in one place.

Every transition writes a `flywheel_campaign_transitions` row with actor, reason and
request id — so "who took this live, and why" is always answerable.
"""
from __future__ import annotations

import logging
from typing import Dict, FrozenSet, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import CampaignStatus as S

logger = logging.getLogger(__name__)


class TransitionError(ValueError):
    """Raised when a caller attempts an illegal state jump. Surfaced as HTTP 409
    by the route layer — it is a conflict with the campaign's current reality,
    not a malformed request."""


#: The legal graph. Read it as: from THIS state you may go to ANY of these.
#:
#: Design notes worth keeping:
#:  * CANCELLED is reachable from every non-terminal state — an operator must
#:    always be able to stop a campaign, and cancelling releases reservations.
#:  * PAUSED ⇄ ACTIVE is a two-way edge (guardrail pauses, human resumes).
#:  * MEASURED is the only terminal state that follows COMPLETED; measurement is
#:    what closes the Flywheel loop, so a campaign is not "done" until measured.
#:  * Approval states can fall BACK to SIMULATED on changes_requested, so a
#:    rejected campaign is re-workable rather than dead.
TRANSITIONS: Dict[S, FrozenSet[S]] = {
    S.DRAFT: frozenset({S.AUDIENCE_READY, S.CANCELLED}),
    S.AUDIENCE_READY: frozenset({S.SIMULATED, S.DRAFT, S.CANCELLED}),
    S.SIMULATED: frozenset({
        S.PENDING_INVENTORY_REVIEW, S.PENDING_PROCUREMENT_REVIEW,
        S.PENDING_FINANCE_APPROVAL, S.PENDING_MARKETING_APPROVAL,
        S.AUDIENCE_READY, S.CANCELLED,
    }),
    # The four review states are siblings: the approval engine decides which are
    # required, and they may complete in parallel. Each can advance to any other
    # still-outstanding review, or straight to APPROVED when none remain.
    S.PENDING_INVENTORY_REVIEW: frozenset({
        S.PENDING_PROCUREMENT_REVIEW, S.PENDING_FINANCE_APPROVAL,
        S.PENDING_MARKETING_APPROVAL, S.APPROVED, S.SIMULATED, S.CANCELLED,
    }),
    S.PENDING_PROCUREMENT_REVIEW: frozenset({
        S.PENDING_INVENTORY_REVIEW, S.PENDING_FINANCE_APPROVAL,
        S.PENDING_MARKETING_APPROVAL, S.APPROVED, S.SIMULATED, S.CANCELLED,
    }),
    S.PENDING_FINANCE_APPROVAL: frozenset({
        S.PENDING_INVENTORY_REVIEW, S.PENDING_PROCUREMENT_REVIEW,
        S.PENDING_MARKETING_APPROVAL, S.APPROVED, S.SIMULATED, S.CANCELLED,
    }),
    S.PENDING_MARKETING_APPROVAL: frozenset({
        S.PENDING_INVENTORY_REVIEW, S.PENDING_PROCUREMENT_REVIEW,
        S.PENDING_FINANCE_APPROVAL, S.APPROVED, S.SIMULATED, S.CANCELLED,
    }),
    S.APPROVED: frozenset({S.SCHEDULED, S.ACTIVE, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.ACTIVE, S.CANCELLED}),
    S.ACTIVE: frozenset({S.PAUSED, S.COMPLETED, S.CANCELLED}),
    S.PAUSED: frozenset({S.ACTIVE, S.COMPLETED, S.CANCELLED}),
    S.COMPLETED: frozenset({S.MEASURED}),
    # Terminal.
    S.CANCELLED: frozenset(),
    S.MEASURED: frozenset(),
}

#: States in which a campaign may issue offers. Anything else returns NO_ACTION
#: from the decision endpoint — checked live, not cached.
LIVE_STATES: FrozenSet[S] = frozenset({S.ACTIVE})

#: States whose budget reservations are still outstanding and must be released
#: when the campaign ends.
RESERVING_STATES: FrozenSet[S] = frozenset({
    S.APPROVED, S.SCHEDULED, S.ACTIVE, S.PAUSED,
})


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        allowed = sorted(s.value for s in TRANSITIONS.get(current, frozenset()))
        raise TransitionError(
            f"Illegal campaign transition {current.value} → {target.value}. "
            f"Allowed from {current.value}: {', '.join(allowed) or '(terminal)'}"
        )


async def transition(
    db: AsyncSession,
    *,
    tenant_id: int,
    campaign_id: int,
    target: S,
    actor_user_id: Optional[int] = None,
    actor_kind: str = "user",
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
    pause_reason: Optional[str] = None,
) -> S:
    """Validate and apply a transition, recording it in the history table.

    Locks the campaign row FOR UPDATE so two concurrent transitions cannot both
    read the same `from` state and both believe they were legal — the classic
    lost-update that would, for instance, let a campaign be approved and
    cancelled at the same instant.

    Does NOT commit: the caller composes this with the rest of its transaction
    (e.g. activation also reserves budget — either both happen or neither does).
    """
    row = (await db.execute(
        text("SELECT status FROM flywheel_campaigns "
             "WHERE id = :cid AND tenant_id = :tid FOR UPDATE"),
        {"cid": campaign_id, "tid": tenant_id},
    )).fetchone()
    if row is None:
        raise TransitionError(f"Campaign {campaign_id} not found in tenant {tenant_id}")

    current = S(row[0])
    if current == target:
        return current  # idempotent no-op; do not spam the history table

    assert_transition(current, target)

    # PAUSED carries a DB-level proof constraint (pause_reason NOT NULL). Give a
    # clear service-level error rather than letting Postgres raise a check
    # violation the operator cannot interpret.
    if target == S.PAUSED and not (pause_reason or reason):
        raise TransitionError("Pausing a campaign requires a reason")

    # The branching happens HERE rather than in SQL CASE expressions. Besides
    # being clearer — we already know the target — it avoids an asyncpg failure:
    # repeating one bind across several CASE arms makes Postgres deduce
    # conflicting types for the same parameter ("inconsistent types deduced for
    # parameter $1"). Each bind below is used exactly once, in one position.
    is_pausing = target == S.PAUSED
    #: Set ONCE and never overwritten — a resume from PAUSED must not rewrite
    #: when the campaign originally went live.
    stamp_activated = target == S.ACTIVE
    stamp_completed = target in (S.COMPLETED, S.CANCELLED)

    await db.execute(
        text("""
            UPDATE flywheel_campaigns
               SET status       = :status,
                   pause_reason = CASE WHEN :is_pausing THEN :pause_reason
                                       ELSE pause_reason END,
                   paused_at    = CASE WHEN :is_pausing THEN now()
                                       ELSE paused_at END,
                   activated_at = CASE WHEN :stamp_activated AND activated_at IS NULL
                                       THEN now() ELSE activated_at END,
                   completed_at = CASE WHEN :stamp_completed THEN now()
                                       ELSE completed_at END,
                   updated_at   = now()
             WHERE id = :cid AND tenant_id = :tid
        """),
        {"status": target.value, "cid": campaign_id, "tid": tenant_id,
         "is_pausing": is_pausing, "stamp_activated": stamp_activated,
         "stamp_completed": stamp_completed,
         "pause_reason": pause_reason or reason},
    )

    await db.execute(
        text("""
            INSERT INTO flywheel_campaign_transitions
                (tenant_id, campaign_id, from_status, to_status,
                 actor_user_id, actor_kind, reason, request_id)
            VALUES (:tid, :cid, :frm, :to, :actor, :kind, :reason, :rid)
        """),
        {"tid": tenant_id, "cid": campaign_id, "frm": current.value,
         "to": target.value, "actor": actor_user_id, "kind": actor_kind,
         "reason": reason, "rid": request_id},
    )

    logger.info("flywheel.campaign.transition campaign=%s %s→%s actor=%s",
                campaign_id, current.value, target.value, actor_kind)
    return target


async def current_status(db: AsyncSession, tenant_id: int, campaign_id: int) -> Optional[S]:
    row = (await db.execute(
        text("SELECT status FROM flywheel_campaigns WHERE id = :cid AND tenant_id = :tid"),
        {"cid": campaign_id, "tid": tenant_id},
    )).fetchone()
    return S(row[0]) if row else None


def mermaid_diagram() -> str:
    """Render the live graph as Mermaid.

    Generated FROM `TRANSITIONS` rather than hand-drawn, so the diagram in
    docs/flywheel/state_machine.md can never drift from the enforced rules — the
    docs test regenerates and compares it.
    """
    lines = ["stateDiagram-v2", "    [*] --> DRAFT"]
    for src in TRANSITIONS:
        for dst in sorted(TRANSITIONS[src], key=lambda s: s.value):
            lines.append(f"    {src.value} --> {dst.value}")
    lines.append("    CANCELLED --> [*]")
    lines.append("    MEASURED --> [*]")
    return "\n".join(lines)
