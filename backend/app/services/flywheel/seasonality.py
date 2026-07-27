"""Seasonality — the calendar the engine was deciding without.

WHY IT MATTERS HERE SPECIFICALLY. In the GCC grocery market, Ramadan roughly
doubles grocery demand; Eid, back-to-school and the summer travel lull each
reshape it. A retention offer made the week before Ramadan is worth MORE than the
identical offer in a flat week, because the customer's forward value over the
retention horizon is genuinely higher. An engine that treats every week as an
average week systematically under-invests before a peak and over-invests into a
lull.

HOW IT ENTERS THE DECISION. `factor_for(date, category)` returns the demand
multiplier in force. `decisioning.evaluate` scales the customer's monthly value by
it BEFORE building candidates, so every EIV term downstream already reflects the
season. Nothing in the optimizer changes — the seasonality lives in the value it
is handed, which keeps the optimizer's determinism and its "no model" guarantee
intact.

WHY IT IS DETERMINISTIC POLICY, NOT A MODEL. The multipliers are configuration —
a calendar an operator maintains, seeded with the UAE observances (migration 080).
This is not a forecast; it is a stated, auditable policy that this week is worth
1.85x. The governing rule holds: models propose, deterministic services dispose,
and this is a deterministic service.

BOUNDED BY THE DATABASE. The multiplier is CHECK-constrained to (0, 5], so a
fat-fingered 20x cannot make the optimizer hand out the store.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NEUTRAL = Decimal("1.000")


async def factor_for(
    db: AsyncSession, *, tenant_id: int, on: Optional[date] = None,
    category: Optional[str] = None,
) -> Decimal:
    """The demand multiplier in force on a date, for a category if given.

    A category-specific factor wins over a general one (a Ramadan dates-and-nuts
    surge need not apply to cleaning products). When several windows overlap, the
    STRONGEST multiplier wins — a peak inside a broader season is the binding
    signal. Returns 1.0 (neutral) when nothing applies, so the caller never has to
    special-case "no season".
    """
    on = on or date.today()
    rows = (await db.execute(
        text("""SELECT demand_multiplier, category FROM flywheel_seasonality_calendar
                 WHERE tenant_id = :t AND :d BETWEEN starts_on AND ends_on
                   AND (category IS NULL OR category = :cat)"""),
        {"t": tenant_id, "d": on, "cat": category},
    )).fetchall()
    if not rows:
        return NEUTRAL

    # A category-specific match, if present, is the intended one; else fall back
    # to the general windows. Within the chosen set, the strongest multiplier —
    # measured by distance from 1.0 — is the binding season.
    specific = [r for r in rows if r[1] is not None]
    chosen = specific if specific else rows
    return max((Decimal(str(r[0])) for r in chosen),
               key=lambda m: abs(m - NEUTRAL))


async def active_seasons(
    db: AsyncSession, *, tenant_id: int, on: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Every season in force on a date — for showing WHY a value was adjusted."""
    on = on or date.today()
    rows = (await db.execute(
        text("""SELECT name, kind, demand_multiplier, category, note, starts_on, ends_on
                  FROM flywheel_seasonality_calendar
                 WHERE tenant_id = :t AND :d BETWEEN starts_on AND ends_on
                 ORDER BY demand_multiplier DESC"""),
        {"t": tenant_id, "d": on},
    )).fetchall()
    return [{
        "name": r[0], "kind": r[1], "demand_multiplier": str(Decimal(str(r[2]))),
        "category": r[3], "note": r[4],
        "starts_on": str(r[5]), "ends_on": str(r[6]),
    } for r in rows]


async def calendar(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """The whole seasonality calendar, with the currently-active windows flagged."""
    today = date.today()
    rows = (await db.execute(
        text("""SELECT id, name, kind, starts_on, ends_on, demand_multiplier,
                       category, note
                  FROM flywheel_seasonality_calendar
                 WHERE tenant_id = :t
                 ORDER BY starts_on"""),
        {"t": tenant_id},
    )).fetchall()
    entries = [{
        "id": int(r[0]), "name": r[1], "kind": r[2],
        "starts_on": str(r[3]), "ends_on": str(r[4]),
        "demand_multiplier": str(Decimal(str(r[5]))),
        "category": r[6], "note": r[7],
        "active": r[3] <= today <= r[4],
    } for r in rows]
    return {
        "calendar": entries,
        "active_now": [e for e in entries if e["active"]],
        "current_factor": str(await factor_for(db, tenant_id=tenant_id, on=today)),
        "note": ("The demand multiplier scales a customer's forward value in the "
                 "EIV calculation, so a retention offer is valued for the season "
                 "it is made in, not an average week."),
    }
