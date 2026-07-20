"""PDPL — the right to object to automated profiling.

THE LEGAL FACT. UAE Federal Decree-Law No. 45 of 2021 (PDPL) grants a data
subject the right to object to the automated processing of their personal data,
including profiling. The Flywheel profiles automatically — that is its whole
function — so this right is squarely in scope. An objection is not a preference
to be weighed against commercial value; it is a legal instruction that excludes
the customer from automated decisions entirely.

HOW IT IS HONOURED. `decisioning.evaluate` checks `is_objected` before it scores
anyone. An objecting customer returns NO_ACTION with a PROFILING_OBJECTION reason
— no score is computed, no offer is issued, and the reason is recorded so an
audit can see the objection was respected rather than ignored.

WHY A SEPARATE TABLE FROM CONSENT. Consent (flywheel_customer_consents) is about
CONTACT — may we email you. An objection is about PROCESSING — may we make
automated decisions about you at all. A customer may consent to email and still
object to profiling, or vice versa; conflating them would silently violate one
while honouring the other.

WITHDRAWABLE. A data subject may withdraw an objection later. That is a lifecycle
on the same row (active -> withdrawn), timestamped both ways, so the record shows
exactly when profiling was and was not permitted.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def is_objected(db: AsyncSession, *, tenant_id: int, customer_id: int) -> bool:
    """Does this customer have an ACTIVE objection to automated profiling?

    Called by decisioning before any scoring. Kept deliberately cheap (a single
    indexed lookup on the partial index) because it runs on the hot path of every
    decision.
    """
    row = (await db.execute(
        text("""SELECT 1 FROM flywheel_profiling_objections
                 WHERE tenant_id = :t AND customer_id = :c AND status = 'active'"""),
        {"t": tenant_id, "c": customer_id},
    )).fetchone()
    return row is not None


async def record_objection(
    db: AsyncSession, *, tenant_id: int, customer_id: int,
    basis: str = "pdpl_art_automated_processing", note: Optional[str] = None,
) -> Dict[str, Any]:
    """Record (or re-activate) a customer's objection to automated profiling.

    Idempotent: objecting twice re-activates the single row rather than creating a
    second. The upsert also un-withdraws a previously-withdrawn objection.
    """
    await db.execute(
        text("""INSERT INTO flywheel_profiling_objections
                   (tenant_id, customer_id, basis, status, note, objected_at)
                VALUES (:t, :c, :b, 'active', :n, now())
                ON CONFLICT (tenant_id, customer_id) DO UPDATE SET
                    status = 'active', basis = EXCLUDED.basis, note = EXCLUDED.note,
                    objected_at = now(), withdrawn_at = NULL"""),
        {"t": tenant_id, "c": customer_id, "b": basis, "n": note},
    )
    logger.info("flywheel.objection recorded customer=%s tenant=%s", customer_id, tenant_id)
    return {"customer_id": customer_id, "status": "active", "basis": basis,
            "effect": ("This customer is now excluded from all automated Flywheel "
                       "decisions until the objection is withdrawn.")}


async def withdraw_objection(
    db: AsyncSession, *, tenant_id: int, customer_id: int
) -> Dict[str, Any]:
    result = await db.execute(
        text("""UPDATE flywheel_profiling_objections
                   SET status = 'withdrawn', withdrawn_at = now()
                 WHERE tenant_id = :t AND customer_id = :c AND status = 'active'"""),
        {"t": tenant_id, "c": customer_id},
    )
    withdrawn = (result.rowcount or 0) > 0
    return {"customer_id": customer_id,
            "status": "withdrawn" if withdrawn else "no_active_objection",
            "withdrawn": withdrawn}


async def list_objections(
    db: AsyncSession, *, tenant_id: int, active_only: bool = True
) -> Dict[str, Any]:
    clause = "AND status = 'active'" if active_only else ""
    rows = (await db.execute(
        text(f"""SELECT customer_id, basis, status, note, objected_at, withdrawn_at
                   FROM flywheel_profiling_objections
                  WHERE tenant_id = :t {clause}
                  ORDER BY objected_at DESC"""),
        {"t": tenant_id},
    )).fetchall()
    return {
        "objections": [{
            "customer_id": int(r[0]), "basis": r[1], "status": r[2], "note": r[3],
            "objected_at": r[4].isoformat() if r[4] else None,
            "withdrawn_at": r[5].isoformat() if r[5] else None,
        } for r in rows],
        "active_count": sum(1 for r in rows if r[2] == "active"),
        "legal_basis": ("UAE PDPL (Federal Decree-Law No. 45 of 2021) — the right "
                        "to object to automated processing, including profiling. "
                        "Active objections exclude the customer from all automated "
                        "Flywheel decisions."),
    }
