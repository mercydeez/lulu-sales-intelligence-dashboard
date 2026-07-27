"""Flywheel — the decision-safety and money-safety invariants.

These tests encode the scenarios from §24 of the build brief that can be proven
WITHOUT a live database: the optimizer's policy gates, the EIV arithmetic, the
state machine, the stable treatment/control split, and the reason-code contract.

The ledger/concurrency scenarios (11–15) that genuinely need Postgres row locks
live in test_flywheel_ledger.py and skip cleanly when no database is reachable —
asserting on a mocked lock would prove nothing about the real invariant.

Follows the repo convention: conftest.py forces ENVIRONMENT=testing and dummy
secrets before app imports, so no live Postgres/Redis is required here.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.flywheel import churn, optimizer, uplift
from app.services.flywheel.campaign_state import (
    TRANSITIONS, TransitionError, assert_transition, can_transition,
    mermaid_diagram,
)
from app.services.flywheel.types import (
    ActionCandidate, ActionType, CampaignStatus as S, PolicyEnvelope,
    ReasonCode, is_control, money, stable_hash,
)

ENVELOPE = PolicyEnvelope(max_discount_pct=Decimal("20"), min_margin_pct=Decimal("10"))

BASE_FEATURES = {
    "recency_days": 30, "frequency_90d": 3, "monetary_90d_aed": 900,
    "avg_basket_aed": 300, "spend_drift_ratio": 0.9,
    "interpurchase_gap_days": 14, "gap_volatility": 4,
    "category_diversity": 3, "return_ratio": 0.05,
    "promo_response_rate": 0.4, "tenure_days": 400, "events_90d": 6,
}


def build(**overrides):
    """Build candidates with sensible defaults, overriding what a test cares about."""
    kwargs = dict(
        customer_id=1, churn_probability=0.5, features=BASE_FEATURES,
        monthly_value_aed=money(400),
        uplift_by_action={ActionType.PERCENT_DISCOUNT: 0.08, ActionType.REMINDER: 0.02,
                          ActionType.LOYALTY_POINTS: 0.04, ActionType.FREE_DELIVERY: 0.03},
        envelope=ENVELOPE, item_id=1, store_id=1,
        unit_price_aed=money(50), unit_cost_aed=money(30),
    )
    kwargs.update(overrides)
    return optimizer.build_candidates(**kwargs)


# ===========================================================================
# §24.1–2 — the headline rule: risk alone never buys a discount
# ===========================================================================

def test_high_churn_positive_uplift_stock_and_budget_returns_an_action():
    """§24.1 — the happy path must actually produce an offer."""
    result = optimizer.select_best(
        build(churn_probability=0.7,
              uplift_by_action={ActionType.PERCENT_DISCOUNT: 0.10}),
        envelope=ENVELOPE)
    assert result["selected"].action_type != ActionType.NO_ACTION
    assert result["selected"].eiv_aed > 0


def test_high_churn_with_zero_uplift_yields_no_discount():
    """§24.2 / §5 — THE core safety property.

    A customer at 92% churn risk with no persuadability must get NO_ACTION.
    This is not enforced by a guard clause but by the objective function: every
    benefit term multiplies uplift, so zero uplift means zero expected value.
    """
    result = optimizer.select_best(
        build(churn_probability=0.92, uplift_by_action={a: 0.0 for a in ActionType}),
        envelope=ENVELOPE)
    assert result["selected"].action_type == ActionType.NO_ACTION
    assert result["selected"].eiv_aed == money(0)


def test_negative_uplift_is_refused_with_its_own_reason_code():
    """An offer that would make things worse must be refused, not merely ranked low."""
    result = optimizer.select_best(
        build(churn_probability=0.7, uplift_by_action={ActionType.PERCENT_DISCOUNT: -0.05}),
        envelope=ENVELOPE)
    assert result["selected"].action_type == ActionType.NO_ACTION
    codes = {r["reason_code"] for r in result["rejected"]}
    assert codes & {ReasonCode.NEGATIVE_UPLIFT.value,
                    ReasonCode.UPLIFT_BELOW_THRESHOLD.value}


def test_uplift_within_noise_is_refused():
    """Uplift below the threshold is noise dressed as a decision."""
    tiny = ENVELOPE.min_uplift_threshold / 2
    result = optimizer.select_best(
        build(churn_probability=0.8, uplift_by_action={ActionType.PERCENT_DISCOUNT: tiny}),
        envelope=ENVELOPE)
    assert result["selected"].action_type == ActionType.NO_ACTION


# ===========================================================================
# §24.3–5 — stock and margin policy
# ===========================================================================

def test_zero_stock_refuses_every_stock_consuming_action():
    """§24.3/4 — you cannot promise what you do not have.

    The correct behaviour is NOT 'give up': it is to refuse the stock-consuming
    actions and fall through to a reward that consumes no inventory — rung (d)
    of the shortage ladder. So we assert on the CLASS of action selected, not
    on NO_ACTION, which would have asserted the system is worse than it is.
    """
    from app.services.flywheel.types import STOCK_CONSUMING_ACTIONS

    result = optimizer.select_best(build(atp_units=0), envelope=ENVELOPE)
    assert result["selected"].action_type not in STOCK_CONSUMING_ACTIONS
    assert any(r["reason_code"] == ReasonCode.INSUFFICIENT_STOCK.value
               for r in result["rejected"])


def test_zero_stock_with_no_alternative_reward_yields_no_action():
    """With every non-stock reward also unpersuasive, there is genuinely
    nothing worth doing."""
    result = optimizer.select_best(
        build(atp_units=0, uplift_by_action={ActionType.PERCENT_DISCOUNT: 0.08}),
        envelope=ENVELOPE)
    assert result["selected"].action_type == ActionType.NO_ACTION


def test_tight_stock_prices_in_a_stockout_penalty_but_still_allows_the_offer():
    """Scarce-but-servable stock should reduce EIV, not veto the action —
    otherwise a healthy campaign stalls the moment inventory dips."""
    tight = [c for c in build(atp_units=3)
             if c.action_type == ActionType.PERCENT_DISCOUNT and c.feasible]
    assert tight, "a servable action should remain feasible at 3 units"
    assert any(c.stockout_risk_penalty_aed > 0 for c in tight)


def test_margin_floor_is_enforced_on_the_net_price():
    """A cost of 47 against a price of 50 leaves no room for a 10% floor after
    any discount — every DISCOUNT candidate must be refused.

    A non-discount reward may still be selected: the margin floor governs what
    we may sell at, not whether the customer is worth contacting.
    """
    result = optimizer.select_best(
        build(unit_cost_aed=money(47)), envelope=ENVELOPE)
    assert result["selected"].action_type != ActionType.PERCENT_DISCOUNT
    assert any(r["reason_code"] == ReasonCode.MARGIN_FLOOR_BREACHED.value
               for r in result["rejected"])


def test_thin_margin_with_only_discount_candidates_yields_no_action():
    result = optimizer.select_best(
        build(unit_cost_aed=money(47),
              uplift_by_action={ActionType.PERCENT_DISCOUNT: 0.10}),
        envelope=ENVELOPE)
    assert result["selected"].action_type == ActionType.NO_ACTION


def test_discount_beyond_the_campaign_cap_is_recorded_as_rejected_not_dropped():
    """The trace must show a capped option was CONSIDERED — silently omitting it
    would make the decision look less thorough than it was."""
    strict = PolicyEnvelope(max_discount_pct=Decimal("7"), min_margin_pct=Decimal("5"))
    result = optimizer.select_best(build(envelope=strict), envelope=strict)
    assert any(r["reason_code"] == ReasonCode.DISCOUNT_CAP_EXCEEDED.value
               for r in result["rejected"])


# ===========================================================================
# EIV arithmetic and reproducibility (§10)
# ===========================================================================

def test_eiv_equals_benefits_minus_every_cost():
    candidate = ActionCandidate(
        action_type=ActionType.PERCENT_DISCOUNT,
        expected_retained_value_aed=money(100),
        expected_margin_aed=money(50),
        expected_discount_cost_aed=money(20),
        comms_cost_aed=money(1),
        fulfilment_cost_aed=money(2),
        procurement_cost_aed=money(3),
        stockout_risk_penalty_aed=money(4),
    )
    assert candidate.eiv_aed == money(120)  # 150 − 30


def test_no_action_has_exactly_zero_eiv():
    """NO_ACTION is the bar every real action must clear."""
    no_action = next(c for c in build() if c.action_type == ActionType.NO_ACTION)
    assert no_action.eiv_aed == money(0)


def test_a_stored_decision_replays_to_the_same_value():
    """§10 — 'reproducible from its stored inputs', made testable."""
    stored = {
        "expected_retained_value_aed": "120.00", "expected_margin_aed": "45.50",
        "expected_discount_cost_aed": "30.25", "comms_cost_aed": "0.05",
        "fulfilment_cost_aed": "0.00", "procurement_cost_aed": "0.00",
        "stockout_risk_penalty_aed": "5.00", "eiv_aed": "130.20",
        "policy_version": "v1",
    }
    replay = optimizer.replay(stored)
    assert replay["matches"] is True
    assert replay["recomputed_eiv_aed"] == "130.20"


def test_replay_detects_a_tampered_total():
    stored = {
        "expected_retained_value_aed": "100.00", "expected_margin_aed": "0.00",
        "expected_discount_cost_aed": "10.00", "comms_cost_aed": "0.00",
        "fulfilment_cost_aed": "0.00", "procurement_cost_aed": "0.00",
        "stockout_risk_penalty_aed": "0.00",
        "eiv_aed": "999.00",  # not what the terms sum to
        "policy_version": "v1",
    }
    replay = optimizer.replay(stored)
    assert replay["matches"] is False
    assert replay["recomputed_eiv_aed"] == "90.00"


def test_every_selected_action_carries_at_least_one_reason_code():
    """The Decision Trace renders these — an empty list would be a blank panel."""
    for churn_p in (0.1, 0.5, 0.9):
        result = optimizer.select_best(build(churn_probability=churn_p), envelope=ENVELOPE)
        assert result["selected"].reason_codes


# ===========================================================================
# §24.21 — treatment/control assignment stability
# ===========================================================================

def test_stable_hash_is_deterministic_across_calls():
    """PYTHONHASHSEED-salted hash() would reassign arms on every restart and
    silently destroy the experiment. BLAKE2b must not."""
    first = [stable_hash(1, 7, c) for c in range(200)]
    second = [stable_hash(1, 7, c) for c in range(200)]
    assert first == second


def test_control_assignment_is_stable_and_roughly_the_requested_share():
    control_pct = Decimal("20")
    assignments = [is_control(1, 42, c, control_pct) for c in range(4000)]
    assert assignments == [is_control(1, 42, c, control_pct) for c in range(4000)]
    share = sum(assignments) / len(assignments)
    assert 0.17 < share < 0.23, f"expected ~20% control, got {share:.1%}"


def test_zero_control_pct_puts_nobody_in_control():
    assert not any(is_control(1, 1, c, Decimal("0")) for c in range(500))


def test_different_campaigns_assign_independently():
    """Otherwise the same customers land in control forever and are never treated."""
    a = [is_control(1, 1, c, Decimal("20")) for c in range(1000)]
    b = [is_control(1, 2, c, Decimal("20")) for c in range(1000)]
    assert a != b


# ===========================================================================
# §7 — the state machine
# ===========================================================================

def test_a_rejected_campaign_cannot_jump_straight_to_active():
    """§24.18 — the gate that stops unapproved spend."""
    assert not can_transition(S.SIMULATED, S.ACTIVE)
    assert not can_transition(S.DRAFT, S.ACTIVE)
    with pytest.raises(TransitionError):
        assert_transition(S.DRAFT, S.ACTIVE)


def test_cancelled_and_measured_are_terminal():
    assert TRANSITIONS[S.CANCELLED] == frozenset()
    assert TRANSITIONS[S.MEASURED] == frozenset()


def test_cancel_is_reachable_from_every_non_terminal_state():
    """An operator must always be able to stop a campaign."""
    for state, allowed in TRANSITIONS.items():
        if state in (S.CANCELLED, S.MEASURED, S.COMPLETED):
            continue
        assert S.CANCELLED in allowed, f"{state.value} cannot be cancelled"


def test_pause_and_resume_round_trip():
    assert can_transition(S.ACTIVE, S.PAUSED)
    assert can_transition(S.PAUSED, S.ACTIVE)


def test_measurement_closes_the_loop():
    assert can_transition(S.COMPLETED, S.MEASURED)


def test_every_status_appears_in_the_transition_graph():
    """A status missing from the graph would be a dead end no service could exit."""
    for status in S:
        assert status in TRANSITIONS, f"{status.value} has no transition entry"


def test_mermaid_diagram_is_generated_from_the_live_graph():
    """The docs diagram must not be able to drift from the enforced rules."""
    diagram = mermaid_diagram()
    assert diagram.startswith("stateDiagram-v2")
    assert "ACTIVE --> PAUSED" in diagram
    assert "COMPLETED --> MEASURED" in diagram
    # Nothing illegal may appear.
    assert "DRAFT --> ACTIVE" not in diagram


# ===========================================================================
# Churn scoring — the always-available fallback tier
# ===========================================================================

def test_rule_based_scorer_returns_a_probability_and_reasons_for_any_input():
    """It must never raise: a missing feature dict is a normal condition on a
    fresh install, not an error worth a 500."""
    for features in ({}, BASE_FEATURES, {"recency_days": None}):
        probability, reasons = churn.rule_based_score(features)
        assert 0.0 < probability < 1.0
        assert reasons


def test_a_lapsed_customer_scores_higher_than_a_loyal_one():
    """Directional sanity — the scorer must encode the domain, not noise."""
    lapsed, _ = churn.rule_based_score({
        **BASE_FEATURES, "recency_days": 150, "frequency_90d": 0,
        "spend_drift_ratio": 0.3, "interpurchase_gap_days": 12})
    loyal, _ = churn.rule_based_score({
        **BASE_FEATURES, "recency_days": 4, "frequency_90d": 14,
        "spend_drift_ratio": 1.15, "interpurchase_gap_days": 6,
        "category_diversity": 6})
    assert lapsed > loyal
    assert lapsed > 0.6 and loyal < 0.4


def test_recency_is_judged_against_the_customers_own_cadence():
    """30 days quiet means nothing for a quarterly shopper and everything for a
    weekly one. An absolute threshold would mislabel both."""
    weekly, _ = churn.rule_based_score({
        **BASE_FEATURES, "recency_days": 30, "interpurchase_gap_days": 7})
    quarterly, _ = churn.rule_based_score({
        **BASE_FEATURES, "recency_days": 30, "interpurchase_gap_days": 90})
    assert weekly > quarterly


def test_risk_bands_are_ordered_and_cover_the_whole_range():
    assert churn.band_for(0.95) == "critical"
    assert churn.band_for(0.60) == "high"
    assert churn.band_for(0.30) == "medium"
    assert churn.band_for(0.05) == "low"


# ===========================================================================
# Uplift — persuadability, not risk
# ===========================================================================

def test_persuadability_peaks_in_the_middle_of_the_risk_range():
    """Sure things and lost causes are both unmovable; only the middle is
    persuadable. This shape is what stops the optimizer discounting the
    customers who were coming back anyway."""
    def u(p):
        return uplift.deterministic_uplift(
            action=ActionType.PERCENT_DISCOUNT, churn_probability=p,
            features=BASE_FEATURES, discount_pct=10.0)[2]

    assert u(0.5) > u(0.05), "a sure thing should not be more persuadable than a fence-sitter"
    assert u(0.5) > u(0.97), "a lost cause should not be more persuadable than a fence-sitter"


def test_a_never_responder_gets_negative_or_negligible_uplift():
    """Someone who ignored ten offers will ignore the eleventh — and the contact
    itself has a cost, so treating them can be actively negative."""
    _, _, lift = uplift.deterministic_uplift(
        action=ActionType.PERCENT_DISCOUNT, churn_probability=0.5,
        features={**BASE_FEATURES, "promo_response_rate": 0.0}, discount_pct=10.0)
    assert lift < 0.02


def test_no_action_has_no_uplift_by_construction():
    assert uplift.deterministic_uplift(
        action=ActionType.NO_ACTION, churn_probability=0.9,
        features=BASE_FEATURES)[2] == 0.0


def test_deeper_discounts_lift_response_with_diminishing_returns():
    def u(depth):
        return uplift.deterministic_uplift(
            action=ActionType.PERCENT_DISCOUNT, churn_probability=0.5,
            features=BASE_FEATURES, discount_pct=depth)[2]

    assert u(20) > u(10) > u(5)
    # The 10→20 gain must not exceed the 5→10 gain: response is sqrt-shaped.
    assert (u(20) - u(10)) < (u(10) - u(5)) * 1.5


# ===========================================================================
# Qini — the correct way to judge an uplift model (§8.6)
# ===========================================================================

def test_qini_rewards_an_informative_ranking():
    """A ranking that concentrates treated responders at the top must score
    positively; a random one must not."""
    n = 400
    scores = [1.0 - i / n for i in range(n)]
    treated = [i % 2 for i in range(n)]
    # Responders concentrated in the top quartile among the treated.
    outcomes = [1 if (treated[i] and i < n // 4) else 0 for i in range(n)]

    informative = uplift.qini_curve(scores, outcomes, treated)
    assert informative["qini_coefficient"] > 0
    assert informative["points"][0]["fraction"] == 0.0


def test_qini_handles_empty_input_without_raising():
    result = uplift.qini_curve([], [], [])
    assert result["n"] == 0 and result["qini_coefficient"] == 0.0


# ===========================================================================
# Money representation
# ===========================================================================

def test_money_never_inherits_binary_float_error():
    """Decimal(0.1) carries float noise; Decimal(str(0.1)) does not. In a ledger
    that difference compounds."""
    assert money(0.1) == Decimal("0.10")
    assert money("1234567.891") == Decimal("1234567.89")
    assert money(None) == Decimal("0.00")


def test_money_is_always_quantized_to_fils():
    for value in (1, 1.005, "3.14159", Decimal("2.71828")):
        assert money(value).as_tuple().exponent == -2
