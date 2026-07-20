"""Always-valid inference — the properties that make the headline number honest.

These tests exist because the incrementality readout is the single most
load-bearing number in the product and the most tempting one to get subtly
wrong. Two claims must hold simultaneously, and each is easy to satisfy alone:

  * FALSE POSITIVES stay controlled even when the interval is checked
    continuously and the campaign is stopped the moment it looks good;
  * the method still FIRES on an effect that is really there.

A method that never rejects passes the first test perfectly and is useless. The
first implementation of this module did exactly that — 0% false positives and
0.8% detection of a real +20% lift — so both directions are asserted here.
"""
from __future__ import annotations

import math
import random

import pytest

from app.services.flywheel.sequential import (
    DEFAULT_ALPHA, MIN_ARM_FOR_INTERVAL, SMD_IMBALANCE_THRESHOLD,
    difference_of_proportions, interpret, standardised_mean_difference,
    summarise_balance,
)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------

def test_returns_none_when_an_arm_is_too_small():
    """Below the floor we decline to answer rather than answer badly."""
    assert difference_of_proportions(
        treatment_converted=1, treatment_n=2,
        control_converted=0, control_n=100) is None
    assert difference_of_proportions(
        treatment_converted=40, treatment_n=100,
        control_converted=1, control_n=2) is None


def test_interval_contains_the_point_estimate():
    cs = difference_of_proportions(
        treatment_converted=40, treatment_n=100,
        control_converted=20, control_n=100)
    assert cs is not None
    assert cs.lower <= cs.estimate <= cs.upper


def test_interval_is_clamped_to_the_physical_range():
    """A difference of two rates in [0,1] cannot lie outside [-1, 1]."""
    cs = difference_of_proportions(
        treatment_converted=5, treatment_n=5,
        control_converted=0, control_n=5)
    assert cs is not None
    assert cs.lower >= -1.0 and cs.upper <= 1.0


def test_rejects_impossible_inputs():
    with pytest.raises(ValueError):
        difference_of_proportions(treatment_converted=200, treatment_n=100,
                                  control_converted=10, control_n=100)
    with pytest.raises(ValueError):
        difference_of_proportions(treatment_converted=10, treatment_n=100,
                                  control_converted=-1, control_n=100)
    with pytest.raises(ValueError):
        difference_of_proportions(treatment_converted=10, treatment_n=100,
                                  control_converted=10, control_n=100, alpha=0.9)


def test_interval_narrows_as_evidence_accumulates():
    """More data at the same rates must produce a tighter interval.

    If this ever fails, the iterated-logarithm term is growing faster than the
    variance term shrinks and the interval would never converge — a method that
    can never conclude anything.
    """
    small = difference_of_proportions(treatment_converted=40, treatment_n=100,
                                      control_converted=30, control_n=100)
    large = difference_of_proportions(treatment_converted=400, treatment_n=1000,
                                      control_converted=300, control_n=1000)
    assert small is not None and large is not None
    assert (large.upper - large.lower) < (small.upper - small.lower)


def test_excludes_zero_only_when_it_really_does():
    tiny = difference_of_proportions(treatment_converted=51, treatment_n=100,
                                     control_converted=50, control_n=100)
    assert tiny is not None and not tiny.excludes_zero
    assert tiny.direction == "inconclusive"

    huge = difference_of_proportions(treatment_converted=900, treatment_n=1000,
                                     control_converted=300, control_n=1000)
    assert huge is not None and huge.excludes_zero
    assert huge.direction == "positive"


def test_negative_effect_is_detected_and_named():
    """A campaign that made things WORSE must be reported as such, not as 'no
    effect'. Silently rounding harm to zero is how a value-destroying programme
    survives review."""
    cs = difference_of_proportions(treatment_converted=200, treatment_n=1000,
                                   control_converted=600, control_n=1000)
    assert cs is not None
    assert cs.excludes_zero
    assert cs.direction == "negative"
    assert cs.estimate < 0


# ---------------------------------------------------------------------------
# THE property that justifies the module
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_coverage_under_peeking():
    """Reproduces the simulation quoted in the module docstring.

    The null is TRUE — both arms have identical rates — and an imaginary
    marketer checks the interval every 10 customers, stopping the moment it
    excludes zero. Under a fixed-horizon interval that strategy manufactures
    significance; under a confidence sequence it must not.
    """
    random.seed(20260720)
    trials, max_n, peek_every, true_p = 400, 400, 10, 0.30
    false_positives = 0

    for _ in range(trials):
        tc = cc = 0
        flagged = False
        for n in range(1, max_n + 1):
            tc += random.random() < true_p
            cc += random.random() < true_p
            if n % peek_every:
                continue
            cs = difference_of_proportions(
                treatment_converted=tc, treatment_n=n,
                control_converted=cc, control_n=n)
            if cs and cs.excludes_zero:
                flagged = True
                break
        false_positives += flagged

    rate = false_positives / trials
    # Nominal alpha is 0.05. The sequence is conservative, so the observed rate
    # should sit well below it; the ceiling here allows simulation noise while
    # still failing loudly if time-uniformity is ever broken.
    assert rate <= 0.05, (
        f"false-positive rate {rate:.1%} exceeds nominal alpha under continuous "
        f"peeking — the time-uniform guarantee is broken")


@pytest.mark.slow
def test_still_detects_a_real_effect():
    """The other half of the bargain: it has to actually fire.

    This is the test that would have caught the first implementation, which
    combined two per-arm sequences additively and detected a real +20% lift in
    under 1% of runs while looking impeccable on the false-positive test.
    """
    random.seed(11)
    trials, per_arm = 120, 300
    detected = 0

    for _ in range(trials):
        tc = cc = 0
        hit = False
        for n in range(1, per_arm + 1):
            tc += random.random() < 0.50   # +20 points of real lift
            cc += random.random() < 0.30
            if n % 10 or n < 20:
                continue
            cs = difference_of_proportions(
                treatment_converted=tc, treatment_n=n,
                control_converted=cc, control_n=n)
            if cs and cs.excludes_zero:
                hit = True
                break
        detected += hit

    power = detected / trials
    assert power >= 0.80, (
        f"only {power:.1%} of runs detected a real +20pt lift at {per_arm}/arm — "
        f"the interval is too conservative to be useful at this product's data "
        f"volume")


# ---------------------------------------------------------------------------
# e-process
# ---------------------------------------------------------------------------

def test_log_e_value_grows_with_evidence():
    weak = difference_of_proportions(treatment_converted=55, treatment_n=100,
                                     control_converted=50, control_n=100)
    strong = difference_of_proportions(treatment_converted=550, treatment_n=1000,
                                       control_converted=500, control_n=1000)
    assert weak is not None and strong is not None
    assert strong.log_e_value > weak.log_e_value


def test_log_e_value_is_finite_at_degenerate_arms():
    """Nobody converted, or everybody did — common early in a campaign, and the
    place a naive log-likelihood produces -inf and poisons the whole readout."""
    for tc, cc in ((0, 0), (10, 10), (0, 10), (10, 0)):
        cs = difference_of_proportions(treatment_converted=tc, treatment_n=10,
                                       control_converted=cc, control_n=10)
        assert cs is not None
        assert math.isfinite(cs.log_e_value)


# ---------------------------------------------------------------------------
# Effect size gating
# ---------------------------------------------------------------------------

def test_meets_effect_size_judges_the_lower_bound_not_the_estimate():
    """The claim is 'the effect is at least X'. Only the lower bound supports
    that; a pretty midpoint does not."""
    # Chosen so the interval EXCLUDES zero (a real effect) while its lower bound
    # sits below a 5-point MDE. A +6pt estimate at n=1000 is NOT significant on
    # an anytime-valid interval — that was this test's original mistake, and the
    # honest fix was a bigger effect rather than a looser interval.
    cs = difference_of_proportions(treatment_converted=620, treatment_n=1000,
                                   control_converted=500, control_n=1000)
    assert cs is not None
    assert cs.excludes_zero, f"expected a detectable effect, got {cs}"
    assert cs.estimate > 0.05
    # The lower bound is below 5pt, so a 5pt MDE is not met even though the
    # point estimate clears it comfortably.
    assert cs.lower < 0.05, f"lower bound {cs.lower} — pick a tighter case"
    assert not cs.meets_effect_size(0.05)
    assert cs.meets_effect_size(0.0)


def test_interpret_never_styles_inconclusive_as_failure():
    """Wording check with teeth: an inconclusive readout must not be described
    in language that would make an operator stop a healthy campaign."""
    cs = difference_of_proportions(treatment_converted=51, treatment_n=100,
                                   control_converted=50, control_n=100)
    out = interpret(cs)
    assert out["state"] == "inconclusive"
    assert out["actionable"] is False
    blob = (out["headline"] + " " + out["detail"]).lower()
    for forbidden in ("fail", "error", "invalid", "problem", "wrong"):
        assert forbidden not in blob, f"inconclusive copy reads as a failure: {blob!r}"


def test_interpret_handles_no_interval():
    out = interpret(None)
    assert out["state"] == "not_measurable"
    assert out["actionable"] is False
    assert str(MIN_ARM_FOR_INTERVAL) in out["detail"]


# ---------------------------------------------------------------------------
# Covariate balance
# ---------------------------------------------------------------------------

def test_smd_zero_for_identical_arms():
    check = standardised_mean_difference("x", [1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert check is not None
    assert check.smd == 0.0
    assert check.is_balanced


def test_smd_flags_a_shifted_arm():
    treatment = [10, 12, 11, 13, 9, 10, 11, 12]
    control = [20, 22, 21, 23, 19, 20, 21, 22]
    check = standardised_mean_difference("basket", treatment, control)
    assert check is not None
    assert abs(check.smd) > SMD_IMBALANCE_THRESHOLD
    assert not check.is_balanced
    assert check.smd < 0  # treatment is lower — direction is meaningful


def test_smd_needs_two_observations_per_arm():
    assert standardised_mean_difference("x", [1], [1, 2, 3]) is None
    assert standardised_mean_difference("x", [1, 2, 3], []) is None


def test_smd_constant_arms_do_not_divide_by_zero():
    same = standardised_mean_difference("x", [5, 5, 5], [5, 5, 5])
    assert same is not None and same.smd == 0.0 and same.is_balanced

    differ = standardised_mean_difference("x", [5, 5, 5], [9, 9, 9])
    assert differ is not None
    assert differ.smd == float("inf")
    assert not differ.is_balanced


def test_summarise_balance_names_the_offending_covariates():
    checks = [
        standardised_mean_difference("ok", [1, 2, 3, 4], [1, 2, 3, 4]),
        standardised_mean_difference("bad", [1, 1, 1, 2], [9, 9, 9, 8]),
    ]
    summary = summarise_balance([c for c in checks if c])
    assert summary["status"] == "imbalanced"
    assert "bad" in summary["imbalanced"]
    assert "ok" not in summary["imbalanced"]
    # The note must explain the CONSEQUENCE, not merely report a statistic.
    assert "campaign" in summary["note"].lower()


def test_summarise_balance_with_no_checks_is_unknown_not_balanced():
    """Absence of evidence is not evidence of balance. Reporting 'balanced' for
    an unverified split would be the most dangerous possible default."""
    summary = summarise_balance([])
    assert summary["status"] == "unknown"
    assert summary["checked"] == 0
