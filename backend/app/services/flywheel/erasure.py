"""Lawful erasure — the ONLY sanctioned way past the append-only guard.

WHY THIS EXISTS. Migration 077 makes `flywheel_readouts` and
`flywheel_preregistrations` append-only, because a measurement you can rewrite
after seeing it is not evidence. But an absolutely immutable table is the wrong
design, for two reasons that both bite in production:

  * ON DELETE CASCADE stops working. Deleting a campaign, or offboarding a
    tenant, fails with a trigger error raised from a table nobody was thinking
    about at the time.

  * It makes the product unlawful. The UAE PDPL (Federal Decree-Law No. 45 of
    2021) grants a data subject the right to erasure, and this module profiles
    people automatically, which puts it squarely in scope. "We cannot delete
    your data, our audit table forbids it" is not a defence.

So the guard blocks UPDATE unconditionally and blocks DELETE *by default*,
while this module provides the deliberate, audited path through it. Erasure
becomes an explicit act by a named caller rather than something a stray
`DELETE` can do by accident.

THE MECHANISM. `set_config('flywheel.allow_purge', 'on', true)` — the third
argument is `is_local`, which scopes the setting to the CURRENT TRANSACTION.
That detail is load-bearing: a session-scoped setting on a pooled connection
would leak the permission to whatever ran next on that connection, silently
disarming the guard for unrelated code. Transaction scope means the permission
dies with the commit or rollback, every time.

EVERY PURGE IS LOGGED. An erasure that leaves no trace is indistinguishable
from a breach after the fact. The audit row records who, what, why and how many
rows — and is written to `audit_log`, which is NOT one of the purgeable tables.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Tables protected by the 077 append-only trigger. Purging any of them requires
#: the flag; everything else deletes normally.
GUARDED_TABLES = ("flywheel_readouts", "flywheel_preregistrations")

#: Recognised lawful bases. Free text would make the audit log unqueryable
#: exactly when someone needs to answer "show me every erasure last quarter".
ERASURE_REASONS = (
    "pdpl_data_subject_request",   # the individual asked
    "tenant_offboarding",          # the customer left
    "retention_policy_expiry",     # scheduled minimisation
    "erroneous_ingestion",         # we should never have held it
)


class ErasureRefused(Exception):
    """Raised when a purge is attempted without a recognised lawful basis."""


async def _enable_purge(db: AsyncSession) -> None:
    """Arm the guard for THIS TRANSACTION ONLY."""
    await db.execute(text("SELECT set_config('flywheel.allow_purge', 'on', true)"))


async def purge_customer(
    db: AsyncSession, *, tenant_id: int, customer_id: int,
    reason: str, actor_user_id: Optional[int] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Erase one customer's Flywheel footprint.

    Readouts are AGGREGATE — they contain arm sizes and rates, never an
    identifiable individual — so they are deliberately NOT deleted here. Erasing
    a customer must not silently destroy the measurement history of every
    campaign they happened to be enrolled in; that would let one erasure request
    delete a quarter's evidence for everyone else.

    What goes is the personal data and everything that points at it: the
    customer row and, by cascade, their events, consents, features, predictions,
    audience memberships, decisions and contact history.
    """
    if reason not in ERASURE_REASONS:
        raise ErasureRefused(
            f"'{reason}' is not a recognised lawful basis. Expected one of: "
            f"{', '.join(ERASURE_REASONS)}.")

    await _enable_purge(db)

    counts: Dict[str, int] = {}
    for table, column in (("flywheel_shadow_decisions", "customer_id"),
                          ("flywheel_allocation_lines", "customer_id")):
        result = await db.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :t AND {column} = :c"),
            {"t": tenant_id, "c": customer_id})
        counts[table] = result.rowcount or 0

    result = await db.execute(
        text("DELETE FROM flywheel_customers WHERE tenant_id = :t AND id = :c"),
        {"t": tenant_id, "c": customer_id})
    counts["flywheel_customers"] = result.rowcount or 0

    await _audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id,
                 action="flywheel.erasure.customer", reason=reason,
                 target=f"customer:{customer_id}", counts=counts, note=note)

    logger.warning("flywheel.erasure customer=%s tenant=%s reason=%s rows=%s",
                   customer_id, tenant_id, reason, counts)
    return {"customer_id": customer_id, "reason": reason, "deleted": counts,
            "readouts_retained": True,
            "note": ("Aggregate readouts are retained: they contain arm sizes and "
                     "rates, never an identifiable individual. Deleting them "
                     "would destroy other customers' measurement history too.")}


async def purge_campaign(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    reason: str, actor_user_id: Optional[int] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete a campaign and its measurement record.

    This DOES remove readouts and the pre-registration, because they are
    meaningless without the campaign. It is the operation the append-only
    trigger would otherwise block outright.
    """
    if reason not in ERASURE_REASONS:
        raise ErasureRefused(
            f"'{reason}' is not a recognised lawful basis. Expected one of: "
            f"{', '.join(ERASURE_REASONS)}.")

    await _enable_purge(db)

    counts: Dict[str, int] = {}
    for table in GUARDED_TABLES:
        result = await db.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :t AND campaign_id = :c"),
            {"t": tenant_id, "c": campaign_id})
        counts[table] = result.rowcount or 0

    result = await db.execute(
        text("DELETE FROM flywheel_campaigns WHERE tenant_id = :t AND id = :c"),
        {"t": tenant_id, "c": campaign_id})
    counts["flywheel_campaigns"] = result.rowcount or 0

    await _audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id,
                 action="flywheel.erasure.campaign", reason=reason,
                 target=f"campaign:{campaign_id}", counts=counts, note=note)

    logger.warning("flywheel.erasure campaign=%s tenant=%s reason=%s rows=%s",
                   campaign_id, tenant_id, reason, counts)
    return {"campaign_id": campaign_id, "reason": reason, "deleted": counts}


async def _audit(
    db: AsyncSession, *, tenant_id: int, actor_user_id: Optional[int],
    action: str, reason: str, target: str, counts: Dict[str, int],
    note: Optional[str],
) -> None:
    """Write the erasure to `audit_log`, which is not itself purgeable.

    `audit_log` predates Flywheel and carries no tenant_id column, so the tenant
    is recorded inside `new_values` rather than invented as a column here —
    altering a shared table would break the ownership boundary this module is
    required to respect (see tests/test_flywheel_migration.py).
    """
    try:
        await db.execute(
            text("""INSERT INTO audit_log
                       (user_id, action, resource_type, resource_id,
                        description, new_values, created_at)
                    VALUES (:u, :a, 'flywheel_erasure', :r, :desc,
                            CAST(:d AS JSONB), now())"""),
            {"u": actor_user_id, "a": action, "r": target,
             "desc": f"Lawful erasure ({reason}) of {target} in tenant {tenant_id}",
             "d": json.dumps({"tenant_id": tenant_id, "reason": reason,
                              "deleted": counts, "note": note})},
        )
    except Exception:
        # An erasure that cannot be logged must not proceed silently. Re-raise so
        # the whole transaction rolls back: no audit trail, no deletion.
        logger.exception("flywheel.erasure audit write FAILED — rolling back")
        raise
