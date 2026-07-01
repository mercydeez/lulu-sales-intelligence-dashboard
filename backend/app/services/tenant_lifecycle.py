"""
Tenant lifecycle state machine + access gating (UAE SaaS Phase 2).

The pure parts (allowed states, transition validation, "is this status allowed to
use the product") have no I/O so they unit-test in isolation and back both the API
and the access-enforcement hook in get_current_user. The DB writes (transition +
audit event) live in async helpers at the bottom.
"""
from __future__ import annotations

from typing import Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# All lifecycle states (kept in sync with the migration 042 CHECK constraint).
STATES: Set[str] = {
    "trial", "onboarding", "active", "payment_pending", "past_due",
    "suspended", "cancelled", "deletion_requested", "deleted",
}

# Statuses that may still use the product/API. payment_pending/past_due keep
# access (dunning grace — you chase payment, you don't lock people out mid-sale);
# deletion_requested keeps access until the operator actually erases the data.
ACTIVE_STATES: Set[str] = {
    "trial", "onboarding", "active", "payment_pending", "past_due", "deletion_requested",
}
# Hard-blocked from product/API (super-admin operators still bypass — see gating).
BLOCKED_STATES: Set[str] = {"suspended", "cancelled", "deleted"}

# Allowed transitions. Operators drive these; the graph keeps obvious nonsense out
# (e.g. you can't go from 'deleted' back to 'active'). 'deleted' is terminal.
_TRANSITIONS = {
    "trial":              {"onboarding", "active", "payment_pending", "suspended", "cancelled"},
    "onboarding":         {"active", "trial", "suspended", "cancelled"},
    "active":             {"payment_pending", "past_due", "suspended", "cancelled", "deletion_requested"},
    "payment_pending":    {"active", "past_due", "suspended", "cancelled"},
    "past_due":           {"active", "suspended", "cancelled"},
    "suspended":          {"active", "cancelled", "deletion_requested"},
    "cancelled":          {"active", "deletion_requested"},
    "deletion_requested": {"deleted", "active", "cancelled"},
    "deleted":            set(),  # terminal
}


def is_access_allowed(status: Optional[str]) -> bool:
    """Whether a tenant in this status may reach product/API endpoints.
    Unknown/None falls back to allowed (the demo tenant + legacy rows are 'active')."""
    if not status:
        return True
    return status not in BLOCKED_STATES


def validate_transition(current: str, target: str) -> Tuple[bool, Optional[str]]:
    """Return (ok, error). Same-status is a no-op error; unknown target rejected."""
    if target not in STATES:
        return False, f"Unknown status '{target}'. One of: {', '.join(sorted(STATES))}"
    if current == target:
        return False, f"Tenant is already '{target}'"
    allowed = _TRANSITIONS.get(current, set())
    if target not in allowed:
        return False, (f"Cannot move a '{current}' tenant to '{target}'. "
                       f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal)'}")
    return True, None


async def get_tenant_status(db: AsyncSession, tenant_id: int) -> Optional[str]:
    row = (await db.execute(
        text("SELECT status FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )).fetchone()
    return row.status if row else None


async def change_tenant_status(
    db: AsyncSession, tenant_id: int, target: str, *,
    reason: Optional[str], actor_id: Optional[int], actor_email: Optional[str],
) -> Tuple[Optional[dict], Optional[str]]:
    """Validate + apply a lifecycle transition and append an audit event.
    Returns (result, None) or (None, error). Caller commits."""
    current = await get_tenant_status(db, tenant_id)
    if current is None:
        return None, "Tenant not found"
    ok, err = validate_transition(current, target)
    if not ok:
        return None, err

    await db.execute(text("""
        UPDATE tenants
           SET status = :s, status_reason = :r,
               status_changed_at = CURRENT_TIMESTAMP, status_changed_by = :uid,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = :tid
    """), {"s": target, "r": reason, "uid": actor_id, "tid": tenant_id})

    await db.execute(text("""
        INSERT INTO tenant_status_events
            (tenant_id, from_status, to_status, reason, changed_by, changed_email)
        VALUES (:tid, :frm, :to, :r, :uid, :email)
    """), {"tid": tenant_id, "frm": current, "to": target, "r": reason,
           "uid": actor_id, "email": actor_email})

    return {"tenant_id": tenant_id, "from_status": current, "to_status": target,
            "reason": reason}, None
