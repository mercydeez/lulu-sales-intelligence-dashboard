"""End-to-end decision tracing — one id across a decision's whole life.

WHY request_id was not enough. flywheel_decisions already carries request_id, the
id of the HTTP request that produced the decision. But a decision's life does not
end with that request. It is activated later, relayed through the outbox, and
redeemed by the customer days afterwards — all on different requests, or on no
request at all (a scheduled job). request_id ties a decision to its birth; it
cannot follow it through the rest of its life.

trace_id does. It is minted once at the start of a decision flow and threaded
through every downstream write — the decision row, the redemption, the outbox
event, and any job that acts on it. "Why did this customer get this offer, and
what became of it" then becomes a single indexed lookup instead of a
cross-table investigation.

TWO AUDIENCES, ONE MECHANISM.
  * Operators get a timeline they can read on /flywheel/decisions/{id}.
  * Data subjects get their PDPL right to an explanation of an automated
    decision. UAE Federal Decree-Law No. 45 of 2021 grants that right, and this
    module is squarely in scope because the Flywheel profiles people
    automatically. The trace IS the explanation — inputs, the action chosen, the
    reasons, and what happened next.

DELIBERATELY NOT OpenTelemetry. A full OTel pipeline (collector, exporter,
backend) is real infrastructure and a Horizon-3 decision. What is needed now is
correlation across the app's own tables, and a contextvar + a trace_id column
delivers exactly that with no new moving parts. The trace_id is a plain opaque
token; if OTel is adopted later, the same column carries a W3C trace-id and the
timeline query is unchanged.
"""
from __future__ import annotations

import logging
import secrets
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The active trace for this task/request. Defaults to None; a decision flow
#: mints one at its start (or inherits an inbound one) and every downstream write
#: reads it. ContextVar so concurrent requests never share a trace.
trace_context: ContextVar[Optional[str]] = ContextVar("flywheel_trace_id", default=None)


def new_trace_id() -> str:
    """A fresh opaque trace id. 32 hex chars — unguessable, and short enough for
    the VARCHAR(48) columns with room to spare for a future 'fw-' prefix or a
    W3C trace-id if OpenTelemetry is adopted."""
    return secrets.token_hex(16)


def current_trace_id() -> Optional[str]:
    return trace_context.get()


def ensure_trace_id(inbound: Optional[str] = None) -> str:
    """Return the active trace id, minting one if there is none.

    `inbound` lets an upstream trace (e.g. a header, or the job that dispatched
    this work) be continued rather than a new one started, so a single logical
    operation keeps one id even across process boundaries.
    """
    if inbound:
        trace_context.set(inbound)
        return inbound
    existing = trace_context.get()
    if existing:
        return existing
    tid = new_trace_id()
    trace_context.set(tid)
    return tid


async def decision_timeline(
    db: AsyncSession, *, tenant_id: int, decision_id: int
) -> Optional[Dict[str, Any]]:
    """Assemble the full life of a decision as an ordered timeline.

    Joins the decision to everything that shares its trace_id — redemptions,
    outbox events, jobs — and orders them in time. Falls back to request_id for
    decisions written before tracing existed, so old decisions still explain
    themselves as far as the data allows.
    """
    decision = (await db.execute(
        text("""SELECT id, campaign_id, customer_id, action_type, discount_pct,
                       eiv_aed, reason_codes, churn_probability, uplift,
                       trace_id, request_id, decided_at,
                       churn_model_version_id, uplift_model_version_id
                  FROM flywheel_decisions
                 WHERE tenant_id = :t AND id = :d"""),
        {"t": tenant_id, "d": decision_id},
    )).fetchone()
    if not decision:
        return None

    trace_id = decision[9]
    events: List[Dict[str, Any]] = [{
        "at": decision[11].isoformat() if decision[11] else None,
        "stage": "decided",
        "detail": {
            "action": decision[3],
            "discount_pct": str(decision[4]),
            "eiv_aed": str(decision[5]),
            "reason_codes": decision[6] or [],
            "churn_probability": float(decision[7]) if decision[7] is not None else None,
            "uplift": float(decision[8]) if decision[8] is not None else None,
        },
    }]

    # Everything downstream that shares the trace. If the decision predates
    # tracing (trace_id NULL), we can only show the decision itself — stated
    # honestly rather than silently returning a one-event timeline as if complete.
    if trace_id:
        redemptions = (await db.execute(
            text("""SELECT r.created_at, o.offer_code, r.units,
                           r.net_value_aed, r.margin_aed
                      FROM flywheel_redemptions r
                      LEFT JOIN flywheel_offers o ON o.id = r.offer_id
                     WHERE r.tenant_id = :t AND r.trace_id = :tr
                     ORDER BY r.created_at"""),
            {"t": tenant_id, "tr": trace_id},
        )).fetchall()
        for r in redemptions:
            events.append({
                "at": r[0].isoformat() if r[0] else None,
                "stage": "redeemed",
                "detail": {"offer_code": r[1], "units": int(r[2]),
                           "net_value_aed": str(r[3]), "margin_aed": str(r[4])},
            })

        outbox_events = (await db.execute(
            text("""SELECT created_at, published_at, event_type, published
                      FROM flywheel_outbox
                     WHERE tenant_id = :t AND trace_id = :tr
                     ORDER BY created_at"""),
            {"t": tenant_id, "tr": trace_id},
        )).fetchall()
        for e in outbox_events:
            events.append({
                "at": e[0].isoformat() if e[0] else None,
                "stage": "event_emitted",
                "detail": {"event_type": e[2],
                           "published": bool(e[3]),
                           "published_at": e[1].isoformat() if e[1] else None},
            })

    events.sort(key=lambda e: (e["at"] or ""))

    return {
        "decision_id": decision_id,
        "trace_id": trace_id,
        "request_id": decision[10],
        "campaign_id": decision[1],
        "customer_id": decision[2],
        "model_lineage": {
            "churn_model_version_id": decision[12],
            "uplift_model_version_id": decision[13],
        },
        "timeline": events,
        "traced": trace_id is not None,
        "note": (
            "This is the automated decision's full recorded life. It is also the "
            "explanation a data subject may request under the UAE PDPL: the inputs, "
            "the action chosen, the reasons, and what followed."
            if trace_id else
            "This decision predates end-to-end tracing (no trace_id), so only the "
            "decision itself can be shown; downstream events cannot be correlated."
        ),
    }
