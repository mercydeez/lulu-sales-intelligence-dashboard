"""Scheduled incrementality readouts — where the loop actually closes.

WHAT WAS MISSING. `measurement.measure()` computed treatment-vs-control
correctly and had done so for some time. But nothing scheduled it, nothing kept
its output, and no decision changed because of it. The product could compute
incremental lift and could not LEARN from it — the proof of value was built and
unplugged.

This module plugs it in. On a schedule it:

  1. recomputes every live campaign's outcome,
  2. wraps the point estimate in an ANYTIME-VALID interval (sequential.py), so a
     number that is refreshed all day stays honest,
  3. checks the two arms are still COMPARABLE (covariate balance) — because a
     perfectly computed difference between two groups that drifted apart is a
     confounded number, and nothing detected that before,
  4. writes the result to `flywheel_readouts`, which the database will not let
     anyone edit afterwards,
  5. updates each shadow model's standing against its pre-registered promotion
     bar.

THE HEADLINE NUMBER is `margin_per_aed_spent`: incremental gross margin, net of
VAT, per AED of promo spend, measured against the held-out control. It is the
one figure the CFO lens asked for and the one the product could not previously
show.

WHY A LIFESPAN TASK AND NOT A JOB QUEUE. There is a worker container, but it is
a Node diagnostics scanner — not a queue the Python backend can dispatch to.
Introducing a real worker tier is Horizon 2 work and deliberately out of scope
here; this follows the established `DataGenerator` lifespan-task pattern so the
capability lands now without pre-empting that decision. The known limitation is
stated plainly rather than hidden: a redeploy mid-readout loses that cycle, and
the next tick simply recomputes it. That is tolerable ONLY because readouts are
idempotent per (campaign, window_end) — re-running is a no-op, never a double
count.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import measurement, sequential
from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: How often the scheduler recomputes. Readouts are cheap and idempotent, but
#: an hourly cadence is plenty for a 60-day retention window — anything faster
#: is churn for its own sake.
READOUT_INTERVAL_SECONDS = 3600

#: Campaign states worth measuring. DRAFT has no outcome; CANCELLED has no
#: meaning; MEASURED keeps being recomputed on purpose, because the window may
#: still be open and evidence still accumulating.
MEASURABLE_STATUSES = (
    "ACTIVE", "PAUSED", "COMPLETED", "MEASURED", "SCHEDULED",
)

#: Covariates checked for balance between arms.
#:
#: ALL ARE PRE-TREATMENT — measured before the campaign touched anyone. Checking
#: a post-treatment variable would guarantee "imbalance" exactly when the
#: campaign worked, which inverts the diagnostic: the better the campaign, the
#: louder the warning that it cannot be trusted.
#:
#: `churn_probability` is taken from the AUDIENCE row rather than the prediction
#: table because it was frozen at assignment time, which is precisely the
#: pre-treatment moment we want. The feature columns come from the snapshot in
#: force on the campaign's start date — see the DISTINCT ON in check_balance.
BALANCE_COVARIATES = {
    "churn_probability": "a.churn_probability",
    "recency_days": "COALESCE(f.recency_days, 0)",
    "frequency_90d": "COALESCE(f.frequency_90d, 0)",
    "monetary_90d_aed": "COALESCE(f.monetary_90d_aed, 0)",
    "avg_basket_aed": "COALESCE(f.avg_basket_aed, 0)",
    "tenure_days": "COALESCE(f.tenure_days, 0)",
}


async def compute_and_store(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    computed_by: str = "scheduler",
) -> Dict[str, Any]:
    """Produce one immutable readout for a campaign and persist it.

    Idempotent per (tenant, campaign, window_end): running twice on the same day
    writes once. That is what makes it safe to retry after a lost cycle.
    """
    # `persist=False` — measure() writes to its own legacy outcomes table, and
    # letting it do so here would double-record the same measurement in two
    # places with two different definitions of "latest".
    outcome = await measurement.measure(
        db, tenant_id=tenant_id, campaign_id=campaign_id, persist=False)

    prereg = await get_preregistration(db, tenant_id=tenant_id, campaign_id=campaign_id)
    alpha = float(prereg["alpha"]) if prereg else sequential.DEFAULT_ALPHA
    mde = float(prereg["min_detectable_effect"]) if prereg else 0.0

    treatment = outcome["treatment"]
    control = outcome["control"]

    cs = sequential.difference_of_proportions(
        treatment_converted=treatment["retained"], treatment_n=treatment["size"],
        control_converted=control["retained"], control_n=control["size"],
        alpha=alpha,
    )

    window = outcome["measured_window"]
    window_start = date.fromisoformat(window["from"])
    window_end = date.fromisoformat(window["to"])

    discount_spend = _dec(outcome["discount_spend_aed"])
    procurement_cost = _dec(outcome["procurement_cost_aed"])
    total_cost = money(discount_spend + procurement_cost)
    incremental_margin = _dec(outcome["incremental_margin_aed"])

    # THE HEADLINE NUMBER. None rather than a sentinel when nothing was spent:
    # an undefined ratio rendered as infinite ROI is worse than an honest gap,
    # and a zero here would read as "the campaign earned nothing".
    margin_per_aed = (money(incremental_margin / total_cost)
                      if total_cost > ZERO else None)

    warnings: List[str] = list(outcome.get("validity", []))
    balance = await check_balance(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if balance["summary"]["status"] == "imbalanced":
        warnings.append(balance["summary"]["note"])
    if cs is None:
        warnings.append(
            f"Arms are too small for an anytime-valid interval (need "
            f"{sequential.MIN_ARM_FOR_INTERVAL} per arm). The point estimate is "
            f"shown without a confidence range and should not be acted on.")

    row = {
        "t": tenant_id, "c": campaign_id,
        "prereg": prereg["id"] if prereg else None,
        "ws": window_start, "we": window_end,
        "tn": treatment["size"], "cn": control["size"],
        "tc": treatment["retained"], "cc": control["retained"],
        "tr": treatment["retention_rate"], "cr": control["retention_rate"],
        "inc": outcome["incremental_retention"],
        "lo": cs.lower if cs else None,
        "hi": cs.upper if cs else None,
        "method": cs.method if cs else "none",
        "alpha": alpha,
        "loge": cs.log_e_value if cs else None,
        "sig": bool(cs and cs.excludes_zero),
        "mde": bool(cs and cs.meets_effect_size(mde)),
        "rev": _dec(outcome["incremental_revenue_aed"]),
        "marg": incremental_margin,
        "disc": discount_spend,
        "proc": procurement_cost,
        "tot": total_cost,
        "mpa": margin_per_aed,
        "roi": _dec_or_none(outcome.get("campaign_roi")),
        "warn": json.dumps(warnings),
        "seg": json.dumps(outcome.get("uplift_by_segment", {})),
        "by": computed_by,
    }

    await db.execute(
        text("""INSERT INTO flywheel_readouts
                   (tenant_id, campaign_id, preregistration_id, window_start, window_end,
                    treatment_n, control_n, treatment_converted, control_converted,
                    treatment_rate, control_rate, incremental_retention,
                    ci_lower, ci_upper, ci_method, alpha, log_e_value,
                    is_significant, meets_mde,
                    incremental_revenue_aed, incremental_margin_aed, discount_spend_aed,
                    procurement_cost_aed, total_cost_aed, margin_per_aed_spent,
                    campaign_roi, validity_warnings, uplift_by_segment, computed_by)
                VALUES (:t, :c, :prereg, :ws, :we, :tn, :cn, :tc, :cc,
                        :tr, :cr, :inc, :lo, :hi, :method, :alpha, :loge,
                        :sig, :mde, :rev, :marg, :disc, :proc, :tot, :mpa, :roi,
                        CAST(:warn AS JSONB), CAST(:seg AS JSONB), :by)
                ON CONFLICT (tenant_id, campaign_id, window_end) DO NOTHING"""),
        row,
    )

    interpretation = sequential.interpret(cs, min_detectable_effect=mde)
    logger.info("flywheel.readout campaign=%s inc=%.4f state=%s margin_per_aed=%s",
                campaign_id, outcome["incremental_retention"],
                interpretation["state"], margin_per_aed)

    return {
        "campaign_id": campaign_id,
        "campaign_name": outcome["campaign_name"],
        "window": window,
        "treatment": treatment,
        "control": control,
        "incremental_retention": outcome["incremental_retention"],
        "interval": cs.to_row() if cs else None,
        "interpretation": interpretation,
        "incremental_margin_aed": str(incremental_margin),
        "total_cost_aed": str(total_cost),
        "margin_per_aed_spent": str(margin_per_aed) if margin_per_aed is not None else None,
        "validity_warnings": warnings,
        "balance": balance["summary"],
        "uplift_by_segment": outcome.get("uplift_by_segment", {}),
        "preregistered": prereg is not None,
        "synthetic": True,
    }


# ---------------------------------------------------------------------------
# Pre-registration
# ---------------------------------------------------------------------------

async def get_preregistration(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Optional[Dict[str, Any]]:
    row = (await db.execute(
        text("""SELECT id, primary_metric, window_days, stopping_rule, alpha,
                       min_detectable_effect, planned_treatment_n, planned_control_n,
                       control_pct, registered_at, notes
                  FROM flywheel_preregistrations
                 WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]), "primary_metric": row[1], "window_days": int(row[2]),
        "stopping_rule": row[3], "alpha": float(row[4]),
        "min_detectable_effect": float(row[5]),
        "planned_treatment_n": int(row[6]), "planned_control_n": int(row[7]),
        "control_pct": str(row[8]),
        "registered_at": row[9].isoformat() if row[9] else None,
        "notes": row[10],
    }


async def preregister(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    primary_metric: str = "incremental_retention", window_days: int = 60,
    alpha: float = sequential.DEFAULT_ALPHA, min_detectable_effect: float = 0.02,
    planned_treatment_n: int = 0, planned_control_n: int = 0,
    control_pct: Decimal = Decimal("10.00"),
    registered_by: Optional[int] = None, notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Fix what will be measured, BEFORE the campaign runs.

    Refuses to overwrite an existing registration. That refusal is the entire
    point: a pre-registration you can revise after seeing the result is just a
    post-hoc rationalisation with an earlier timestamp. The database enforces it
    too (unique constraint plus an append-only trigger); this is the polite
    error rather than the integrity violation.
    """
    existing = await get_preregistration(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if existing:
        raise ValueError(
            f"Campaign {campaign_id} is already pre-registered (at "
            f"{existing['registered_at']}). A pre-registration cannot be changed "
            f"after the fact — that is what makes it evidence."
        )

    await db.execute(
        text("""INSERT INTO flywheel_preregistrations
                   (tenant_id, campaign_id, primary_metric, window_days, alpha,
                    min_detectable_effect, planned_treatment_n, planned_control_n,
                    control_pct, registered_by, notes)
                VALUES (:t, :c, :m, :w, :a, :mde, :ptn, :pcn, :cp, :by, :notes)"""),
        {"t": tenant_id, "c": campaign_id, "m": primary_metric, "w": window_days,
         "a": alpha, "mde": min_detectable_effect, "ptn": planned_treatment_n,
         "pcn": planned_control_n, "cp": control_pct, "by": registered_by,
         "notes": notes},
    )
    return await get_preregistration(db, tenant_id=tenant_id, campaign_id=campaign_id)


# ---------------------------------------------------------------------------
# Covariate balance
# ---------------------------------------------------------------------------

async def check_balance(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, persist: bool = True,
) -> Dict[str, Any]:
    """Are treatment and control still comparable?

    The stable-hash split should produce balanced arms and usually does. But
    "should" is not "did": differential attrition, a mid-campaign audience edit,
    or an eligibility filter applied to one arm all break comparability
    silently, and every downstream number stays confidently wrong. Nothing in
    the product detected this before.
    """
    select_exprs = ",\n                       ".join(
        f"{expr} AS {name}" for name, expr in BALANCE_COVARIATES.items())

    # ONE FEATURE ROW PER CUSTOMER, AND IT MUST BE A PRE-TREATMENT ONE.
    #
    # flywheel_feature_snapshots is effective-dated, so a naive join multiplies
    # every customer by their snapshot count. Customers with more history would
    # then be weighted more heavily in the arm means, and the imbalance
    # diagnostic would be measuring snapshot frequency rather than covariate
    # balance — a wrong answer that looks like a right one.
    #
    # DISTINCT ON picks the latest snapshot dated on or before the campaign
    # start. Later snapshots are excluded on purpose: a feature measured after
    # treatment began is contaminated by the treatment.
    rows = (await db.execute(
        text(f"""WITH pre AS (
                    SELECT DISTINCT ON (fs.customer_id)
                           fs.customer_id, fs.recency_days, fs.frequency_90d,
                           fs.monetary_90d_aed, fs.avg_basket_aed, fs.tenure_days
                      FROM flywheel_feature_snapshots fs
                      JOIN flywheel_campaigns c
                        ON c.id = :c AND c.tenant_id = fs.tenant_id
                     WHERE fs.tenant_id = :t
                       AND fs.as_of_date <= c.starts_on
                     ORDER BY fs.customer_id, fs.as_of_date DESC
                )
                SELECT a.assignment,
                       {select_exprs}
                  FROM flywheel_campaign_audience a
                  LEFT JOIN pre f ON f.customer_id = a.customer_id
                 WHERE a.campaign_id = :c AND a.tenant_id = :t
                   AND a.assignment IN ('treatment', 'control')"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchall()

    by_arm: Dict[str, Dict[str, List[float]]] = {
        "treatment": {k: [] for k in BALANCE_COVARIATES},
        "control": {k: [] for k in BALANCE_COVARIATES},
    }
    for row in rows:
        arm = row[0]
        if arm not in by_arm:
            continue
        for offset, name in enumerate(BALANCE_COVARIATES, start=1):
            value = row[offset]
            if value is not None:
                by_arm[arm][name].append(float(value))

    checks: List[sequential.BalanceCheck] = []
    for name in BALANCE_COVARIATES:
        check = sequential.standardised_mean_difference(
            name, by_arm["treatment"][name], by_arm["control"][name])
        if check:
            checks.append(check)

    if persist and checks:
        for check in checks:
            payload = check.to_row()
            await db.execute(
                text("""INSERT INTO flywheel_holdout_balance
                           (tenant_id, campaign_id, covariate, treatment_mean,
                            control_mean, pooled_sd, smd, threshold, is_balanced)
                        VALUES (:t, :c, :cov, :tm, :cm, :sd, :smd, :th, :bal)
                        ON CONFLICT (tenant_id, campaign_id, checked_on, covariate)
                        DO NOTHING"""),
                {"t": tenant_id, "c": campaign_id, "cov": payload["covariate"],
                 "tm": payload["treatment_mean"], "cm": payload["control_mean"],
                 "sd": payload["pooled_sd"],
                 # inf is not representable in a DOUBLE PRECISION column in a way
                 # any consumer handles well; clamp to a large finite marker.
                 "smd": min(payload["smd"], 999.0) if payload["smd"] == payload["smd"] else 0.0,
                 "th": payload["threshold"], "bal": payload["is_balanced"]},
            )

    return {
        "checks": [c.to_row() for c in checks],
        "summary": sequential.summarise_balance(checks),
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

async def run_once(db_factory, *, tenant_id: int) -> Dict[str, Any]:
    """One scheduler pass over every measurable campaign for a tenant."""
    processed, failed = 0, 0
    async with db_factory() as db:
        campaigns = (await db.execute(
            text("""SELECT id FROM flywheel_campaigns
                     WHERE tenant_id = :t AND status = ANY(:statuses)
                     ORDER BY id"""),
            {"t": tenant_id, "statuses": list(MEASURABLE_STATUSES)},
        )).fetchall()

    for (campaign_id,) in campaigns:
        # A fresh session per campaign so one failure cannot poison the rest —
        # a single bad campaign should not silently stop measurement for every
        # other campaign in the tenant.
        try:
            async with db_factory() as db:
                await compute_and_store(db, tenant_id=tenant_id,
                                        campaign_id=int(campaign_id))
                await db.commit()
            processed += 1
        except Exception:
            failed += 1
            logger.exception("flywheel.readout failed campaign=%s", campaign_id)

    logger.info("flywheel.readout pass tenant=%s processed=%s failed=%s",
                tenant_id, processed, failed)
    return {"processed": processed, "failed": failed, "campaigns": len(campaigns)}


async def scheduler_loop(db_factory, *, tenant_id: int,
                         interval_seconds: int = READOUT_INTERVAL_SECONDS) -> None:
    """Recompute readouts forever. Started from the app lifespan.

    Never lets an exception escape: a measurement task that dies takes the
    product's proof of value down with it, and it would do so silently because
    nothing is waiting on this coroutine.
    """
    logger.info("flywheel.readout scheduler started (every %ss)", interval_seconds)
    while True:
        try:
            await run_once(db_factory, tenant_id=tenant_id)
        except asyncio.CancelledError:
            logger.info("flywheel.readout scheduler stopping")
            raise
        except Exception:
            logger.exception("flywheel.readout scheduler pass failed; continuing")
        await asyncio.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def history(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, limit: int = 90,
) -> List[Dict[str, Any]]:
    """The readout time series — how significance accumulated.

    This is what lets the Incrementality page show evidence building over time
    rather than a single number that mutates under the user. Watching a
    confidence sequence narrow is also the most effective explanation of why
    the campaign should not be stopped at the first good-looking day.
    """
    rows = (await db.execute(
        text("""SELECT window_start, window_end, treatment_n, control_n,
                       treatment_converted, control_converted,
                       incremental_retention, ci_lower, ci_upper, log_e_value,
                       is_significant, meets_mde, incremental_margin_aed,
                       total_cost_aed, margin_per_aed_spent, validity_warnings,
                       computed_at
                  FROM flywheel_readouts
                 WHERE tenant_id = :t AND campaign_id = :c
                 ORDER BY window_end ASC
                 LIMIT :lim"""),
        {"t": tenant_id, "c": campaign_id, "lim": limit},
    )).fetchall()

    return [{
        "window_start": str(r[0]), "window_end": str(r[1]),
        "treatment_n": int(r[2]), "control_n": int(r[3]),
        "treatment_converted": int(r[4]), "control_converted": int(r[5]),
        "incremental_retention": float(r[6]),
        "ci_lower": float(r[7]) if r[7] is not None else None,
        "ci_upper": float(r[8]) if r[8] is not None else None,
        "log_e_value": float(r[9]) if r[9] is not None else None,
        "is_significant": bool(r[10]), "meets_mde": bool(r[11]),
        "incremental_margin_aed": str(money(r[12])),
        "total_cost_aed": str(money(r[13])),
        "margin_per_aed_spent": str(money(r[14])) if r[14] is not None else None,
        "validity_warnings": r[15] or [],
        "computed_at": r[16].isoformat() if r[16] else None,
    } for r in rows]


async def latest(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Optional[Dict[str, Any]]:
    rows = await history(db, tenant_id=tenant_id, campaign_id=campaign_id, limit=1000)
    return rows[-1] if rows else None


async def portfolio_summary(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """Tenant-wide roll-up for the Incrementality landing view.

    Deliberately reports how many campaigns are INCONCLUSIVE alongside how many
    are proven. A dashboard that shows only the winners is how a retention
    programme convinces itself it works.
    """
    row = (await db.execute(
        text("""WITH latest AS (
                    SELECT DISTINCT ON (campaign_id) *
                      FROM flywheel_readouts
                     WHERE tenant_id = :t
                     ORDER BY campaign_id, window_end DESC
                )
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE is_significant),
                       COUNT(*) FILTER (WHERE is_significant AND incremental_retention > 0),
                       COUNT(*) FILTER (WHERE is_significant AND incremental_retention < 0),
                       COALESCE(SUM(incremental_margin_aed), 0),
                       COALESCE(SUM(total_cost_aed), 0)
                  FROM latest"""),
        {"t": tenant_id},
    )).fetchone()

    measured = int(row[0] or 0)
    significant = int(row[1] or 0)
    total_margin = money(row[4] or 0)
    total_spend = money(row[5] or 0)

    return {
        "campaigns_measured": measured,
        "significant": significant,
        "proven_positive": int(row[2] or 0),
        "proven_negative": int(row[3] or 0),
        "inconclusive": measured - significant,
        "incremental_margin_aed": str(total_margin),
        "total_spend_aed": str(total_spend),
        "margin_per_aed_spent": (str(money(total_margin / total_spend))
                                 if total_spend > ZERO else None),
        "note": (
            "Inconclusive campaigns are counted, not hidden. A programme that "
            "reports only its proven winners is measuring its own marketing, "
            "not its effect."
        ),
    }


def _dec(value: Any) -> Decimal:
    try:
        return money(value)
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _dec_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return money(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
