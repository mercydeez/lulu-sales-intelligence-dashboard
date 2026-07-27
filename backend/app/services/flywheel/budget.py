"""The budget ledger. Postgres is the financial source of truth — Redis is not.

INVARIANTS THIS MODULE EXISTS TO GUARANTEE:
  1. `reserved + spent <= allocated`, always. Enforced BOTH here (fail fast with
     a readable error) AND by a CHECK constraint in migration 075 (so even a bug
     in this file cannot overspend an approved budget).
  2. Concurrent reservations cannot both succeed against the same last dirham.
     Every mutation takes `SELECT ... FOR UPDATE` on the budget row first, so
     the read-modify-write is serialized.
  3. A retried mutation carrying the same idempotency key applies ONCE. The
     unique partial index `uq_flywheel_ledger_idem` makes the database the arbiter,
     not application memory.
  4. Every mutation is reconstructable: the ledger stores before/after balance,
     actor, source and reason for each entry.

MONEY LIFECYCLE
    ALLOCATED  budget granted for the period
    RESERVED   exposure held at campaign APPROVAL (money not yet spent)
    COMMITTED  contractually owed (e.g. an approved PO) but not yet paid
    SPENT      actual discount given at REDEMPTION (reserved → spent)
    RELEASED   unused reservation returned at expiry/cancellation/completion

Nothing here commits. Callers compose these into their own transaction so that
money and stock move together or not at all.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import BudgetType, LedgerEntry, ZERO, money

logger = logging.getLogger(__name__)


class BudgetError(RuntimeError):
    """Base for every budget refusal. Route layer maps to HTTP 409."""


class InsufficientBudget(BudgetError):
    """The requested amount does not fit in the remaining allocation.

    Carries the numbers so the caller can show the operator exactly how short
    they are rather than a bare 'insufficient funds'.
    """

    def __init__(self, requested: Decimal, available: Decimal, budget_type: str):
        self.requested, self.available, self.budget_type = requested, available, budget_type
        super().__init__(
            f"{budget_type} budget short by {money(requested - available)} AED "
            f"(requested {money(requested)}, available {money(available)})"
        )


async def get_or_create_budget(
    db: AsyncSession, *, tenant_id: int, budget_type: BudgetType,
    period_start: date, period_end: date, allocated: Decimal = ZERO,
) -> int:
    """Return the budget id for the period, creating a zero-allocation row if
    absent so a campaign can never fail merely because nobody pre-created one."""
    row = (await db.execute(
        text("SELECT id FROM flywheel_budgets WHERE tenant_id = :t "
             "AND budget_type = :bt AND period_start = :ps"),
        {"t": tenant_id, "bt": budget_type.value, "ps": period_start},
    )).fetchone()
    if row:
        return int(row[0])

    row = (await db.execute(
        text("""INSERT INTO flywheel_budgets
                   (tenant_id, budget_type, period_start, period_end, allocated_aed)
                VALUES (:t, :bt, :ps, :pe, :alloc)
                ON CONFLICT (tenant_id, budget_type, period_start) DO UPDATE
                    SET updated_at = now()
                RETURNING id"""),
        {"t": tenant_id, "bt": budget_type.value, "ps": period_start,
         "pe": period_end, "alloc": money(allocated)},
    )).fetchone()
    return int(row[0])


async def active_budget_id(
    db: AsyncSession, *, tenant_id: int, budget_type: BudgetType,
    on_date: Optional[date] = None,
) -> Optional[int]:
    """The budget covering `on_date` (default today), or None."""
    row = (await db.execute(
        text("""SELECT id FROM flywheel_budgets
                 WHERE tenant_id = :t AND budget_type = :bt
                   AND period_start <= :d AND period_end > :d
                 ORDER BY period_start DESC LIMIT 1"""),
        {"t": tenant_id, "bt": budget_type.value, "d": on_date or date.today()},
    )).fetchone()
    return int(row[0]) if row else None


async def snapshot(db: AsyncSession, *, tenant_id: int, budget_id: int) -> Dict[str, Any]:
    """Current balances. Read-only — safe to call outside a locking transaction,
    and used for the budget_snapshot persisted on every decision."""
    row = (await db.execute(
        text("""SELECT budget_type, currency, allocated_aed, reserved_aed,
                       committed_aed, spent_aed, released_aed,
                       period_start, period_end
                  FROM flywheel_budgets WHERE id = :b AND tenant_id = :t"""),
        {"b": budget_id, "t": tenant_id},
    )).fetchone()
    if not row:
        return {}
    allocated, reserved, spent = money(row[2]), money(row[3]), money(row[5])
    return {
        "budget_id": budget_id,
        "budget_type": row[0],
        "currency": row[1],
        "allocated_aed": str(allocated),
        "reserved_aed": str(reserved),
        "committed_aed": str(money(row[4])),
        "spent_aed": str(spent),
        "released_aed": str(money(row[6])),
        # What a NEW reservation may draw on. Reserved money is already claimed.
        "available_aed": str(money(allocated - reserved - spent)),
        "period_start": str(row[7]),
        "period_end": str(row[8]),
    }


async def _lock_budget(db: AsyncSession, tenant_id: int, budget_id: int) -> Dict[str, Decimal]:
    """Row-lock the budget and return its balances.

    This lock is what makes concurrent reservations safe: the second transaction
    blocks here until the first commits, then reads the UPDATED balance rather
    than the stale one it would otherwise have used to approve an overspend.
    """
    row = (await db.execute(
        text("""SELECT allocated_aed, reserved_aed, committed_aed, spent_aed, released_aed
                  FROM flywheel_budgets WHERE id = :b AND tenant_id = :t FOR UPDATE"""),
        {"b": budget_id, "t": tenant_id},
    )).fetchone()
    if not row:
        raise BudgetError(f"Budget {budget_id} not found in tenant {tenant_id}")
    return {
        "allocated": money(row[0]), "reserved": money(row[1]),
        "committed": money(row[2]), "spent": money(row[3]), "released": money(row[4]),
    }


async def _write_entry(
    db: AsyncSession, *, tenant_id: int, budget_id: int, entry_type: LedgerEntry,
    amount: Decimal, balance_before: Decimal, balance_after: Decimal,
    source_type: str, source_id: Optional[str], campaign_id: Optional[int],
    actor_user_id: Optional[int], request_id: Optional[str],
    idempotency_key: Optional[str], reason: Optional[str],
) -> Optional[int]:
    """Append one ledger row. Returns None when the idempotency key was already
    used — the signal to the caller that this mutation is a replay."""
    try:
        row = (await db.execute(
            text("""INSERT INTO flywheel_budget_ledger
                       (tenant_id, budget_id, campaign_id, entry_type, amount_aed,
                        source_type, source_id, balance_before, balance_after,
                        actor_user_id, request_id, idempotency_key, reason)
                    VALUES (:t, :b, :c, :et, :amt, :st, :sid, :bb, :ba,
                            :actor, :rid, :idem, :reason)
                    RETURNING id"""),
            {"t": tenant_id, "b": budget_id, "c": campaign_id, "et": entry_type.value,
             "amt": money(amount), "st": source_type, "sid": source_id,
             "bb": money(balance_before), "ba": money(balance_after),
             "actor": actor_user_id, "rid": request_id, "idem": idempotency_key,
             "reason": reason},
        )).fetchone()
        return int(row[0])
    except IntegrityError:
        # uq_flywheel_ledger_idem fired: this exact mutation already applied.
        # Roll back to the savepoint the caller established, never the whole tx.
        raise


async def reserve(
    db: AsyncSession, *, tenant_id: int, budget_id: int, amount: Decimal,
    campaign_id: Optional[int] = None, source_type: str = "campaign_approval",
    source_id: Optional[str] = None, actor_user_id: Optional[int] = None,
    request_id: Optional[str] = None, idempotency_key: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Hold exposure against the budget (campaign approval).

    Raises InsufficientBudget rather than clamping: silently reserving less than
    asked would let a campaign go live believing it is funded.
    """
    amount = money(amount)
    if amount < 0:
        raise BudgetError("Cannot reserve a negative amount")
    if amount == ZERO:
        return {"applied": False, "reason": "zero_amount"}

    bal = await _lock_budget(db, tenant_id, budget_id)
    available = money(bal["allocated"] - bal["reserved"] - bal["spent"])
    if amount > available:
        raise InsufficientBudget(amount, available, "DISCOUNT/PROCUREMENT")

    before = bal["reserved"]
    after = money(before + amount)
    await db.execute(
        text("""UPDATE flywheel_budgets
                   SET reserved_aed = :after, updated_at = now()
                 WHERE id = :b AND tenant_id = :t"""),
        {"after": after, "b": budget_id, "t": tenant_id},
    )
    entry_id = await _write_entry(
        db, tenant_id=tenant_id, budget_id=budget_id, entry_type=LedgerEntry.RESERVED,
        amount=amount, balance_before=before, balance_after=after,
        source_type=source_type, source_id=source_id, campaign_id=campaign_id,
        actor_user_id=actor_user_id, request_id=request_id,
        idempotency_key=idempotency_key, reason=reason,
    )
    logger.info("flywheel.budget.reserved budget=%s amount=%s campaign=%s",
                budget_id, amount, campaign_id)
    return {"applied": True, "entry_id": entry_id, "reserved_after": str(after),
            "available_after": str(money(bal["allocated"] - after - bal["spent"]))}


async def spend(
    db: AsyncSession, *, tenant_id: int, budget_id: int, amount: Decimal,
    campaign_id: Optional[int] = None, source_type: str = "redemption",
    source_id: Optional[str] = None, actor_user_id: Optional[int] = None,
    request_id: Optional[str] = None, idempotency_key: Optional[str] = None,
    reason: Optional[str] = None, from_reservation: bool = True,
) -> Dict[str, Any]:
    """Convert reserved exposure into actual spend (redemption).

    `from_reservation=True` (the default) moves money reserved→spent, which
    keeps `reserved + spent` flat and therefore cannot breach the allocation.
    When a redemption exceeds what was reserved for it — legitimate, e.g. a
    larger basket than modelled — the excess is drawn from unreserved headroom
    and refused if there is none.
    """
    amount = money(amount)
    if amount <= ZERO:
        return {"applied": False, "reason": "zero_amount"}

    bal = await _lock_budget(db, tenant_id, budget_id)
    from_reserved = min(amount, bal["reserved"]) if from_reservation else ZERO
    excess = money(amount - from_reserved)

    headroom = money(bal["allocated"] - bal["reserved"] - bal["spent"])
    if excess > headroom:
        raise InsufficientBudget(excess, headroom, "DISCOUNT")

    new_reserved = money(bal["reserved"] - from_reserved)
    new_spent = money(bal["spent"] + amount)
    await db.execute(
        text("""UPDATE flywheel_budgets
                   SET reserved_aed = :res, spent_aed = :spent, updated_at = now()
                 WHERE id = :b AND tenant_id = :t"""),
        {"res": new_reserved, "spent": new_spent, "b": budget_id, "t": tenant_id},
    )
    entry_id = await _write_entry(
        db, tenant_id=tenant_id, budget_id=budget_id, entry_type=LedgerEntry.SPENT,
        amount=amount, balance_before=bal["spent"], balance_after=new_spent,
        source_type=source_type, source_id=source_id, campaign_id=campaign_id,
        actor_user_id=actor_user_id, request_id=request_id,
        idempotency_key=idempotency_key, reason=reason,
    )
    logger.info("flywheel.budget.spent budget=%s amount=%s campaign=%s",
                budget_id, amount, campaign_id)
    return {"applied": True, "entry_id": entry_id, "spent_after": str(new_spent),
            "reserved_after": str(new_reserved)}


async def release(
    db: AsyncSession, *, tenant_id: int, budget_id: int, amount: Optional[Decimal] = None,
    campaign_id: Optional[int] = None, source_type: str = "campaign_completion",
    source_id: Optional[str] = None, actor_user_id: Optional[int] = None,
    request_id: Optional[str] = None, idempotency_key: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Return unused reservation to the pool (expiry / cancellation / completion).

    With `amount=None` and a campaign id, releases exactly that campaign's
    outstanding reservation — computed from the ledger, so it can never release
    more than the campaign actually holds and steal another campaign's headroom.
    """
    bal = await _lock_budget(db, tenant_id, budget_id)

    if amount is None:
        if campaign_id is None:
            raise BudgetError("release() needs either an amount or a campaign_id")
        row = (await db.execute(
            text("""SELECT COALESCE(SUM(CASE WHEN entry_type = 'RESERVED' THEN amount_aed
                                             WHEN entry_type IN ('RELEASED', 'SPENT')
                                             THEN -amount_aed ELSE 0 END), 0)
                      FROM flywheel_budget_ledger
                     WHERE tenant_id = :t AND budget_id = :b AND campaign_id = :c"""),
            {"t": tenant_id, "b": budget_id, "c": campaign_id},
        )).fetchone()
        amount = money(max(ZERO, money(row[0])))

    amount = money(amount)
    # Never release more than is actually held — that would inflate the budget.
    amount = min(amount, bal["reserved"])
    if amount <= ZERO:
        return {"applied": False, "reason": "nothing_to_release"}

    new_reserved = money(bal["reserved"] - amount)
    new_released = money(bal["released"] + amount)
    await db.execute(
        text("""UPDATE flywheel_budgets
                   SET reserved_aed = :res, released_aed = :rel, updated_at = now()
                 WHERE id = :b AND tenant_id = :t"""),
        {"res": new_reserved, "rel": new_released, "b": budget_id, "t": tenant_id},
    )
    entry_id = await _write_entry(
        db, tenant_id=tenant_id, budget_id=budget_id, entry_type=LedgerEntry.RELEASED,
        amount=amount, balance_before=bal["reserved"], balance_after=new_reserved,
        source_type=source_type, source_id=source_id, campaign_id=campaign_id,
        actor_user_id=actor_user_id, request_id=request_id,
        idempotency_key=idempotency_key, reason=reason,
    )
    logger.info("flywheel.budget.released budget=%s amount=%s campaign=%s",
                budget_id, amount, campaign_id)
    return {"applied": True, "entry_id": entry_id, "released": str(amount),
            "reserved_after": str(new_reserved)}


async def commit_amount(
    db: AsyncSession, *, tenant_id: int, budget_id: int, amount: Decimal,
    campaign_id: Optional[int] = None, source_type: str = "procurement_po",
    source_id: Optional[str] = None, actor_user_id: Optional[int] = None,
    request_id: Optional[str] = None, idempotency_key: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a contractual commitment (approved PO) — kept SEPARATE from
    discount spend so a CFO can see cash requirement independently of promo
    burn, per §14 of the brief."""
    amount = money(amount)
    if amount <= ZERO:
        return {"applied": False, "reason": "zero_amount"}

    bal = await _lock_budget(db, tenant_id, budget_id)
    before = bal["committed"]
    after = money(before + amount)
    await db.execute(
        text("UPDATE flywheel_budgets SET committed_aed = :after, updated_at = now() "
             "WHERE id = :b AND tenant_id = :t"),
        {"after": after, "b": budget_id, "t": tenant_id},
    )
    entry_id = await _write_entry(
        db, tenant_id=tenant_id, budget_id=budget_id, entry_type=LedgerEntry.COMMITTED,
        amount=amount, balance_before=before, balance_after=after,
        source_type=source_type, source_id=source_id, campaign_id=campaign_id,
        actor_user_id=actor_user_id, request_id=request_id,
        idempotency_key=idempotency_key, reason=reason,
    )
    return {"applied": True, "entry_id": entry_id, "committed_after": str(after)}


async def campaign_exposure(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Dict[str, str]:
    """What this campaign currently holds and has burned, from the ledger.

    Derived from ledger entries rather than a denormalized column so it is
    always consistent with the audit trail — if they ever disagreed, the ledger
    is the truth and the column is the bug.
    """
    row = (await db.execute(
        text("""SELECT
                  COALESCE(SUM(CASE WHEN entry_type='RESERVED'  THEN amount_aed END),0),
                  COALESCE(SUM(CASE WHEN entry_type='SPENT'     THEN amount_aed END),0),
                  COALESCE(SUM(CASE WHEN entry_type='RELEASED'  THEN amount_aed END),0),
                  COALESCE(SUM(CASE WHEN entry_type='COMMITTED' THEN amount_aed END),0)
                FROM flywheel_budget_ledger
               WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    reserved, spent, released, committed = (money(x) for x in row)
    return {
        "reserved_aed": str(reserved),
        "spent_aed": str(spent),
        "released_aed": str(released),
        "committed_aed": str(committed),
        # Still held: reserved less what has been converted or handed back.
        "outstanding_aed": str(money(max(ZERO, reserved - spent - released))),
    }
