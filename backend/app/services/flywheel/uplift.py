"""Stage 2 — uplift: "would an offer actually CHANGE this customer's behaviour?"

WHY THIS IS A SEPARATE MODEL FROM CHURN, AND THE MOST IMPORTANT IDEA HERE.

Churn answers "who is leaving?". Targeting on churn alone spends money on two
groups that cannot repay it:

  * SURE THINGS — they were coming back anyway. The discount is pure margin loss.
  * LOST CAUSES — they are gone regardless. The discount buys nothing.

Uplift answers the actually useful question: P(stay | treated) − P(stay | control).
Only the PERSUADABLES have positive uplift. And some customers have NEGATIVE
uplift — a discount reminds a price-insensitive loyal buyer that they have been
overpaying, or a promotion-resistant customer finds contact annoying. Treating
them is worse than doing nothing.

That is why §5 of the brief says a high churn score must never trigger a large
discount on its own, and why `optimizer.py` gates on uplift, not risk.

EVALUATION HONESTY (§8.6): uplift models are NOT judged by outcome AUC. A model
can predict the outcome perfectly and rank uplift terribly. The correct metrics
are Qini / AUUC on a holdout, computed in `scripts/flywheel_train_uplift.py`.

TIER 1: a T-learner (separate treatment and control models) fitted on the
synthetic randomized-treatment log. TIER 2: a documented deterministic estimator,
used for the first vertical slice and whenever no artifact is registered.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ActionType

logger = logging.getLogger(__name__)

DETERMINISTIC_VERSION = "uplift-rule-v1"

#: Base persuadability per action, before customer-level adjustment.
#: Ordered by how intrusive/expensive the action is: a reminder is nearly free
#: and mildly effective; a deep discount is expensive and effective on a narrow
#: segment. These are DOCUMENTED ASSUMPTIONS, not fitted values — the whole
#: point of the deterministic tier is that they are inspectable.
BASE_RESPONSE: Dict[ActionType, float] = {
    ActionType.NO_ACTION: 0.00,
    ActionType.REMINDER: 0.03,
    ActionType.LOYALTY_POINTS: 0.06,
    ActionType.FREE_DELIVERY: 0.07,
    ActionType.PERCENT_DISCOUNT: 0.12,
    ActionType.FIXED_DISCOUNT: 0.11,
    ActionType.PRODUCT_BUNDLE: 0.09,
    ActionType.SUBSTITUTE_PRODUCT: 0.05,
    ActionType.ALTERNATIVE_STORE: 0.04,
    ActionType.HUMAN_REVIEW: 0.00,
}


def deterministic_uplift(
    *, action: ActionType, churn_probability: float, features: Dict[str, Any],
    discount_pct: float = 0.0,
) -> Tuple[float, float, float]:
    """Estimate (treated_response, control_response, uplift) without a model.

    The shape encodes three domain claims that a fitted model would have to
    learn, and which we can state plainly instead:

    1. PERSUADABILITY IS AN INVERTED-U IN RISK. Customers at moderate risk are
       movable. The near-certain-to-stay have nothing to gain; the near-certain-
       to-leave have already decided. Peak persuadability is around p≈0.5.

    2. PAST PROMO RESPONSE IS THE STRONGEST INDIVIDUAL PREDICTOR. Someone who
       has ignored ten offers will ignore the eleventh.

    3. DISCOUNT DEPTH HAS DIMINISHING RETURNS. Going 10%→20% moves people;
       40%→50% mostly moves margin. Modelled as a square-root response.
    """
    base = BASE_RESPONSE.get(action, 0.0)
    if base == 0.0:
        return 0.0, 0.0, 0.0

    def f(name: str, default: float = 0.0) -> float:
        value = features.get(name, default)
        try:
            return float(value if value is not None else default)
        except (TypeError, ValueError):
            return default

    promo_response = f("promo_response_rate")
    frequency = f("frequency_90d")
    return_ratio = f("return_ratio")

    # (1) Inverted-U in risk, peaking at 0.5 and vanishing at both extremes.
    persuadability = 4.0 * churn_probability * (1.0 - churn_probability)

    # (2) Past responsiveness. Centred so an AVERAGE responder (0.3) is neutral
    # at 1.0, a keen responder is amplified, and a never-responder is damped to
    # ~0.22 rather than merely reduced.
    #
    # The floor matters more than it looks. An earlier version used 0.45, which
    # still credited someone who had ignored every offer ever sent with ~5%
    # uplift — enough to clear the noise threshold and buy them a discount.
    # That directly contradicts claim (2): the strongest single predictor of
    # whether someone responds to an offer is whether they ever have.
    responsiveness = 0.22 + 2.6 * min(1.0, promo_response)

    # (3) Diminishing returns on depth (only for discount-shaped actions).
    depth_multiplier = 1.0
    if discount_pct > 0:
        depth_multiplier = 1.0 + 1.15 * ((discount_pct / 100.0) ** 0.5)

    # Frequent buyers are less movable — they were coming back anyway. This is
    # the "sure thing" correction, and it is what stops the optimizer from
    # discounting the best customers.
    sure_thing_damping = 1.0 / (1.0 + 0.06 * max(0.0, frequency - 3.0))

    treated_lift = base * persuadability * responsiveness * depth_multiplier * sure_thing_damping

    # NEGATIVE UPLIFT is real and must be representable. Two documented cases:
    #  * A promotion-resistant customer (never responds) finds contact a cost.
    #  * A high-return customer redeems and returns, which loses money.
    penalty = 0.0
    if promo_response < 0.05 and action != ActionType.REMINDER:
        penalty += 0.025
    if return_ratio > 0.25:
        penalty += 0.015 * (return_ratio / 0.25)

    control_response = max(0.0, (1.0 - churn_probability) * 0.5)
    treated_response = max(0.0, min(0.999, control_response + treated_lift - penalty))
    uplift = treated_response - control_response

    return round(treated_response, 5), round(control_response, 5), round(uplift, 5)


async def ensure_deterministic_version(db: AsyncSession, tenant_id: int) -> int:
    """Register the deterministic estimator as a model version, so uplift
    predictions always reference a version like churn predictions do."""
    row = (await db.execute(
        text("""SELECT id FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = 'uplift' AND version_label = :v"""),
        {"t": tenant_id, "v": DETERMINISTIC_VERSION},
    )).fetchone()
    if row:
        return int(row[0])

    from app.services.flywheel import features as feature_service
    import json
    row = (await db.execute(
        text("""INSERT INTO flywheel_model_versions
                   (tenant_id, model_kind, algorithm, version_label, random_seed,
                    feature_window_days, outcome_window_days, feature_list,
                    metrics, is_active, notes)
                VALUES (:t, 'uplift', 'rule_based', :v, 42, :fw, :ow,
                        CAST(:fl AS JSONB), '{}'::jsonb, TRUE,
                        'Deterministic uplift estimator: inverted-U persuadability in risk, '
                        'past promo-response weighting, sqrt discount-depth response. '
                        'Superseded by the T-learner when one is trained.')
                RETURNING id"""),
        {"t": tenant_id, "v": DETERMINISTIC_VERSION,
         "fw": feature_service.FEATURE_WINDOW_DAYS,
         "ow": feature_service.OUTCOME_WINDOW_DAYS,
         "fl": json.dumps(feature_service.FEATURE_NAMES)},
    )).fetchone()
    return int(row[0])


_T_LEARNER_CACHE: Dict[str, Any] = {}


def _load_t_learner(path: str) -> Optional[Dict[str, Any]]:
    """Load a fitted T-learner ({'treatment': est, 'control': est}). Degrades to
    None on any failure, exactly like the churn artifact loader."""
    if path in _T_LEARNER_CACHE:
        return _T_LEARNER_CACHE[path]
    try:
        import os
        if not os.path.exists(path):
            _T_LEARNER_CACHE[path] = None
            return None
        import joblib
        bundle = joblib.load(path)
        if not (isinstance(bundle, dict) and "treatment" in bundle and "control" in bundle):
            logger.warning("flywheel.uplift artifact at %s is not a T-learner bundle", path)
            bundle = None
        _T_LEARNER_CACHE[path] = bundle
        return bundle
    except Exception as exc:
        logger.warning("flywheel.uplift could not load %s (%s) — using deterministic tier", path, exc)
        _T_LEARNER_CACHE[path] = None
        return None


def _t_learner_predict(bundle: Dict[str, Any],
                       features: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    """Score both arms of a T-learner and difference them."""
    try:
        from app.services.flywheel import features as feature_service
        vector = [[float(features.get(n) or 0) for n in feature_service.FEATURE_NAMES]]
        treated = float(bundle["treatment"].predict_proba(vector)[0][1])
        control = float(bundle["control"].predict_proba(vector)[0][1])
        return round(treated, 5), round(control, 5), round(treated - control, 5)
    except Exception as exc:
        logger.warning("flywheel.uplift T-learner scoring failed (%s)", exc)
        return None


async def estimate_for_customer(
    db: AsyncSession, *, tenant_id: int, customer_id: int, action: ActionType,
    churn_probability: float, features: Dict[str, Any], discount_pct: float = 0.0,
    as_of: Optional[date] = None, persist: bool = False,
    model_version_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Uplift for one (customer, action), from the T-learner if available."""
    as_of = as_of or date.today()

    model = None
    if model_version_id is None:
        row = (await db.execute(
            text("""SELECT id, artifact_path FROM flywheel_model_versions
                     WHERE tenant_id = :t AND model_kind = 'uplift' AND is_active = TRUE
                     ORDER BY (algorithm <> 'rule_based') DESC, trained_at DESC NULLS LAST
                     LIMIT 1"""),
            {"t": tenant_id},
        )).fetchone()
        if row:
            model_version_id, artifact_path = int(row[0]), row[1]
            model = _load_t_learner(artifact_path) if artifact_path else None
        else:
            model_version_id = await ensure_deterministic_version(db, tenant_id)

    scored = _t_learner_predict(model, features) if model else None
    tier = "t_learner" if scored else "deterministic"
    if scored is None:
        scored = deterministic_uplift(
            action=action, churn_probability=churn_probability,
            features=features, discount_pct=discount_pct,
        )
    treated, control, uplift = scored

    if persist:
        await db.execute(
            text("""INSERT INTO flywheel_offer_response_predictions
                       (tenant_id, customer_id, model_version_id, action_type, as_of_date,
                        treated_response, control_response, uplift)
                    VALUES (:t, :c, :m, :a, :d, :tr, :cr, :u)
                    ON CONFLICT (tenant_id, customer_id, action_type, as_of_date, model_version_id)
                    DO UPDATE SET treated_response = EXCLUDED.treated_response,
                                  control_response = EXCLUDED.control_response,
                                  uplift           = EXCLUDED.uplift"""),
            {"t": tenant_id, "c": customer_id, "m": model_version_id,
             "a": action.value, "d": as_of, "tr": treated, "cr": control, "u": uplift},
        )

    return {
        "action_type": action.value,
        "treated_response": treated,
        "control_response": control,
        "uplift": uplift,
        "tier": tier,
        "model_version_id": model_version_id,
    }


def qini_curve(scores: List[float], outcomes: List[int],
               treated_flags: List[int], bins: int = 10) -> Dict[str, Any]:
    """Qini curve + coefficient — the CORRECT way to judge an uplift model.

    At each decile of the uplift ranking:
        qini(k) = responders_treated(k) − responders_control(k) × N_t(k)/N_c(k)

    The scaling term is what makes this valid when the arms are unequal sizes:
    without it, a larger treatment arm looks better regardless of model quality.

    The coefficient is the area between the model curve and the random line —
    positive means the ranking has real information, ~0 means it does not, and
    NEGATIVE means the model is actively anti-informative (worse than random,
    which is a finding worth reporting rather than hiding).
    """
    if not scores or len(scores) != len(outcomes) != len(treated_flags):
        return {"points": [], "qini_coefficient": 0.0, "n": 0}

    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    n = len(order)
    points: List[Dict[str, float]] = [{"fraction": 0.0, "qini": 0.0, "random": 0.0}]

    total_treated = sum(treated_flags) or 1
    total_control = (n - sum(treated_flags)) or 1
    total_resp_t = sum(o for o, t in zip(outcomes, treated_flags) if t)
    total_resp_c = sum(o for o, t in zip(outcomes, treated_flags) if not t)
    overall_qini = total_resp_t - total_resp_c * (total_treated / total_control)

    for b in range(1, bins + 1):
        cutoff = int(n * b / bins)
        subset = order[:cutoff]
        n_t = sum(treated_flags[i] for i in subset) or 1
        n_c = (len(subset) - sum(treated_flags[i] for i in subset)) or 1
        resp_t = sum(outcomes[i] for i in subset if treated_flags[i])
        resp_c = sum(outcomes[i] for i in subset if not treated_flags[i])
        qini = resp_t - resp_c * (n_t / n_c)
        fraction = b / bins
        points.append({
            "fraction": round(fraction, 4),
            "qini": round(qini, 4),
            "random": round(overall_qini * fraction, 4),
        })

    # Trapezoidal area between the model curve and the random diagonal.
    area = 0.0
    for i in range(1, len(points)):
        width = points[i]["fraction"] - points[i - 1]["fraction"]
        model_avg = (points[i]["qini"] + points[i - 1]["qini"]) / 2
        random_avg = (points[i]["random"] + points[i - 1]["random"]) / 2
        area += (model_avg - random_avg) * width

    return {
        "points": points,
        "qini_coefficient": round(area, 5),
        "n": n,
        "interpretation": (
            "Positive = the uplift ranking carries real information. "
            "Near zero = no better than random targeting. "
            "Negative = anti-informative; targeting the top decile would be "
            "worse than targeting at random."
        ),
    }
