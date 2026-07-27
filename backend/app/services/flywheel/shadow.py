"""Shadow mode — what the models WOULD have done, and whether they earned trust.

THE RULING THIS IMPLEMENTS (20 Jul 2026). The deterministic rule tier is the
production decision path. Models run in shadow: they score, their decisions are
recorded next to the rule decisions that actually shipped, and they are promoted
only when a pre-registered holdout shows them beating rules with a confidence
interval that excludes zero.

WHY. Three training runs produced three different winners — GRU 0.8961, then
FT-Transformer 0.9197, then LightGBM — and Qini swung from +1.13 to -3.80. At
n=300 with roughly 16 positives in the test split, none of those numbers is
distinguishable from sampling noise. Choosing a "best" model from that is
choosing a random number and calling it a decision.

This module is what turns that from a hidden liability into a governed process.
The models are not hidden and not trusted: they run continuously, their
disagreements with the shipping path are counted, and there is a written bar
they must clear. A technical buyer who asks "how do you know your model works?"
gets a scoreboard rather than a shrug.

WHAT MAKES A DISAGREEMENT INTERESTING. Not its size — its KIND. A model that
wants a 15% discount where rules chose 10% is haggling. A model that wants to
contact someone rules chose to leave alone is disagreeing about the decision
itself, and that is the disagreement that would change spend if promoted. The
two are recorded separately for exactly that reason.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, ActionType, money

logger = logging.getLogger(__name__)


def classify_disagreement(
    *, rule_action: str, rule_discount: Decimal,
    shadow_action: str, shadow_discount: Decimal,
) -> Optional[str]:
    """How the two paths differ, or None if they agree.

    'action'    — different decision entirely (contact vs don't, or a different
                  instrument). This is the kind that changes outcomes.
    'magnitude' — same decision, different size. Cheaper to be wrong about.
    'both'      — different action AND materially different spend.
    """
    action_differs = rule_action != shadow_action
    discount_differs = money(rule_discount) != money(shadow_discount)

    if not action_differs and not discount_differs:
        return None
    if action_differs and discount_differs:
        return "both"
    if action_differs:
        return "action"
    return "magnitude"


async def record(
    db: AsyncSession, *, tenant_id: int, customer_id: int,
    campaign_id: Optional[int], model_label: str,
    rule_action: str, rule_discount: Decimal, rule_eiv: Decimal,
    rule_churn: Optional[float],
    shadow_action: str, shadow_discount: Decimal, shadow_eiv: Decimal,
    shadow_churn: Optional[float],
    decision_id: Optional[int] = None,
    model_version_id: Optional[int] = None,
) -> None:
    """Log one rule-vs-model comparison.

    Idempotent per (tenant, customer, campaign, model): re-scoring the same
    customer overwrites rather than inflating the disagreement denominator,
    which would otherwise make a model look worse purely for being scored twice.
    """
    kind = classify_disagreement(
        rule_action=rule_action, rule_discount=rule_discount,
        shadow_action=shadow_action, shadow_discount=shadow_discount)

    await db.execute(
        text("""INSERT INTO flywheel_shadow_decisions
                   (tenant_id, campaign_id, customer_id, decision_id,
                    model_version_id, model_label,
                    rule_action, rule_discount_pct, rule_eiv_aed, rule_churn_probability,
                    shadow_action, shadow_discount_pct, shadow_eiv_aed,
                    shadow_churn_probability, agreed, disagreement_kind)
                VALUES (:t, :c, :cust, :d, :mv, :label,
                        :ra, :rd, :re, :rc, :sa, :sd, :se, :sc, :agreed, :kind)
                ON CONFLICT (tenant_id, customer_id, campaign_id, model_label)
                DO UPDATE SET
                    rule_action = EXCLUDED.rule_action,
                    rule_discount_pct = EXCLUDED.rule_discount_pct,
                    rule_eiv_aed = EXCLUDED.rule_eiv_aed,
                    shadow_action = EXCLUDED.shadow_action,
                    shadow_discount_pct = EXCLUDED.shadow_discount_pct,
                    shadow_eiv_aed = EXCLUDED.shadow_eiv_aed,
                    agreed = EXCLUDED.agreed,
                    disagreement_kind = EXCLUDED.disagreement_kind"""),
        {"t": tenant_id, "c": campaign_id, "cust": customer_id, "d": decision_id,
         "mv": model_version_id, "label": model_label,
         "ra": rule_action, "rd": money(rule_discount), "re": money(rule_eiv),
         "rc": rule_churn, "sa": shadow_action, "sd": money(shadow_discount),
         "se": money(shadow_eiv), "sc": shadow_churn,
         "agreed": kind is None, "kind": kind},
    )


async def comparison(
    db: AsyncSession, *, tenant_id: int, model_label: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Per-model disagreement summary against the shipping rule tier."""
    rows = (await db.execute(
        text("""SELECT model_label,
                       COUNT(*),
                       COUNT(*) FILTER (WHERE NOT agreed),
                       COUNT(*) FILTER (WHERE disagreement_kind = 'action'),
                       COUNT(*) FILTER (WHERE disagreement_kind = 'magnitude'),
                       COUNT(*) FILTER (WHERE disagreement_kind = 'both'),
                       COALESCE(SUM(rule_eiv_aed), 0),
                       COALESCE(SUM(shadow_eiv_aed), 0)
                  FROM flywheel_shadow_decisions
                 WHERE tenant_id = :t
                   -- CAST is required, not stylistic: asyncpg cannot deduce a
                   -- parameter's type when it appears only as `$n IS NULL`, and
                   -- fails the whole statement with "could not determine data
                   -- type of parameter". Same trap as the `:as_of::timestamptz`
                   -- fix elsewhere in this package.
                   AND (CAST(:label AS TEXT) IS NULL
                        OR model_label = CAST(:label AS TEXT))
                 GROUP BY model_label
                 ORDER BY model_label"""),
        {"t": tenant_id, "label": model_label},
    )).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        total = int(r[1])
        disagreed = int(r[2])
        rule_eiv = money(r[6])
        shadow_eiv = money(r[7])

        # SELF-COMPARISON GUARD.
        #
        # If the only registered "model version" IS the rule tier, then the
        # stored churn probabilities were produced by the rule tier, and this
        # comparison is rules against themselves. It yields 0% disagreement by
        # construction.
        #
        # Rendered without this flag, a 0% disagreement rate reads as "the model
        # agrees with policy perfectly" — the most flattering possible reading of
        # a comparison that measured nothing at all. That is precisely the kind
        # of number that gets screenshotted into a board deck. Flag it loudly.
        is_self = str(r[0]).lower() in {"rule_based", "rule", "rules", "baseline"}

        out.append({
            "model_label": r[0],
            "scored": total,
            "disagreements": disagreed,
            "disagreement_rate": round(disagreed / total, 4) if total else 0.0,
            "is_self_comparison": is_self,
            "self_comparison_warning": (
                "This row compares the rule tier against ITSELF: no trained ML "
                "model version is registered, so the stored probabilities are the "
                "rule tier's own output. The 0% disagreement rate is an identity, "
                "not a result, and is NOT evidence that any model agrees with "
                "policy. Train and register a model version to get a real "
                "comparison."
            ) if is_self else None,
            "by_kind": {"action": int(r[3]), "magnitude": int(r[4]), "both": int(r[5])},
            "rule_eiv_aed": str(rule_eiv),
            "shadow_eiv_aed": str(shadow_eiv),
            "claimed_eiv_delta_aed": str(money(shadow_eiv - rule_eiv)),
            "claimed_delta_note": (
                "This delta is what the model CLAIMS it would have earned, scored "
                "by its own estimates. It is NOT evidence — a model that "
                "systematically overestimates uplift shows a large positive delta "
                "precisely because it is wrong. Only a holdout readout can settle it."
            ),
        })
    return out


async def promotion_standing(
    db: AsyncSession, *, tenant_id: int
) -> List[Dict[str, Any]]:
    """Each model's position against its pre-registered promotion bar."""
    criteria = (await db.execute(
        text("""SELECT model_label, min_readouts_required, min_ci_lower,
                       max_disagreement_rate, readouts_passed,
                       current_disagreement_rate, eligible_for_promotion,
                       blocked_reason, status, updated_at
                  FROM flywheel_promotion_criteria
                 WHERE tenant_id = :t
                 ORDER BY model_label"""),
        {"t": tenant_id},
    )).fetchall()

    comparisons = {c["model_label"]: c
                   for c in await comparison(db, tenant_id=tenant_id)}

    out: List[Dict[str, Any]] = []
    for r in criteria:
        label = r[0]
        comp = comparisons.get(label, {})
        rate = comp.get("disagreement_rate")
        max_rate = float(r[3])
        blockers: List[str] = []

        if int(r[4]) < int(r[1]):
            blockers.append(
                f"{int(r[4])}/{int(r[1])} qualifying readouts — needs a holdout "
                f"result with a confidence-sequence lower bound above "
                f"{float(r[2]):.2f}")
        if rate is not None and rate > max_rate:
            blockers.append(
                f"disagreement rate {rate:.1%} exceeds the {max_rate:.0%} ceiling")
        if not comp.get("scored"):
            blockers.append("no shadow decisions recorded yet")

        out.append({
            "model_label": label,
            "status": r[8],
            "readouts_passed": int(r[4]),
            "readouts_required": int(r[1]),
            "min_ci_lower": float(r[2]),
            "disagreement_rate": rate,
            "max_disagreement_rate": max_rate,
            "scored": comp.get("scored", 0),
            "eligible_for_promotion": bool(r[6]) and not blockers,
            "blockers": blockers,
            "blocked_reason": r[7],
            "updated_at": r[9].isoformat() if r[9] else None,
        })
    return out


async def refresh_standing(db: AsyncSession, *, tenant_id: int) -> int:
    """Recompute each model's disagreement rate and eligibility.

    Called from the readout scheduler so the scoreboard tracks evidence rather
    than being updated by hand — a promotion bar that a human maintains is a
    promotion bar that gets adjusted to fit the model.
    """
    comparisons = await comparison(db, tenant_id=tenant_id)
    updated = 0
    for comp in comparisons:
        result = await db.execute(
            text("""UPDATE flywheel_promotion_criteria
                       SET current_disagreement_rate = :rate,
                           eligible_for_promotion =
                               (readouts_passed >= min_readouts_required
                                AND :rate <= max_disagreement_rate),
                           updated_at = now()
                     WHERE tenant_id = :t AND model_label = :label"""),
            {"t": tenant_id, "label": comp["model_label"],
             "rate": comp["disagreement_rate"]},
        )
        updated += result.rowcount or 0
    return updated


# ---------------------------------------------------------------------------
# Shadow scoring pass
# ---------------------------------------------------------------------------

#: Discount ladder the rule tier walks by risk band. Deliberately coarse — the
#: rule tier's virtue is that a human can predict it, not that it is subtle.
_BAND_ACTION = {
    "critical": (ActionType.PERCENT_DISCOUNT, Decimal("15")),
    "high":     (ActionType.PERCENT_DISCOUNT, Decimal("10")),
    "medium":   (ActionType.REMINDER,         Decimal("0")),
    "low":      (ActionType.NO_ACTION,        Decimal("0")),
}


def action_for_probability(probability: float) -> tuple:
    """Map a churn probability to the action the tier would take.

    Shared by BOTH paths on purpose. The only thing that differs between the
    rule tier and a shadow model is the PROBABILITY they produce; running each
    through the same policy isolates the model's contribution instead of
    confounding it with a different action policy. Comparing a model plus a new
    policy against rules plus the old policy would tell you nothing about the
    model.
    """
    from app.services.flywheel.churn import band_for
    return _BAND_ACTION.get(band_for(probability), _BAND_ACTION["low"])


async def score_pass(
    db: AsyncSession, *, tenant_id: int, campaign_id: Optional[int] = None,
    limit: int = 1000,
) -> Dict[str, Any]:
    """Compare the shipping rule tier against every stored model prediction.

    HOW THIS IS AN HONEST COMPARISON. Both sides start from the same customer's
    same pre-treatment features. The rule tier recomputes its deterministic
    logit from those features; the shadow side uses the probability the trained
    model actually persisted. Both are then mapped to an action by the SAME
    policy. Any disagreement is therefore attributable to the model's estimate
    and nothing else.

    Nothing here touches money, stock or a customer. It is a recorded opinion.
    """
    from app.services.flywheel.churn import rule_based_score

    rows = (await db.execute(
        text("""SELECT DISTINCT ON (p.customer_id)
                       p.customer_id, p.churn_probability, p.model_version_id,
                       mv.algorithm, mv.version_label,
                       f.recency_days, f.frequency_90d, f.monetary_90d_aed,
                       f.avg_basket_aed, f.spend_drift_ratio,
                       f.interpurchase_gap_days, f.gap_volatility,
                       f.category_diversity, f.return_ratio,
                       f.promo_response_rate, f.tenure_days, f.events_90d
                  FROM flywheel_churn_predictions p
                  JOIN flywheel_feature_snapshots f
                    ON f.customer_id = p.customer_id AND f.tenant_id = p.tenant_id
                  LEFT JOIN flywheel_model_versions mv ON mv.id = p.model_version_id
                 WHERE p.tenant_id = :t
                 ORDER BY p.customer_id, p.as_of_date DESC, f.as_of_date DESC
                 LIMIT :lim"""),
        {"t": tenant_id, "lim": limit},
    )).fetchall()

    scored = 0
    for r in rows:
        features = {
            "recency_days": r[5], "frequency_90d": r[6], "monetary_90d_aed": r[7],
            "avg_basket_aed": r[8], "spend_drift_ratio": r[9],
            "interpurchase_gap_days": r[10], "gap_volatility": r[11],
            "category_diversity": r[12], "return_ratio": r[13],
            "promo_response_rate": r[14], "tenure_days": r[15], "events_90d": r[16],
        }
        rule_prob, _reasons = rule_based_score(features)
        shadow_prob = float(r[1])

        rule_action, rule_discount = action_for_probability(rule_prob)
        shadow_action, shadow_discount = action_for_probability(shadow_prob)

        # algorithm first (what it IS), version_label as fallback.
        label = (r[3] or r[4] or "unknown_model")
        await record(
            db, tenant_id=tenant_id, customer_id=int(r[0]), campaign_id=campaign_id,
            model_label=label, model_version_id=int(r[2]) if r[2] else None,
            rule_action=rule_action.value, rule_discount=rule_discount,
            rule_eiv=ZERO, rule_churn=rule_prob,
            shadow_action=shadow_action.value, shadow_discount=shadow_discount,
            shadow_eiv=ZERO, shadow_churn=shadow_prob,
        )
        scored += 1

    await refresh_standing(db, tenant_id=tenant_id)
    logger.info("flywheel.shadow score_pass tenant=%s scored=%s", tenant_id, scored)
    return {"scored": scored,
            "comparison": await comparison(db, tenant_id=tenant_id)}
