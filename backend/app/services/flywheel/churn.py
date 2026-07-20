"""Stage 2 — churn scoring, with a deterministic fallback that always works.

TWO-TIER BY DESIGN (§8.1):

  1. A trained, CALIBRATED artifact (LightGBM / sequence / ensemble) when one is
     registered and loadable.
  2. A deterministic RULE-BASED score otherwise.

Tier 2 is not a stub — it is a requirement. The system must never hard-depend on
a trained model: a fresh clone with no artifacts, a container without the model
volume mounted, or a corrupted pickle must all still produce a usable, explained
score rather than a 500. The rule-based scorer is transparent, monotone in the
right directions, and produces the same reason codes the trained model does, so
the UI is identical either way.

CALIBRATION MATTERS MORE THAN RANKING HERE. The optimizer multiplies churn
probability by customer value to get expected retained value — so a model that
ranks perfectly but is systematically overconfident will systematically overspend.
That is why the training script fits isotonic calibration and why Brier score is
tracked alongside PR-AUC.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import features as feature_service

logger = logging.getLogger(__name__)

RULE_BASED_VERSION = "rule-v2"

#: Temperature for the rule-tier logit (standard temperature scaling).
#:
#: WHY THIS EXISTS. The rule scorer sums several independent domain signals —
#: overdue, low frequency, declining spend, erratic cadence, narrow category,
#: high returns. A genuinely lapsing customer trips most of them at once, and
#: the raw sum reached ±6 logits, which saturates the sigmoid: measured on 300
#: live customers, 195 landed in the bottom two deciles and 48 in the top, with
#: only 27 across the whole 30–80% middle.
#:
#: That distribution is not just ugly, it is FUNCTIONALLY BROKEN for this
#: product. Uplift peaks at p = 0.5 and vanishes at both extremes, so a bimodal
#: risk score starves the persuadable middle the campaign exists to reach — the
#: optimizer correctly refuses almost everyone and the engine does nothing.
#:
#: Hand-set weights carry no claim to calibration, so dividing the summed logit
#: by a temperature is honest rather than a fudge: it preserves every sign and
#: every RANKING (a monotone transform) while pulling the probabilities back
#: toward plausible base rates. Ranking is what the audience uses; calibration
#: is what the optimizer multiplies by. This fixes the second without touching
#: the first.
RULE_LOGIT_TEMPERATURE = 2.4

#: Base-rate anchor: most customers do not churn. sigmoid(-1.4) ≈ 0.20, which
#: is close to the 18.3% base rate measured on the live synthetic population.
BASE_LOGIT = -1.4

#: Risk bands. Chosen so "critical" is genuinely rare — a band that contains
#: half the population tells an operator nothing.
#:
#: Thresholds must partition the ACTUAL score distribution, not a theoretical
#: 0–1 range. After temperature scaling the rule tier tops out near 0.80, so the
#: old 0.75 cut left `critical` permanently EMPTY — a band nobody can ever enter
#: is worse than no band, because an operator reads "0 critical" as good news
#: rather than as a broken scale. These cuts are set against the measured
#: distribution and should be revisited whenever the scorer is recalibrated.
BAND_THRESHOLDS: List[Tuple[float, str]] = [
    (0.65, "critical"), (0.45, "high"), (0.28, "medium"), (0.0, "low"),
]


def band_for(probability: float) -> str:
    for threshold, name in BAND_THRESHOLDS:
        if probability >= threshold:
            return name
    return "low"


# ---------------------------------------------------------------------------
# Tier 2 — the deterministic rule-based scorer
# ---------------------------------------------------------------------------

def rule_based_score(features: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
    """A transparent logistic scorer over the engineered features.

    The weights are hand-set from retail domain reasoning, not fitted — that is
    the point: this tier must be explainable line by line and must not silently
    change when data drifts. Returns (probability, reason_codes).

    Signs are the domain claims, stated explicitly:
      recency ↑        → churn ↑   (the single strongest classical signal)
      frequency ↑      → churn ↓
      spend drift ↓    → churn ↑   (spending less than they used to)
      gap volatility ↑ → churn ↑   (erratic buyers are unpredictable buyers)
      diversity ↑      → churn ↓   (more categories = more reasons to return)
      returns ↑        → churn ↑   (dissatisfaction)
      tenure ↑         → churn ↓   (habit)
    """
    def f(name: str, default: float = 0.0) -> float:
        value = features.get(name, default)
        try:
            return float(value if value is not None else default)
        except (TypeError, ValueError):
            return default

    recency = f("recency_days")
    frequency = f("frequency_90d")
    drift = f("spend_drift_ratio", 1.0)
    gap = f("interpurchase_gap_days")
    volatility = f("gap_volatility")
    diversity = f("category_diversity")
    return_ratio = f("return_ratio")
    tenure = f("tenure_days")

    reasons: List[Dict[str, Any]] = []
    logit = BASE_LOGIT

    # Recency, normalised against the customer's OWN cadence. Being 30 days
    # quiet means nothing for a quarterly shopper and everything for a weekly
    # one — an absolute threshold would mislabel both.
    expected_gap = max(gap, 7.0)
    overdue_ratio = recency / expected_gap
    if overdue_ratio > 1.0:
        contribution = min(2.6, 1.25 * math.log1p(overdue_ratio - 1.0) * 2.2)
        logit += contribution
        if overdue_ratio >= 2.0:
            reasons.append({
                "code": "OVERDUE_VS_OWN_CADENCE",
                "detail": f"{int(recency)}d since last purchase vs a typical "
                          f"{int(expected_gap)}d gap ({overdue_ratio:.1f}× overdue)",
                "impact": round(contribution, 3),
            })

    if frequency <= 1:
        logit += 0.75
        reasons.append({"code": "VERY_LOW_FREQUENCY",
                        "detail": f"{int(frequency)} purchase(s) in 90 days",
                        "impact": 0.75})
    else:
        relief = min(1.1, 0.24 * math.log1p(frequency))
        logit -= relief

    if drift < 0.75:
        contribution = min(1.5, (0.75 - drift) * 2.6)
        logit += contribution
        reasons.append({
            "code": "SPEND_DECLINING",
            "detail": f"Recent 90d spend is {drift:.0%} of the prior 90d",
            "impact": round(contribution, 3),
        })
    elif drift > 1.25:
        logit -= 0.45

    if volatility > expected_gap * 0.85 and volatility > 5:
        logit += 0.42
        reasons.append({"code": "ERRATIC_CADENCE",
                        "detail": f"Purchase-gap volatility {volatility:.1f}d",
                        "impact": 0.42})

    if diversity >= 4:
        logit -= 0.38
    elif diversity <= 1 and frequency > 0:
        logit += 0.30
        reasons.append({"code": "SINGLE_CATEGORY_ONLY",
                        "detail": "Shops one category — narrow attachment",
                        "impact": 0.30})

    if return_ratio > 0.20:
        contribution = min(0.85, return_ratio * 1.9)
        logit += contribution
        reasons.append({"code": "HIGH_RETURN_RATIO",
                        "detail": f"{return_ratio:.0%} of purchases returned",
                        "impact": round(contribution, 3)})

    if tenure > 540:
        logit -= 0.30
    elif tenure < 60:
        logit += 0.22  # new customers have not formed a habit yet

    # Temperature-scale the DEVIATION from the base rate, not the base itself,
    # so the anchor stays put and only the spread is tempered. Monotone, so the
    # ranking the audience builder relies on is unchanged.
    tempered = BASE_LOGIT + (logit - BASE_LOGIT) / RULE_LOGIT_TEMPERATURE
    probability = 1.0 / (1.0 + math.exp(-tempered))
    probability = min(0.98, max(0.02, probability))

    if not reasons:
        reasons.append({"code": "STABLE_BEHAVIOUR",
                        "detail": "No deterioration detected across the feature window",
                        "impact": 0.0})

    return probability, reasons


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

async def ensure_rule_based_version(db: AsyncSession, tenant_id: int) -> int:
    """Register (once) the rule-based scorer as a real model version.

    It gets a row like any other model so that every prediction — including
    fallback predictions — references a version, and the Decision Trace can
    always answer "which model said this?". `artifact_path` is NULL and
    `algorithm='rule_based'`, which the migration's CHECK constraint permits
    without a `trained_at`.
    """
    row = (await db.execute(
        text("""SELECT id FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = 'churn'
                   AND version_label = :v"""),
        {"t": tenant_id, "v": RULE_BASED_VERSION},
    )).fetchone()
    if row:
        return int(row[0])

    row = (await db.execute(
        text("""INSERT INTO flywheel_model_versions
                   (tenant_id, model_kind, algorithm, version_label, random_seed,
                    feature_window_days, outcome_window_days, feature_list,
                    metrics, is_active, notes)
                VALUES (:t, 'churn', 'rule_based', :v, 42, :fw, :ow,
                        CAST(:fl AS JSONB), '{}'::jsonb, TRUE,
                        'Deterministic domain-rule scorer. Always available; '
                        'guarantees the system never hard-depends on a trained artifact.')
                RETURNING id"""),
        {"t": tenant_id, "v": RULE_BASED_VERSION,
         "fw": feature_service.FEATURE_WINDOW_DAYS,
         "ow": feature_service.OUTCOME_WINDOW_DAYS,
         "fl": __import__("json").dumps(feature_service.FEATURE_NAMES)},
    )).fetchone()
    return int(row[0])


async def active_model(db: AsyncSession, tenant_id: int,
                       model_kind: str = "churn") -> Optional[Dict[str, Any]]:
    """The active model for a kind, preferring a TRAINED artifact over the rule
    tier when both are marked active."""
    row = (await db.execute(
        text("""SELECT id, algorithm, version_label, artifact_path, metrics
                  FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = :k AND is_active = TRUE
                 ORDER BY (algorithm <> 'rule_based') DESC, trained_at DESC NULLS LAST
                 LIMIT 1"""),
        {"t": tenant_id, "k": model_kind},
    )).fetchone()
    if not row:
        return None
    return {"id": int(row[0]), "algorithm": row[1], "version_label": row[2],
            "artifact_path": row[3], "metrics": row[4] or {}}


# ---------------------------------------------------------------------------
# Tier 1 — trained artifact, loaded lazily and cached per process
# ---------------------------------------------------------------------------

_ARTIFACT_CACHE: Dict[str, Any] = {}


def _load_artifact(path: str) -> Optional[Any]:
    """Load a trained model, returning None on ANY failure.

    Deliberately broad: a missing file, a joblib version mismatch, a truncated
    volume mount and a corrupted pickle must all degrade to the rule tier rather
    than take down scoring. The failure is logged once per path, not per call.
    """
    if path in _ARTIFACT_CACHE:
        return _ARTIFACT_CACHE[path]
    try:
        import os
        if not os.path.exists(path):
            logger.warning("flywheel.churn artifact missing at %s — using rule tier", path)
            _ARTIFACT_CACHE[path] = None
            return None
        import joblib
        model = joblib.load(path)
        _ARTIFACT_CACHE[path] = model
        logger.info("flywheel.churn loaded artifact %s", path)
        return model
    except Exception as exc:
        logger.warning("flywheel.churn could not load %s (%s) — using rule tier", path, exc)
        _ARTIFACT_CACHE[path] = None
        return None


def _predict_with_artifact(model: Any, features: Dict[str, Any]) -> Optional[float]:
    """Score one customer with a trained sklearn-compatible estimator."""
    try:
        vector = [[float(features.get(name) or 0) for name in feature_service.FEATURE_NAMES]]
        if hasattr(model, "predict_proba"):
            return float(model.predict_proba(vector)[0][1])
        return float(model.predict(vector)[0])
    except Exception as exc:
        logger.warning("flywheel.churn artifact scoring failed (%s) — using rule tier", exc)
        return None


# ---------------------------------------------------------------------------
# Public scoring API
# ---------------------------------------------------------------------------

async def score_customers(
    db: AsyncSession, *, tenant_id: int, as_of: Optional[date] = None,
    customer_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Score every customer with a feature snapshot at `as_of` and persist.

    Uses the trained artifact when one loads, else the rule tier — recorded per
    run in the return value so a caller (and the UI) always knows which tier
    produced the numbers on screen.
    """
    as_of = as_of or await feature_service.latest_snapshot_date(db, tenant_id) or date.today()

    model = await active_model(db, tenant_id, "churn")
    if model is None:
        model_id = await ensure_rule_based_version(db, tenant_id)
        model = {"id": model_id, "algorithm": "rule_based",
                 "version_label": RULE_BASED_VERSION, "artifact_path": None}

    artifact = _load_artifact(model["artifact_path"]) if model.get("artifact_path") else None
    tier_used = "trained" if artifact is not None else "rule_based"

    where_customer = "AND customer_id = ANY(:cids)" if customer_ids else ""
    params: Dict[str, Any] = {"t": tenant_id, "d": as_of}
    if customer_ids:
        params["cids"] = customer_ids

    rows = (await db.execute(
        text(f"""SELECT customer_id, {', '.join(feature_service.FEATURE_NAMES)}
                   FROM flywheel_feature_snapshots
                  WHERE tenant_id = :t AND as_of_date = :d {where_customer}
                  ORDER BY customer_id"""),
        params,
    )).fetchall()

    if not rows:
        return {"scored": 0, "as_of": str(as_of), "tier": tier_used,
                "reason": "no feature snapshots — run feature generation first"}

    import json
    scored = 0
    band_counts: Dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    for row in rows:
        customer_id = int(row[0])
        feats = {name: row[i + 1] for i, name in enumerate(feature_service.FEATURE_NAMES)}

        # Reason codes always come from the transparent scorer, even when a
        # trained model supplies the probability: an operator needs a readable
        # explanation, and a raw SHAP vector is not one. When the tiers
        # disagree materially the trained probability wins but the explanation
        # is flagged as indicative.
        rule_probability, reasons = rule_based_score(feats)
        probability = rule_probability
        if artifact is not None:
            trained_probability = _predict_with_artifact(artifact, feats)
            if trained_probability is not None:
                probability = trained_probability
                if abs(trained_probability - rule_probability) > 0.25:
                    reasons = reasons + [{
                        "code": "EXPLANATION_INDICATIVE",
                        "detail": "Trained model differs materially from the rule "
                                  "baseline; drivers shown are indicative.",
                        "impact": 0.0,
                    }]

        risk_band = band_for(probability)
        band_counts[risk_band] += 1

        await db.execute(
            text("""INSERT INTO flywheel_churn_predictions
                       (tenant_id, customer_id, model_version_id, as_of_date,
                        churn_probability, risk_band, reason_codes)
                    VALUES (:t, :c, :m, :d, :p, :b, CAST(:r AS JSONB))
                    ON CONFLICT (tenant_id, customer_id, as_of_date, model_version_id)
                    DO UPDATE SET churn_probability = EXCLUDED.churn_probability,
                                  risk_band        = EXCLUDED.risk_band,
                                  reason_codes     = EXCLUDED.reason_codes"""),
            {"t": tenant_id, "c": customer_id, "m": model["id"], "d": as_of,
             "p": round(probability, 5), "b": risk_band, "r": json.dumps(reasons)},
        )
        scored += 1

    logger.info("flywheel.churn tenant=%s as_of=%s scored=%s tier=%s",
                tenant_id, as_of, scored, tier_used)
    return {
        "scored": scored,
        "as_of": str(as_of),
        "tier": tier_used,
        "model_version_id": model["id"],
        "model_version": model["version_label"],
        "algorithm": model["algorithm"],
        "risk_bands": band_counts,
    }


async def get_score(
    db: AsyncSession, *, tenant_id: int, customer_id: int,
    as_of: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """The most recent stored churn score for one customer."""
    clause = "AND as_of_date = :d" if as_of else ""
    params: Dict[str, Any] = {"t": tenant_id, "c": customer_id}
    if as_of:
        params["d"] = as_of

    row = (await db.execute(
        text(f"""SELECT p.churn_probability, p.risk_band, p.reason_codes,
                        p.as_of_date, p.model_version_id, m.version_label, m.algorithm
                   FROM flywheel_churn_predictions p
                   JOIN flywheel_model_versions m ON m.id = p.model_version_id
                  WHERE p.tenant_id = :t AND p.customer_id = :c {clause}
                  ORDER BY p.as_of_date DESC LIMIT 1"""),
        params,
    )).fetchone()
    if not row:
        return None
    return {
        "churn_probability": float(row[0]), "risk_band": row[1],
        "reason_codes": row[2] or [], "as_of": str(row[3]),
        "model_version_id": int(row[4]), "model_version": row[5], "algorithm": row[6],
    }
