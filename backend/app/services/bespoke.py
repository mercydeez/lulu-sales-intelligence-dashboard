"""Platform Console — the bespoke ("Rolls-Royce") request ledger.

When a client asks for something the product does not have, a platform developer
records the ask here and walks it through an explicit delivery pipeline. The brand
rule is HONESTY: the state machine refuses illegal jumps (a request cannot teleport
from `requested` to `delivered`), a `delivered` claim always carries its timestamp,
a `declined` always carries its reason, and every create/update is recorded as a
security audit event. The DB backs the two proof invariants with CHECK constraints
(migration 073) so not even a buggy writer can strip the evidence.

Access model: this is CROSS-TENANT control-plane data (a request may even predate
its tenant), gated by services/platform_access.require_platform_developer in the
route layer and NOT covered by RLS; migration 073 additionally revokes the
tenant-request role's (app_rw) privileges on the table so a tenant-path query bug
fails closed instead of reading every client's asks.

All functions take an AsyncSession and DO NOT commit — the caller owns the
transaction boundary.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The delivery pipeline. `declined` is reachable from every non-terminal state;
# `delivered` and `declined` are terminal (a delivered/declined request is
# history — a new ask gets a new row, keeping the ledger append-honest).
TRANSITIONS: Dict[str, Set[str]] = {
    "requested": {"scoped", "declined"},
    "scoped": {"approved", "declined"},
    "approved": {"building", "declined"},
    "building": {"delivered", "declined"},
    "delivered": set(),
    "declined": set(),
}

VALID_PRIORITIES = ("low", "medium", "high", "vip")

_COLUMNS = """id, tenant_id, title, client_description, status, priority,
              scoping_notes, estimate, ai_suggestion, delivered_at,
              created_by, updated_by, created_at, updated_at"""


def transition_error(current: str, new: str, *, has_reason: bool = False) -> Optional[str]:
    """Pure legality check for a status change — returns a human-readable refusal
    or None if the transition is legal. Testable without any DB."""
    if new not in TRANSITIONS:
        return (f"Unknown status {new!r}; valid statuses: "
                f"{', '.join(sorted(TRANSITIONS))}")
    if current not in TRANSITIONS:
        return f"Request is in unknown status {current!r}; refusing to transition"
    if new not in TRANSITIONS[current]:
        allowed = ", ".join(sorted(TRANSITIONS[current])) or "none — terminal status"
        return (f"Illegal transition {current!r} -> {new!r}; "
                f"allowed from {current!r}: {allowed}")
    if new == "declined" and not has_reason:
        return ("Declining requires scoping_notes explaining why — provide them in "
                "this update (or record them on the request first)")
    return None


def _serialize(row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row)
    for k in ("created_at", "updated_at", "delivered_at"):
        v = d.get(k)
        d[k] = v.isoformat() if hasattr(v, "isoformat") else v
    ai = d.get("ai_suggestion")
    if isinstance(ai, str):  # some drivers hand JSONB back as text
        try:
            d["ai_suggestion"] = json.loads(ai)
        except ValueError:
            pass
    return d


async def create_request(
    db: AsyncSession,
    *,
    tenant_id: Optional[int],
    title: str,
    client_description: str,
    priority: str,
    created_by: Optional[str],
    ai_suggestion: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a client's ask. Refuses garbage before touching the DB; the route
    layer validates too — this is defence in depth, not the primary gate."""
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"Unknown priority {priority!r}; valid: {', '.join(VALID_PRIORITIES)}")
    if not (title or "").strip() or not (client_description or "").strip():
        raise ValueError("title and client_description are required")
    row = (await db.execute(text(f"""
        INSERT INTO bespoke_requests
            (tenant_id, title, client_description, priority, ai_suggestion, created_by, updated_by)
        VALUES
            (:tenant_id, :title, :client_description, :priority,
             CAST(:ai_suggestion AS JSONB), :created_by, :created_by)
        RETURNING {_COLUMNS}
    """), {
        "tenant_id": tenant_id,
        "title": title.strip(),
        "client_description": client_description.strip(),
        "priority": priority,
        "ai_suggestion": json.dumps(ai_suggestion) if ai_suggestion is not None else None,
        "created_by": created_by,
    })).mappings().fetchone()
    rec = _serialize(dict(row))

    # Audit trail — best-effort by design of record_event (it never raises).
    from app.services.security_events import record_event
    await record_event(
        "bespoke_request_created", category="audit", severity="low",
        tenant_id=tenant_id, actor_email=created_by,
        detail=f"Bespoke request {rec['id']} created ({rec['priority']}): {rec['title']}",
    )
    return rec


async def list_requests(
    db: AsyncSession,
    status: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    if status is not None:
        if status not in TRANSITIONS:
            raise ValueError(f"Unknown status {status!r}; valid: {', '.join(sorted(TRANSITIONS))}")
        clauses.append("status = :status")
        params["status"] = status
    if tenant_id is not None:
        clauses.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (await db.execute(text(f"""
        SELECT {_COLUMNS} FROM bespoke_requests {where}
        ORDER BY created_at DESC, id DESC
    """), params)).mappings().all()
    return [_serialize(dict(r)) for r in rows]


async def get_request(db: AsyncSession, request_id: int) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text(f"""
        SELECT {_COLUMNS} FROM bespoke_requests WHERE id = :id
    """), {"id": request_id})).mappings().fetchone()
    return _serialize(dict(row)) if row else None


async def update_request(
    db: AsyncSession,
    request_id: int,
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    scoping_notes: Optional[str] = None,
    estimate: Optional[str] = None,
    actor: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Update a request; status changes must be legal per TRANSITIONS.

    Returns (row, None) on success, (None, error) on refusal. Refusals happen
    BEFORE any write. Transitioning to 'delivered' stamps delivered_at; to
    'declined' requires scoping_notes (in this call or already on the row).
    Same-status is treated as a no-op, not a transition (idempotent PATCH).
    """
    # Validate inputs before any DB work — fail closed, no partial writes.
    if status is not None and status not in TRANSITIONS:
        return None, (f"Unknown status {status!r}; valid statuses: "
                      f"{', '.join(sorted(TRANSITIONS))}")
    if priority is not None and priority not in VALID_PRIORITIES:
        return None, f"Unknown priority {priority!r}; valid: {', '.join(VALID_PRIORITIES)}"

    row = await get_request(db, request_id)
    if row is None:
        return None, f"Bespoke request {request_id} not found"

    transition: Optional[Tuple[str, str]] = None
    if status is not None and status != row["status"]:
        has_reason = bool(((scoping_notes if scoping_notes is not None
                            else row.get("scoping_notes")) or "").strip())
        err = transition_error(row["status"], status, has_reason=has_reason)
        if err:
            return None, err
        transition = (row["status"], status)

    sets = ["updated_at = now()", "updated_by = :actor"]
    params: Dict[str, Any] = {"id": request_id, "actor": actor}
    if priority is not None:
        sets.append("priority = :priority")
        params["priority"] = priority
    if scoping_notes is not None:
        sets.append("scoping_notes = :scoping_notes")
        params["scoping_notes"] = scoping_notes
    if estimate is not None:
        sets.append("estimate = :estimate")
        params["estimate"] = estimate
    if transition:
        sets.append("status = :status")
        params["status"] = status
        if status == "delivered":
            # PROOF: the delivered claim carries its timestamp (also DB-enforced).
            sets.append("delivered_at = now()")

    await db.execute(text(
        f"UPDATE bespoke_requests SET {', '.join(sets)} WHERE id = :id"
    ), params)

    detail = f"Bespoke request {request_id} updated"
    if transition:
        detail += f": {transition[0]} -> {transition[1]}"
    from app.services.security_events import record_event
    await record_event(
        "bespoke_request_updated", category="audit",
        severity="medium" if transition else "low",
        tenant_id=row.get("tenant_id"), actor_email=actor, detail=detail,
    )
    return await get_request(db, request_id), None
