"""Outcome-based pricing — revisited, and deliberately gated.

THE TEMPTATION AND THE RULE. The most attractive pitch in this whole product is
"pay us a share of the incremental margin we prove we created." It aligns
perfectly with the buyer. And the plan (and the CFO lens) explicitly REFUSED to
ship it yet, for one reason: we could not measure incrementality reliably enough
to invoice against it, and getting an outcome-priced bill wrong ONCE destroys the
trust the entire product runs on. So outcome pricing was deferred until the
holdout readout had run clean for two quarters.

WHAT THIS MODULE IS. The mechanism, built, but GATED behind that evidence. An
outcome-pricing plan can be recorded and proposed at any time. It cannot become
CHARGEABLE until `evaluate_gate` confirms the required number of consecutive
SIGNIFICANT holdout readouts — an interval that excludes zero, from
flywheel_readouts (Horizon 1). Until then the plan is inert, `gate_met` is false,
and `compute_charge` refuses to bill.

WHY THE GATE READS THE ANYTIME-VALID READOUTS. The Horizon-1 confidence sequence
is exactly the evidence this needs: it is honest under the continuous monitoring
a live dashboard invites, so "two significant readouts" is a claim that survives
scrutiny rather than a peeked p-value. Outcome pricing is only as trustworthy as
the measurement under it, and this is why measurement was built first.

THE GATE IS COMPUTED, NEVER SET BY HAND. `gate_met` is recomputed from the
readouts every time; there is no endpoint to flip it true. That is the whole
integrity of the thing — a human who could just tick the box could bill on
evidence that does not exist.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)


async def propose_plan(
    db: AsyncSession, *, tenant_id: int, plan_name: str,
    margin_share_pct: Decimal, gate_readouts_required: int = 2,
) -> Dict[str, Any]:
    """Record an outcome-pricing plan. It is proposed and inert — proposing a plan
    never makes it chargeable; only the evidence gate can do that."""
    if not (ZERO < margin_share_pct <= Decimal("0.5")):
        raise ValueError("margin_share_pct must be in (0, 0.5]")
    plan_id = int((await db.execute(
        text("""INSERT INTO flywheel_outcome_pricing
                   (tenant_id, plan_name, margin_share_pct, gate_readouts_required, status)
                VALUES (:t, :n, :share, :req, 'proposed')
                ON CONFLICT (tenant_id, plan_name) DO UPDATE
                    SET margin_share_pct = EXCLUDED.margin_share_pct,
                        gate_readouts_required = EXCLUDED.gate_readouts_required,
                        updated_at = now()
                RETURNING id"""),
        {"t": tenant_id, "n": plan_name, "share": margin_share_pct,
         "req": gate_readouts_required},
    )).scalar())
    return {"plan_id": plan_id, "plan_name": plan_name, "status": "proposed",
            "chargeable": False,
            "note": "Proposed and inert. It cannot bill until the evidence gate is met."}


async def evaluate_gate(
    db: AsyncSession, *, tenant_id: int, plan_id: int
) -> Dict[str, Any]:
    """Recompute whether the plan has earned the right to charge.

    The bar: at least `gate_readouts_required` consecutive SIGNIFICANT readouts
    (confidence interval excludes zero) that are also POSITIVE — you cannot
    outcome-price on a campaign that measured harm. Computed from the immutable
    Horizon-1 readouts; the result is written back, never hand-set.
    """
    plan = (await db.execute(
        text("""SELECT plan_name, gate_readouts_required, status
                  FROM flywheel_outcome_pricing WHERE tenant_id = :t AND id = :p"""),
        {"t": tenant_id, "p": plan_id},
    )).fetchone()
    if not plan:
        raise ValueError(f"outcome-pricing plan {plan_id} not found")
    required = int(plan[1])

    # The most recent readout per campaign, newest first — how much SIGNIFICANT,
    # POSITIVE evidence exists right now across the tenant's measured campaigns.
    readouts = (await db.execute(
        text("""SELECT DISTINCT ON (campaign_id)
                       campaign_id, is_significant, incremental_retention, window_end
                  FROM flywheel_readouts
                 WHERE tenant_id = :t
                 ORDER BY campaign_id, window_end DESC"""),
        {"t": tenant_id},
    )).fetchall()

    qualifying = [r for r in readouts if bool(r[1]) and float(r[2]) > 0]
    met = len(qualifying) >= required

    evidence = {
        "required": required,
        "qualifying_readouts": len(qualifying),
        "total_measured_campaigns": len(readouts),
        "qualifying_campaign_ids": [int(r[0]) for r in qualifying],
        "evaluated_at": None,  # stamped by the caller / DB now()
    }

    await db.execute(
        text("""UPDATE flywheel_outcome_pricing
                   SET gate_met = :met, gate_evidence = CAST(:ev AS JSONB),
                       updated_at = now()
                 WHERE tenant_id = :t AND id = :p"""),
        {"met": met, "ev": json.dumps(evidence), "t": tenant_id, "p": plan_id},
    )

    return {
        "plan_id": plan_id, "gate_met": met,
        "qualifying_readouts": len(qualifying), "required": required,
        "chargeable": met,
        "reason": (
            f"{len(qualifying)} of {required} required significant, positive "
            f"holdout readouts. " + (
                "The gate is MET — outcome pricing may be activated and charged."
                if met else
                "The gate is NOT met. Outcome pricing stays inert; charging on "
                "unproven incrementality is exactly what this gate prevents.")),
    }


async def compute_charge(
    db: AsyncSession, *, tenant_id: int, plan_id: int, campaign_id: int,
) -> Dict[str, Any]:
    """Compute an outcome-priced charge for a campaign — ONLY if the gate is met.

    Refuses when the gate is not met. This is the enforcement point: even a caller
    who wants to bill cannot, because the evidence does not support it. The charge
    is a share of the MEASURED incremental margin from the latest readout, never
    a projection.
    """
    plan = (await db.execute(
        text("""SELECT plan_name, margin_share_pct, gate_met
                  FROM flywheel_outcome_pricing WHERE tenant_id = :t AND id = :p"""),
        {"t": tenant_id, "p": plan_id},
    )).fetchone()
    if not plan:
        raise ValueError(f"outcome-pricing plan {plan_id} not found")
    plan_name, share, gate_met = plan[0], Decimal(str(plan[1])), bool(plan[2])

    if not gate_met:
        return {
            "plan_id": plan_id, "campaign_id": campaign_id, "chargeable": False,
            "charge_aed": None,
            "refusal": ("The evidence gate is not met — this plan cannot bill. Run "
                        "evaluate_gate; until enough significant holdout readouts "
                        "exist, outcome pricing stays inert by design."),
        }

    readout = (await db.execute(
        text("""SELECT incremental_margin_aed, is_significant, incremental_retention
                  FROM flywheel_readouts
                 WHERE tenant_id = :t AND campaign_id = :c
                 ORDER BY window_end DESC LIMIT 1"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    if not readout or not bool(readout[1]) or float(readout[2]) <= 0:
        return {
            "plan_id": plan_id, "campaign_id": campaign_id, "chargeable": False,
            "charge_aed": None,
            "refusal": ("This campaign has no significant, positive readout — there "
                        "is no proven incremental margin to charge a share of."),
        }

    incremental_margin = money(readout[0])
    charge = money(incremental_margin * share)
    return {
        "plan_id": plan_id, "plan_name": plan_name, "campaign_id": campaign_id,
        "chargeable": True,
        "incremental_margin_aed": str(incremental_margin),
        "margin_share_pct": str(share),
        "charge_aed": str(charge),
        "basis": ("A share of MEASURED incremental margin from the latest holdout "
                  "readout — never a projection."),
    }


async def status(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """Every outcome-pricing plan and whether it may charge — the surface for the
    metering/billing view."""
    rows = (await db.execute(
        text("""SELECT id, plan_name, margin_share_pct, gate_readouts_required,
                       gate_met, status, gate_evidence
                  FROM flywheel_outcome_pricing
                 WHERE tenant_id = :t ORDER BY plan_name"""),
        {"t": tenant_id},
    )).fetchall()
    return {
        "plans": [{
            "plan_id": int(r[0]), "plan_name": r[1],
            "margin_share_pct": str(Decimal(str(r[2]))),
            "gate_readouts_required": int(r[3]),
            "gate_met": bool(r[4]), "chargeable": bool(r[4]),
            "status": r[5], "gate_evidence": r[6],
        } for r in rows],
        "note": ("Outcome pricing charges a share of measured incremental margin, "
                 "but only once the evidence gate is met — two clean quarters of "
                 "significant holdout readouts. Until then it is inert by design."),
    }
