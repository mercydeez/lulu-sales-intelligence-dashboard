"""Flywheel metering — charge for the thing that is worth charging for.

WHY THIS EXISTS. The CFO lens was blunt: until a decision or a scoring pass emits
a billable event, the Flywheel is a cost centre. `services/billing.py` had
invoices and plans and zero Flywheel hooks, so the one differentiated capability
in the product could not be charged for.

THE PRICING SHAPE (owner default, 20 Jul 2026). Hybrid, not pure outcome. A
platform fee the buyer can predict, PLUS a metered decisioning layer keyed to a
metric the buyer already tracks and we can count exactly — decisions served and
customers scored. Pure outcome pricing ("pay a share of incremental margin") is
deferred until the holdout readout has run clean for two quarters, because we
cannot yet measure reliably enough to invoice against it, and getting that wrong
once destroys the trust the whole product runs on.

METERING IS NOT INVOICING. Recording a metered event moves no money and is
best-effort — a metering failure must never fail a customer's decision (that is
why `record` swallows). Money moves only through billing.create_invoice, from
these counts, deliberately.

USAGE IS VISIBLE BEFORE IT IS BILLED. `summary()` shows the tenant exactly what
they have accrued this period and what it would cost, so an invoice is never a
surprise. A metered bill the customer could not see coming is how metered pricing
loses the trust that made it worth adopting.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: The metered dimensions. These are the usage_events.event_type strings the
#: Flywheel emits; usage_metering already stores and counts them per period.
EVENT_DECISION = "flywheel_decision"
EVENT_CUSTOMER_SCORED = "flywheel_customer_scored"

#: Draft hybrid pricing. Platform fee is monthly; the metered rates are per event
#: over the platform's included allowance. Anchored in the GCC gap the market
#: research found — below Braze's ~50k entry, above Klaviyo's mid-market band —
#: but DRAFT: confirm before any real invoice (same discipline as billing.py).
HYBRID_PRICING = {
    "platform_fee_aed_month": Decimal("12000.00"),
    "included_decisions": 50_000,
    "per_decision_aed": Decimal("0.08"),
    "included_scored_customers": 100_000,
    "per_scored_customer_aed": Decimal("0.02"),
    "currency": "AED",
    "note": ("DRAFT hybrid pricing — a predictable platform fee plus a metered "
             "decisioning layer. Outcome-based pricing (a share of incremental "
             "margin) is deferred until the holdout readout has run clean for two "
             "quarters. Confirm before invoicing."),
}


async def record(tenant_id: int, event_type: str, quantity: int = 1,
                 metadata: Optional[Dict[str, Any]] = None) -> None:
    """Record a metered Flywheel event. Best-effort; never raises.

    Delegates to the platform's usage_metering so Flywheel usage sits in the same
    ledger as every other metered dimension and the same invoicing path can read
    it. A metering failure is swallowed — it must never break a decision.
    """
    try:
        from app.services import usage_metering
        await usage_metering.record_usage(tenant_id, event_type, quantity, metadata)
    except Exception:
        logger.debug("flywheel.metering record failed (swallowed)", exc_info=True)


async def summary(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """This period's metered Flywheel usage and what it would cost.

    Read-only and shown to the tenant BEFORE any invoice, so metered charges are
    never a surprise.
    """
    from app.services.usage_metering import current_period

    period = current_period()
    counts = {r[0]: int(r[1]) for r in (await db.execute(
        text("""SELECT event_type, COALESCE(SUM(quantity), 0)
                  FROM usage_events
                 WHERE tenant_id = :t
                   AND event_type IN (:d, :s)
                   AND created_at >= :start AND created_at < :end
                 GROUP BY event_type"""),
        {"t": tenant_id, "d": EVENT_DECISION, "s": EVENT_CUSTOMER_SCORED,
         "start": period["start"], "end": period["end"]},
    )).fetchall()}

    decisions = counts.get(EVENT_DECISION, 0)
    scored = counts.get(EVENT_CUSTOMER_SCORED, 0)

    billable_decisions = max(0, decisions - HYBRID_PRICING["included_decisions"])
    billable_scored = max(0, scored - HYBRID_PRICING["included_scored_customers"])

    decision_charge = money(Decimal(billable_decisions) * HYBRID_PRICING["per_decision_aed"])
    scored_charge = money(Decimal(billable_scored) * HYBRID_PRICING["per_scored_customer_aed"])
    platform_fee = money(HYBRID_PRICING["platform_fee_aed_month"])
    total = money(platform_fee + decision_charge + scored_charge)

    return {
        "period": {"from": str(period["start"].date()), "to": str(period["end"].date())},
        "usage": {
            "decisions_served": decisions,
            "customers_scored": scored,
        },
        "included": {
            "decisions": HYBRID_PRICING["included_decisions"],
            "customers_scored": HYBRID_PRICING["included_scored_customers"],
        },
        "billable": {
            "decisions": billable_decisions,
            "customers_scored": billable_scored,
        },
        "charges_aed": {
            "platform_fee": str(platform_fee),
            "metered_decisions": str(decision_charge),
            "metered_scoring": str(scored_charge),
            "total": str(total),
        },
        "pricing": {k: (str(v) if isinstance(v, Decimal) else v)
                    for k, v in HYBRID_PRICING.items()},
        "note": ("This is accrued usage for the current period, shown before any "
                 "invoice is raised. Nothing here has been charged."),
    }
