"""Stage 6 — measurement. Treatment vs control, and the loop closes.

WHY CONTROL GROUPS ARE NOT OPTIONAL. Without one, a campaign's "results" are:

    "We contacted 4,000 at-risk customers and 2,800 came back — 70% retention!"

That number is meaningless. Some of those 2,800 were coming back anyway; the
discount just cost margin on a sale that would have happened. The only honest
question is: how many MORE came back than would have without the offer?

    incremental_retention = treatment_rate − control_rate

That single subtraction is the difference between a retention programme that
pays for itself and one that quietly destroys margin while reporting success.

WHAT THIS MODULE REFUSES TO DO: report a treatment rate on its own as if it were
uplift. Every returned figure is labelled, and `campaign_roi` is computed from
INCREMENTAL margin, never gross.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import budget as budget_service, campaign_state, outbox
from app.services.flywheel.types import ZERO, CampaignStatus, money

logger = logging.getLogger(__name__)

#: A customer is "retained" if they purchased within this window after the
#: campaign started. Must match the churn label's outcome window, or the
#: measurement answers a different question than the model was trained on.
RETENTION_WINDOW_DAYS = 60


async def measure(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    persist: bool = True,
) -> Dict[str, Any]:
    """Compute treatment-vs-control outcomes for a campaign.

    Both arms are measured over the SAME window with the SAME definition of
    retention — otherwise the comparison is invalid before the arithmetic starts.
    """
    campaign = (await db.execute(
        text("""SELECT status, starts_on, ends_on, name FROM flywheel_campaigns
                 WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    status, starts_on, ends_on, name = campaign
    # The window is [starts_on, window_end) — HALF-OPEN, so window_end must be
    # the day AFTER the last day we want counted. Using `today` directly made
    # the window ZERO-WIDTH for a campaign measured on its own start date
    # (`[today, today)` contains nothing) and silently dropped the final day of
    # every other campaign. Both arms then reported 0 retained, which reads as
    # "the campaign achieved nothing" rather than "we measured nothing" — the
    # most dangerous kind of wrong number, because it looks like a result.
    window_end = min(date.today() + timedelta(days=1),
                     starts_on + timedelta(days=RETENTION_WINDOW_DAYS))

    # Retention per arm, in one pass. `purchased` counts customers with at least
    # one purchase in the measurement window — identical logic for both arms.
    rows = (await db.execute(
        text("""SELECT a.assignment,
                       COUNT(DISTINCT a.customer_id) AS arm_size,
                       COUNT(DISTINCT e.customer_id) AS retained
                  FROM flywheel_campaign_audience a
                  LEFT JOIN flywheel_customer_events e
                    ON e.customer_id = a.customer_id
                   AND e.tenant_id = a.tenant_id
                   AND e.event_type IN ('purchase', 'offer_redeemed')
                   AND e.occurred_at >= :start
                   AND e.occurred_at <  :end
                 WHERE a.campaign_id = :c AND a.tenant_id = :t
                 GROUP BY a.assignment"""),
        {"c": campaign_id, "t": tenant_id, "start": starts_on, "end": window_end},
    )).fetchall()

    arms = {row[0]: {"size": int(row[1]), "retained": int(row[2])} for row in rows}
    treatment = arms.get("treatment", {"size": 0, "retained": 0})
    control = arms.get("control", {"size": 0, "retained": 0})

    treatment_rate = (Decimal(treatment["retained"]) / Decimal(treatment["size"])
                      if treatment["size"] else ZERO)
    control_rate = (Decimal(control["retained"]) / Decimal(control["size"])
                    if control["size"] else ZERO)
    incremental_retention = treatment_rate - control_rate

    # --- financials -------------------------------------------------------
    financials = (await db.execute(
        text("""SELECT COALESCE(SUM(net_value_aed), 0), COALESCE(SUM(margin_aed), 0),
                       COALESCE(SUM(discount_aed), 0), COUNT(*)
                  FROM flywheel_redemptions
                 WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    gross_revenue = money(financials[0])
    gross_margin = money(financials[1])
    discount_spend = money(financials[2])
    redemption_count = int(financials[3])

    # THE KEY CORRECTION. Only the INCREMENTAL share of revenue is attributable
    # to the campaign. Reporting gross revenue as campaign revenue is the single
    # most common way retention programmes overstate their value.
    attributable_share = (incremental_retention / treatment_rate
                          if treatment_rate > ZERO else ZERO)
    incremental_revenue = money(gross_revenue * attributable_share)
    incremental_margin = money(gross_margin * attributable_share)

    procurement_cost = money((await db.execute(
        text("""SELECT COALESCE(SUM(total_cost_aed), 0)
                  FROM flywheel_procurement_requisitions
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND status IN ('approved', 'converted_to_po')"""),
        {"t": tenant_id, "c": campaign_id},
    )).scalar() or 0)

    total_cost = money(discount_spend + procurement_cost)
    incremental_retained = int(
        Decimal(treatment["size"]) * incremental_retention) if treatment["size"] else 0
    cost_per_retained = (money(total_cost / Decimal(incremental_retained))
                         if incremental_retained > 0 else None)
    campaign_roi = (money((incremental_margin - total_cost) / total_cost)
                    if total_cost > ZERO else None)

    # --- budget variance --------------------------------------------------
    exposure = await budget_service.campaign_exposure(
        db, tenant_id=tenant_id, campaign_id=campaign_id)
    budget_variance = money(money(exposure["reserved_aed"]) - money(exposure["spent_aed"]))

    # --- uplift by segment ------------------------------------------------
    segments = await _uplift_by_segment(
        db, tenant_id=tenant_id, campaign_id=campaign_id,
        starts_on=starts_on, window_end=window_end)

    # --- stockout rate ----------------------------------------------------
    stockouts = (await db.execute(
        text("""SELECT COUNT(*) FILTER (WHERE rejected_actions::text LIKE '%INSUFFICIENT_STOCK%'),
                       COUNT(*)
                  FROM flywheel_decisions
                 WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    stockout_rate = (Decimal(int(stockouts[0])) / Decimal(int(stockouts[1]))
                     if int(stockouts[1]) else ZERO)

    result = {
        "campaign_id": campaign_id,
        "campaign_name": name,
        "measured_window": {"from": str(starts_on), "to": str(window_end),
                            "days": (window_end - starts_on).days},
        "treatment": {
            "size": treatment["size"], "retained": treatment["retained"],
            "retention_rate": round(float(treatment_rate), 5),
        },
        "control": {
            "size": control["size"], "retained": control["retained"],
            "retention_rate": round(float(control_rate), 5),
        },
        "incremental_retention": round(float(incremental_retention), 5),
        "incremental_customers_retained": incremental_retained,
        "gross_revenue_aed": str(gross_revenue),
        "incremental_revenue_aed": str(incremental_revenue),
        "incremental_margin_aed": str(incremental_margin),
        "discount_spend_aed": str(discount_spend),
        "procurement_cost_aed": str(procurement_cost),
        "cost_per_retained_aed": str(cost_per_retained) if cost_per_retained else None,
        "campaign_roi": str(campaign_roi) if campaign_roi is not None else None,
        "budget_variance_aed": str(budget_variance),
        "stockout_rate": round(float(stockout_rate), 5),
        "redemptions": redemption_count,
        "uplift_by_segment": segments,
        "causal_note": (
            "Incremental figures are treatment MINUS control, using a stable-hash "
            "split fixed when the audience was built. Gross revenue is shown "
            "separately and is NOT the campaign's contribution — only the "
            "incremental share is attributable."
        ),
        "validity": _validity_warnings(treatment["size"], control["size"],
                                       incremental_retention),
        "synthetic": True,
    }

    if persist:
        await db.execute(
            text("""INSERT INTO flywheel_campaign_outcomes
                       (tenant_id, campaign_id, treatment_size, control_size,
                        treatment_retained, control_retained, treatment_retention_rate,
                        control_retention_rate, incremental_retention,
                        incremental_revenue_aed, incremental_margin_aed,
                        discount_spend_aed, procurement_cost_aed, cost_per_retained_aed,
                        campaign_roi, uplift_by_segment, budget_variance_aed,
                        stockout_rate, notes)
                    VALUES (:t, :c, :ts, :cs, :tr, :cr, :trr, :crr, :inc,
                            :rev, :marg, :disc, :proc, :cpr, :roi,
                            CAST(:seg AS JSONB), :var, :stock, :notes)
                    ON CONFLICT (campaign_id, measured_at) DO NOTHING"""),
            {"t": tenant_id, "c": campaign_id,
             "ts": treatment["size"], "cs": control["size"],
             "tr": treatment["retained"], "cr": control["retained"],
             "trr": round(float(treatment_rate), 5), "crr": round(float(control_rate), 5),
             "inc": round(float(incremental_retention), 5),
             "rev": incremental_revenue, "marg": incremental_margin,
             "disc": discount_spend, "proc": procurement_cost,
             "cpr": cost_per_retained, "roi": campaign_roi,
             "seg": json.dumps(segments), "var": budget_variance,
             "stock": round(float(stockout_rate), 5),
             "notes": "Synthetic data; incremental figures are causal (treatment − control)."},
        )

        if CampaignStatus(status) == CampaignStatus.COMPLETED:
            await campaign_state.transition(
                db, tenant_id=tenant_id, campaign_id=campaign_id,
                target=CampaignStatus.MEASURED, actor_kind="system",
                reason=f"Measured: incremental retention "
                       f"{float(incremental_retention):.2%}")

        await outbox.emit(
            db, tenant_id=tenant_id, channel=outbox.CHANNEL_CAMPAIGN,
            event_type="campaign.measured",
            payload={"campaign_id": campaign_id,
                     "incremental_retention": round(float(incremental_retention), 5),
                     "roi": str(campaign_roi) if campaign_roi else None},
            campaign_id=campaign_id)

    logger.info("flywheel.measure campaign=%s incremental=%.4f roi=%s",
                campaign_id, float(incremental_retention), campaign_roi)
    return result


def _validity_warnings(treatment_size: int, control_size: int,
                       incremental: Decimal) -> List[str]:
    """Say plainly when the result cannot bear the weight being put on it.

    Reporting a confident-looking ROI off a 12-customer control group is how
    measurement theatre happens. These warnings are surfaced in the UI next to
    the numbers, not buried.
    """
    warnings: List[str] = []
    if control_size < 30:
        warnings.append(
            f"Control group has only {control_size} customers — too small for a "
            f"reliable estimate. Treat the incremental figures as directional.")
    if treatment_size < 30:
        warnings.append(f"Treatment arm has only {treatment_size} customers.")
    if control_size and treatment_size:
        ratio = treatment_size / control_size
        if ratio > 8:
            warnings.append(
                f"Treatment is {ratio:.0f}× the control arm; consider a larger "
                f"control share for a tighter estimate.")
    if incremental < 0:
        warnings.append(
            "Incremental retention is NEGATIVE — the treated group retained WORSE "
            "than control. This campaign may have destroyed value; investigate "
            "before repeating it.")
    return warnings


async def _uplift_by_segment(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    starts_on: date, window_end: date,
) -> Dict[str, Any]:
    """Incremental retention broken out by risk band.

    Segmenting by BAND rather than archetype is deliberate: risk band is
    something the model produced and an operator can act on, whereas archetype
    is generator ground truth that would not exist with real customers.
    """
    rows = (await db.execute(
        text("""SELECT p.risk_band, a.assignment,
                       COUNT(DISTINCT a.customer_id),
                       COUNT(DISTINCT e.customer_id)
                  FROM flywheel_campaign_audience a
                  JOIN flywheel_churn_predictions p
                    ON p.customer_id = a.customer_id AND p.tenant_id = a.tenant_id
                  LEFT JOIN flywheel_customer_events e
                    ON e.customer_id = a.customer_id
                   AND e.event_type IN ('purchase', 'offer_redeemed')
                   AND e.occurred_at >= :start AND e.occurred_at < :end
                 WHERE a.campaign_id = :c AND a.tenant_id = :t
                 GROUP BY p.risk_band, a.assignment"""),
        {"c": campaign_id, "t": tenant_id, "start": starts_on, "end": window_end},
    )).fetchall()

    by_band: Dict[str, Dict[str, Any]] = {}
    for band, assignment, size, retained in rows:
        entry = by_band.setdefault(band, {})
        entry[assignment] = {"size": int(size), "retained": int(retained),
                             "rate": round(int(retained) / int(size), 5) if size else 0.0}

    for band, entry in by_band.items():
        treatment_rate = entry.get("treatment", {}).get("rate", 0.0)
        control_rate = entry.get("control", {}).get("rate", 0.0)
        entry["incremental_retention"] = round(treatment_rate - control_rate, 5)
        control_n = entry.get("control", {}).get("size", 0)
        entry["reliable"] = control_n >= 30
        if not entry["reliable"]:
            entry["note"] = f"Control n={control_n} — directional only"

    return by_band


async def latest_outcome(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Optional[Dict[str, Any]]:
    row = (await db.execute(
        text("""SELECT treatment_size, control_size, treatment_retention_rate,
                       control_retention_rate, incremental_retention,
                       incremental_revenue_aed, incremental_margin_aed,
                       discount_spend_aed, cost_per_retained_aed, campaign_roi,
                       uplift_by_segment, budget_variance_aed, measured_at
                  FROM flywheel_campaign_outcomes
                 WHERE tenant_id = :t AND campaign_id = :c
                 ORDER BY measured_at DESC LIMIT 1"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    if not row:
        return None
    return {
        "treatment_size": int(row[0]), "control_size": int(row[1]),
        "treatment_retention_rate": float(row[2]), "control_retention_rate": float(row[3]),
        "incremental_retention": float(row[4]),
        "incremental_revenue_aed": str(money(row[5])),
        "incremental_margin_aed": str(money(row[6])),
        "discount_spend_aed": str(money(row[7])),
        "cost_per_retained_aed": str(money(row[8])) if row[8] is not None else None,
        "campaign_roi": float(row[9]) if row[9] is not None else None,
        "uplift_by_segment": row[10] or {},
        "budget_variance_aed": str(money(row[11])),
        "measured_at": row[12].isoformat() if row[12] else None,
    }
