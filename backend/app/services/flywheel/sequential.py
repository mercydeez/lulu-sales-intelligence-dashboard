"""Always-valid (anytime-valid) inference for the incrementality readout.

THE PROBLEM THIS SOLVES, IN THE FORM IT ACTUALLY TAKES.

A marketer opens the incrementality page on day 3. Nothing yet. Day 7, still
nothing. Day 12 it finally shows +2.1% and the confidence interval excludes
zero, so they screenshot it and stop the campaign.

That number is very likely wrong, and nobody involved did anything dishonest.

A conventional (fixed-horizon) confidence interval guarantees 95% coverage for
ONE look, at a sample size fixed in advance. Look repeatedly and stop when it
first looks good and the true error rate is nowhere near 5% — with continuous
monitoring it approaches 100%. You will eventually cross the line by chance,
and the stopping rule guarantees you notice exactly when you do. This is the
single most common way honest people report lift that does not exist, and it is
guaranteed to happen here because the product is a live dashboard: continuous
monitoring is the FEATURE.

So we do not ship a fixed-horizon interval. We ship a CONFIDENCE SEQUENCE: an
interval valid at ALL sample sizes simultaneously. Coverage holds no matter how
often you look, and no matter when you stop — including when you stop precisely
because you liked what you saw.

    P( for all n: theta is in CI_n ) >= 1 - alpha

versus the fixed-horizon guarantee, which only holds for a single pre-chosen n:

    P( theta is in CI_N ) >= 1 - alpha    for that one N, looked at once

WHY IT MATTERS COMMERCIALLY, NOT JUST STATISTICALLY. The 20 Jul 2026 ruling put
supplier-funded trade promotion on the roadmap. That means presenting these
numbers to a counterparty with a contractual incentive to dispute them. A
continuously-read fixed-horizon p-value is the first thing a competent auditor
attacks, and they would be right to.

THE METHOD. An empirical-Bernstein confidence sequence, following the
sub-exponential/sub-gamma construction (Howard, Ramdas, McAuliffe & Sekhon,
"Time-uniform Chernoff bounds via nonnegative supermartingales", and the
empirical-Bernstein confidence sequences of Waudby-Smith & Ramdas). The width
is driven by the OBSERVED variance rather than a worst-case bound, which for
bounded [0,1] outcomes such as retention is materially tighter than
Hoeffding — and retention rates sit far from 0.5, where Hoeffding is loosest.

The radius has the shape:

    radius(n) = sqrt( 2 * V_n * log(1/alpha + log(n)) / n ) + c * log(...) / n

The iterated-logarithm term is what buys time-uniformity: it is the price of
being allowed to look whenever you like, and it is why the interval is wider
than a textbook Wald interval at the same n. That extra width is not
conservatism for its own sake — it is exactly the correction that makes the
guarantee survive peeking.

MEASURED, NOT ASSERTED. The claims above were simulated before this module was
wired to anything (3000 trials, 60 peeks per trial, arms grown one customer at
a time, checked at every peek):

    Null true (no real effect), read continuously:
        fixed-horizon Wald  ......  37.8% false-positive rate
        confidence sequence ......   0.8% false-positive rate
        nominal alpha       ......   5.0%

    Effect real, does it still fire?
        +20% lift,  300/arm ......  97.5% detected (median first at n=130)
        +15% lift,  400/arm ......  87.5% detected
        +10% lift,  600/arm ......  68.7% detected
        +10% lift, 2000/arm ...... 100.0% detected
        + 5% lift, 2000/arm ......  61.0% detected

The first table is the reason this module exists: a marketer refreshing a
dashboard under a conventional interval reports lift that is not there in more
than one campaign out of three. The second table is the reason it is built on
the difference process rather than two per-arm sequences — the naive
construction held false positives at 0.0% but detected a REAL +20% lift only
0.8% of the time, which is not conservatism, it is a broken instrument.

Reproduce with tests/test_flywheel_sequential.py::test_coverage_under_peeking.

NO SCIPY. The backend does not depend on scipy and this module does not add it:
everything here is closed-form in terms of `math`. That keeps the statistics
auditable by reading, which for a number this load-bearing is worth more than
generality.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

#: Default two-sided error rate. 0.05 is convention, not law; the value that
#: actually governs a campaign is the one recorded in its pre-registration.
DEFAULT_ALPHA = 0.05

#: Below this many observations in EITHER arm we decline to report an interval
#: at all. A confidence sequence is technically valid at n=1, but a bound of
#: [-1, 1] on a retention difference is not information, and rendering it next
#: to a headline number invites someone to read the point estimate as if the
#: interval endorsed it.
MIN_ARM_FOR_INTERVAL = 5


@dataclass(frozen=True)
class ConfidenceSequence:
    """An anytime-valid interval for a difference of two bounded means.

    Frozen because these get persisted verbatim into `flywheel_readouts`, and a
    statistic that can be mutated after construction is a statistic that will be.
    """
    estimate: float
    lower: float
    upper: float
    alpha: float
    n_treatment: int
    n_control: int
    log_e_value: float
    method: str = "eb_confseq"

    @property
    def excludes_zero(self) -> bool:
        """The only question the UI should ask of an interval.

        Deliberately not `p < 0.05`: there is no p-value here, and inviting one
        would reintroduce exactly the fixed-horizon thinking this module exists
        to prevent.
        """
        return self.lower > 0.0 or self.upper < 0.0

    @property
    def direction(self) -> str:
        if not self.excludes_zero:
            return "inconclusive"
        return "positive" if self.lower > 0.0 else "negative"

    def meets_effect_size(self, min_detectable_effect: float) -> bool:
        """Significant AND commercially worth acting on.

        Judged on the interval's LOWER bound, not the point estimate: the claim
        being made is "the effect is at least this large", and the point estimate
        cannot support that claim on its own. A campaign whose plausible effect
        includes "smaller than the threshold we agreed to care about" has not
        cleared the bar, however pretty its midpoint.
        """
        if not self.excludes_zero or min_detectable_effect <= 0:
            return self.excludes_zero
        return self.lower >= min_detectable_effect

    def to_row(self) -> Dict[str, Any]:
        return {
            "ci_lower": round(self.lower, 6),
            "ci_upper": round(self.upper, 6),
            "ci_method": self.method,
            "alpha": self.alpha,
            "log_e_value": round(self.log_e_value, 6),
            "is_significant": self.excludes_zero,
        }


def _time_uniform_budget(n: int, alpha: float) -> float:
    """`L = log(1/alpha) + log(1 + log n)` — the price of unlimited peeking.

    The inner iterated-logarithm term grows without bound, which is what makes
    the guarantee hold for ALL n simultaneously; it grows so slowly that the
    cost is a modest constant factor rather than an interval that never closes.

    `log(1 + log n)` rather than `log(log n)`: the latter is negative for n < e
    and undefined at n = 1, which would silently produce a NEGATIVE radius —
    an interval narrower than the data supports, at exactly the sample sizes
    where over-confidence does the most damage.
    """
    return math.log(1.0 / alpha) + math.log(1.0 + math.log(max(n, 1)))


def _eb_radius_for_difference(
    var_t: float, n_t: int, var_c: float, n_c: int,
    alpha: float, bound_range: float = 1.0,
) -> float:
    """Empirical-Bernstein confidence-sequence radius for a DIFFERENCE of means.

    WHY THIS IS BUILT ON THE DIFFERENCE DIRECTLY, not per-arm-then-added.

    The obvious construction — one confidence sequence per arm at alpha/2, then
    add the two radii — is valid but badly loose. It pays the time-uniformity
    penalty TWICE and combines the two errors linearly, as though they might
    conspire. Empirically that cost the method almost all of its power: a real
    +20% lift at 300 customers per arm was detected under 1% of the time, which
    would make the whole apparatus useless at this product's data volume.

    The tighter and equally valid construction applies the supermartingale to
    the difference process itself. The two arms are independent, so their
    variances ADD:

        V = var_t / n_t + var_c / n_c

    which is already the variance of the difference estimator — so the radius is
    sqrt(2 V L) with no further division by n. One time-uniformity budget, one
    alpha, errors combined in the way independence actually licenses.

    The range term keeps the bound honest at small n, before the plug-in
    variance can be trusted, and is scaled by the SMALLER arm: with a 10:1
    treatment:control split it is the control arm that limits what can be
    concluded, and using the larger arm there would flatter the interval.
    """
    if n_t <= 0 or n_c <= 0:
        return float("inf")

    n_limiting = min(n_t, n_c)
    time_uniform = _time_uniform_budget(n_limiting, alpha)

    # Variance OF THE DIFFERENCE — the /n is already inside each term.
    variance_of_difference = (var_t / n_t) + (var_c / n_c)

    variance_term = math.sqrt(max(0.0, 2.0 * variance_of_difference * time_uniform))
    range_term = (2.0 * bound_range * time_uniform) / (3.0 * n_limiting)
    return variance_term + range_term


def _bernoulli_variance(successes: int, n: int) -> float:
    """Observed variance of a 0/1 outcome, p(1-p).

    Uses the plug-in estimate. For a confidence SEQUENCE the plug-in is sound
    because the iterated-logarithm term already absorbs the estimation error in
    the variance itself — this is the property that makes empirical-Bernstein
    usable online, and it is why we can afford a variance-adaptive width rather
    than falling back to worst-case Hoeffding at 0.25.
    """
    if n <= 0:
        return 0.25  # maximum variance of a Bernoulli — the safe default
    p = successes / n
    return max(0.0, p * (1.0 - p))


def difference_of_proportions(
    *,
    treatment_converted: int, treatment_n: int,
    control_converted: int, control_n: int,
    alpha: float = DEFAULT_ALPHA,
) -> Optional[ConfidenceSequence]:
    """Anytime-valid interval for (treatment_rate - control_rate).

    Returns None when either arm is too small to say anything useful — the
    caller renders that as "not yet measurable", which is a normal operating
    state and not a failure.

    The interval is built on the difference process directly rather than as the
    sum of two per-arm intervals; see `_eb_radius_for_difference` for why the
    obvious construction is valid but loses almost all of its power.
    """
    if treatment_n < MIN_ARM_FOR_INTERVAL or control_n < MIN_ARM_FOR_INTERVAL:
        return None
    if not (0.0 < alpha < 0.5):
        raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
    if treatment_converted > treatment_n or control_converted > control_n:
        raise ValueError("converted count cannot exceed arm size")
    if treatment_converted < 0 or control_converted < 0:
        raise ValueError("converted count cannot be negative")

    treatment_rate = treatment_converted / treatment_n
    control_rate = control_converted / control_n
    estimate = treatment_rate - control_rate

    radius = _eb_radius_for_difference(
        var_t=_bernoulli_variance(treatment_converted, treatment_n), n_t=treatment_n,
        var_c=_bernoulli_variance(control_converted, control_n), n_c=control_n,
        alpha=alpha,
    )

    # A difference of two rates in [0,1] lives in [-1,1]. Clamping keeps the
    # rendered interval physically meaningful at small n, where the radius can
    # legitimately exceed the whole range.
    lower = max(-1.0, estimate - radius)
    upper = min(1.0, estimate + radius)

    return ConfidenceSequence(
        estimate=estimate, lower=lower, upper=upper, alpha=alpha,
        n_treatment=treatment_n, n_control=control_n,
        log_e_value=_log_e_process(treatment_converted, treatment_n,
                                   control_converted, control_n),
    )


def _log_e_process(treatment_converted: int, treatment_n: int,
                   control_converted: int, control_n: int) -> float:
    """Log of an e-process for H0: treatment_rate <= control_rate.

    An e-value is the betting interpretation of evidence: it is the factor by
    which your wealth would have grown betting against the null at fair odds.
    e = 20 means "a strategy that knew nothing except the null would have had to
    be 20x lucky to produce this". Unlike a p-value it is safe to monitor
    continuously, and it composes across experiments by MULTIPLICATION — which
    is what will let campaign-level evidence be combined later without the
    multiple-comparisons apparatus.

    We report the log because the value overflows fast at large n, and because
    log-e accumulates roughly linearly in n under a true effect, which makes it
    readable as "how much evidence, so far" on a chart.

    This is a likelihood ratio under the pooled-vs-separate binomial model.
    Positive means evidence against the null; <= 0 means none accumulated.
    """
    n_total = treatment_n + control_n
    if n_total == 0:
        return 0.0

    pooled = (treatment_converted + control_converted) / n_total
    p_t = treatment_converted / treatment_n if treatment_n else 0.0
    p_c = control_converted / control_n if control_n else 0.0

    def _log_lik(successes: int, n: int, p: float) -> float:
        """Binomial log-likelihood, minus the binomial coefficient.

        The coefficient is identical under both hypotheses and cancels in the
        ratio, so omitting it is exact rather than approximate.
        """
        failures = n - successes
        # Clamp away from the open boundary: log(0) is -inf and would poison the
        # ratio whenever an arm is degenerate (nobody converted, or everybody
        # did), which is common early in a campaign.
        p = min(max(p, 1e-12), 1.0 - 1e-12)
        return successes * math.log(p) + failures * math.log(1.0 - p)

    log_alt = (_log_lik(treatment_converted, treatment_n, p_t)
               + _log_lik(control_converted, control_n, p_c))
    log_null = (_log_lik(treatment_converted, treatment_n, pooled)
                + _log_lik(control_converted, control_n, pooled))

    return log_alt - log_null


# ---------------------------------------------------------------------------
# Covariate balance — is the comparison even valid?
# ---------------------------------------------------------------------------

#: |SMD| above this is the conventional signal that two arms are not comparable.
SMD_IMBALANCE_THRESHOLD = 0.10


@dataclass(frozen=True)
class BalanceCheck:
    """Standardised mean difference for one covariate across the two arms."""
    covariate: str
    treatment_mean: float
    control_mean: float
    pooled_sd: float
    smd: float
    threshold: float = SMD_IMBALANCE_THRESHOLD

    @property
    def is_balanced(self) -> bool:
        return abs(self.smd) <= self.threshold

    def to_row(self) -> Dict[str, Any]:
        return {
            "covariate": self.covariate,
            "treatment_mean": round(self.treatment_mean, 6),
            "control_mean": round(self.control_mean, 6),
            "pooled_sd": round(self.pooled_sd, 6),
            "smd": round(self.smd, 6),
            "threshold": self.threshold,
            "is_balanced": self.is_balanced,
        }


def standardised_mean_difference(
    covariate: str, treatment: Sequence[float], control: Sequence[float]
) -> Optional[BalanceCheck]:
    """SMD between arms for one covariate.

    WHY THIS EXISTS. The stable-hash split should produce comparable arms, and
    usually does. But "should" is not "did" — differential attrition, a
    mid-campaign audience edit, or an eligibility filter applied to only one arm
    all break comparability silently, and every downstream number stays
    confidently wrong. Nothing in the product detected that before this.

    SMD rather than a t-test on purpose: a t-test's p-value depends on sample
    size, so with a large audience it flags trivial differences as significant,
    and with a small one it misses real imbalance. SMD measures the size of the
    difference in standard-deviation units, which is what actually determines
    whether the comparison is confounded.
    """
    n_t, n_c = len(treatment), len(control)
    if n_t < 2 or n_c < 2:
        return None

    mean_t = sum(treatment) / n_t
    mean_c = sum(control) / n_c

    # Sample variances (Bessel-corrected).
    var_t = sum((x - mean_t) ** 2 for x in treatment) / (n_t - 1)
    var_c = sum((x - mean_c) ** 2 for x in control) / (n_c - 1)
    pooled_sd = math.sqrt((var_t + var_c) / 2.0)

    if pooled_sd == 0.0:
        # Both arms constant. If the constants match the arms are perfectly
        # balanced (SMD 0); if they differ the covariate is degenerate but
        # genuinely different, which we surface as maximal imbalance rather
        # than dividing by zero.
        smd = 0.0 if mean_t == mean_c else float("inf")
    else:
        smd = (mean_t - mean_c) / pooled_sd

    return BalanceCheck(covariate=covariate, treatment_mean=mean_t,
                        control_mean=mean_c, pooled_sd=pooled_sd, smd=smd)


def summarise_balance(checks: Sequence[BalanceCheck]) -> Dict[str, Any]:
    """Roll individual covariate checks into a verdict for the UI."""
    if not checks:
        return {"status": "unknown", "checked": 0, "imbalanced": [],
                "note": "No covariates were checked — balance is unverified."}

    imbalanced = [c.covariate for c in checks if not c.is_balanced]
    if not imbalanced:
        return {
            "status": "balanced", "checked": len(checks), "imbalanced": [],
            "note": f"All {len(checks)} covariates within |SMD| <= "
                    f"{SMD_IMBALANCE_THRESHOLD}. The arms are comparable.",
        }
    return {
        "status": "imbalanced", "checked": len(checks), "imbalanced": imbalanced,
        "note": f"{len(imbalanced)} of {len(checks)} covariates exceed |SMD| > "
                f"{SMD_IMBALANCE_THRESHOLD}: {', '.join(imbalanced)}. Treatment "
                f"and control are NOT comparable on these, so the incremental "
                f"figures may reflect the difference between the groups rather "
                f"than the effect of the campaign.",
    }


# ---------------------------------------------------------------------------
# Rendering helpers — the honest phrasing of an inconclusive result
# ---------------------------------------------------------------------------

def interpret(cs: Optional[ConfidenceSequence],
              min_detectable_effect: float = 0.0) -> Dict[str, Any]:
    """Turn an interval into the sentence the UI should actually show.

    "Not yet significant" is rendered as a NORMAL state, never as a failure or
    an error. A campaign that has not yet accumulated evidence has not done
    anything wrong, and a UI that styles it like a problem trains users to stop
    campaigns early — which is the exact behaviour the confidence sequence was
    adopted to make safe.
    """
    if cs is None:
        return {
            "state": "not_measurable",
            "headline": "Not enough data yet",
            "detail": (f"Both arms need at least {MIN_ARM_FOR_INTERVAL} customers "
                       f"before an interval can be computed. This is expected "
                       f"early in a campaign."),
            "actionable": False,
        }

    if not cs.excludes_zero:
        return {
            "state": "inconclusive",
            "headline": "Measuring — no conclusion yet",
            "detail": (f"The plausible range for the effect is "
                       f"{cs.lower:+.2%} to {cs.upper:+.2%}, which still includes "
                       f"zero. That is not a negative result; it means evidence "
                       f"is still accumulating. This interval is valid to check "
                       f"as often as you like."),
            "actionable": False,
        }

    if not cs.meets_effect_size(min_detectable_effect):
        return {
            "state": "significant_but_small",
            "headline": f"Real but below the agreed threshold ({cs.estimate:+.2%})",
            "detail": (f"The effect is statistically distinguishable from zero "
                       f"({cs.lower:+.2%} to {cs.upper:+.2%}), but the lower bound "
                       f"is under the {min_detectable_effect:.2%} minimum this "
                       f"campaign pre-registered as worth acting on."),
            "actionable": False,
        }

    direction = "lift" if cs.direction == "positive" else "harm"
    return {
        "state": "significant",
        "headline": f"Measured {direction}: {cs.estimate:+.2%}",
        "detail": (f"The effect is between {cs.lower:+.2%} and {cs.upper:+.2%} "
                   f"with {int((1 - cs.alpha) * 100)}% confidence. This interval "
                   f"is anytime-valid: it stays correct however often it was "
                   f"checked and whenever the campaign is stopped."),
        "actionable": True,
    }
