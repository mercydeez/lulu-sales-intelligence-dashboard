"""
Retention & Commercial Orchestration — unit coverage of the correctness-critical
logic: the campaign state machine, deterministic cohort assignment, churn
scoring, the Decimal EV optimizer and its policy guards, and the idempotent
redemption replay path. Concurrency invariants (no negative stock, no
over-budget spend) are enforced in SQL (FOR UPDATE + guarded UPDATE + CHECK
constraints) and exercised by the live stack, not by these mocked-session tests.
"""
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services import retention_service as ret


# --- State machine ----------------------------------------------------------

def test_state_machine_covers_lifecycle():
    assert "audience_ready" in ret.STATUS_TRANSITIONS["draft"]
    assert "simulated" in ret.STATUS_TRANSITIONS["audience_ready"]
    assert "pending_approval" in ret.STATUS_TRANSITIONS["simulated"]
    assert "approved" in ret.STATUS_TRANSITIONS["pending_approval"]
    assert "active" in ret.STATUS_TRANSITIONS["approved"]
    assert "paused" in ret.STATUS_TRANSITIONS["active"]
    assert "active" in ret.STATUS_TRANSITIONS["paused"]          # resume
    assert "measured" in ret.STATUS_TRANSITIONS["completed"]
    assert ret.STATUS_TRANSITIONS["measured"] == set()
    assert ret.STATUS_TRANSITIONS["cancelled"] == set()


def test_state_machine_rejects_illegal_jumps():
    with pytest.raises(ValueError):
        ret._require_transition("draft", "active")
    with pytest.raises(ValueError):
        ret._require_transition("cancelled", "active")
    # A rejected (still pending) campaign cannot activate.
    with pytest.raises(ValueError):
        ret._require_transition("pending_approval", "active")


# --- Deterministic cohort assignment ---------------------------------------

def test_cohort_assignment_is_stable_across_runs():
    first = [ret.assign_cohort(1, 42, cid, 10.0) for cid in range(1, 200)]
    second = [ret.assign_cohort(1, 42, cid, 10.0) for cid in range(1, 200)]
    assert first == second


def test_cohort_split_roughly_matches_control_pct():
    cohorts = [ret.assign_cohort(1, 7, cid, 20.0) for cid in range(1, 2001)]
    control_share = cohorts.count("control") / len(cohorts)
    assert 0.15 < control_share < 0.25


def test_cohort_differs_by_campaign():
    a = [ret.assign_cohort(1, 1, cid, 50.0) for cid in range(1, 100)]
    b = [ret.assign_cohort(1, 2, cid, 50.0) for cid in range(1, 100)]
    assert a != b


# --- Churn scoring ----------------------------------------------------------

def test_churn_score_monotonic_in_recency():
    lo, _ = ret.churn_score({"recency_days": 3, "purchases_90d": 12,
                             "avg_interval_days": 7, "promo_rate": 0, "return_rate": 0})
    hi, reasons = ret.churn_score({"recency_days": 70, "purchases_90d": 1,
                                   "avg_interval_days": 10, "promo_rate": 0,
                                   "return_rate": 0})
    assert hi > lo
    assert "overdue_vs_own_rhythm" in reasons


def test_churn_score_has_reason_codes_and_range():
    score, reasons = ret.churn_score({"recency_days": 10, "purchases_90d": 8,
                                      "avg_interval_days": 9, "promo_rate": 0.6,
                                      "return_rate": 0.3})
    assert 0.0 <= score <= 1.0
    assert "discount_dependent" in reasons
    assert "high_return_ratio" in reasons


# --- Optimizer: expected value + policy guards ------------------------------

COMMON = dict(promo_rate=0.5, price=Decimal("20.00"), cost=Decimal("12.00"),
              monthly_value=Decimal("300.00"))


def test_high_churn_positive_ev_yields_discount():
    action, pct, resp, ev, reasons = ret.choose_action(
        churn=0.8, max_discount_pct=Decimal("15"), min_margin_pct=Decimal("10"),
        **COMMON)
    assert action == "PERCENT_DISCOUNT"
    assert pct > 0
    assert ev > 0


def test_low_value_customer_gets_no_discount_despite_high_churn():
    # High churn but near-zero retained value -> EV of a discount goes negative;
    # high churn alone must never force a discount.
    action, pct, resp, ev, reasons = ret.choose_action(
        churn=0.9, promo_rate=0.0, price=Decimal("20.00"), cost=Decimal("19.90"),
        monthly_value=Decimal("0.00"), max_discount_pct=Decimal("15"),
        min_margin_pct=Decimal("0"))
    assert action != "PERCENT_DISCOUNT"


def test_margin_floor_blocks_deep_discount():
    # 15% off a 20 AED item costing 16 AED sells at 17 -> margin 5% < floor 10%.
    action, pct, resp, ev, reasons = ret.choose_action(
        churn=0.8, promo_rate=0.5, price=Decimal("20.00"), cost=Decimal("16.00"),
        monthly_value=Decimal("300.00"), max_discount_pct=Decimal("15"),
        min_margin_pct=Decimal("10"))
    if action == "PERCENT_DISCOUNT":
        sell = Decimal("20.00") * (1 - pct / 100)
        margin_pct = (sell - Decimal("16.00")) / Decimal("20.00") * 100
        assert margin_pct >= Decimal("10")


def test_unknown_cost_never_discounts():
    action, pct, *_ = ret.choose_action(
        churn=0.9, promo_rate=0.9, price=Decimal("20.00"), cost=None,
        monthly_value=Decimal("500.00"), max_discount_pct=Decimal("15"),
        min_margin_pct=Decimal("10"))
    assert action != "PERCENT_DISCOUNT"


def test_ev_math_is_decimal_and_rounded():
    ev = ret.action_ev("PERCENT_DISCOUNT", churn=0.7, resp=0.3,
                       price=Decimal("25.00"), cost=Decimal("15.00"),
                       discount_pct=Decimal("10"), monthly_value=Decimal("200.00"))
    assert isinstance(ev, Decimal)
    assert ev == ev.quantize(Decimal("0.01"))


def test_response_prob_bounded_and_rises_with_discount():
    low = ret.response_prob(0.5, 0, 0.5)
    high = ret.response_prob(0.5, 15, 0.5)
    assert 0.02 <= low < high <= 0.95


# --- Redemption: idempotent replay ------------------------------------------

def _session_with_prior_redemption():
    session = MagicMock()
    prior = MagicMock(id=7, redemption_amount_aed=Decimal("3.00"), redeemed_at=None)
    result = MagicMock()
    result.fetchone.return_value = prior
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_redeem_replay_returns_original_without_writes():
    session = _session_with_prior_redemption()
    out = await ret.redeem(session, tenant_id=1, offer_id=7,
                           idempotency_key="abc12345", actor=None)
    assert out["replay"] is True
    assert out["amount_aed"] == "3.00"
    # Only the replay lookup ran — no locks, no updates, no commit.
    assert session.execute.await_count == 1
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_redeem_missing_offer_raises():
    session = MagicMock()
    empty = MagicMock()
    empty.fetchone.return_value = None
    empty.mappings.return_value.fetchone.return_value = None
    session.execute = AsyncMock(return_value=empty)
    with pytest.raises(ValueError, match="not found"):
        await ret.redeem(session, tenant_id=1, offer_id=999,
                         idempotency_key="zzzz9999", actor=None)


@pytest.mark.asyncio
async def test_expired_offer_cannot_be_redeemed():
    from datetime import datetime, timedelta, timezone
    session = MagicMock()
    no_prior = MagicMock(); no_prior.fetchone.return_value = None
    offer = {"status": "issued",
             "expires_at": datetime.now(timezone.utc) - timedelta(days=1)}
    offer_result = MagicMock()
    offer_result.mappings.return_value.fetchone.return_value = offer
    session.execute = AsyncMock(side_effect=[no_prior, offer_result])
    with pytest.raises(ValueError, match="expired"):
        await ret.redeem(session, tenant_id=1, offer_id=1,
                         idempotency_key="key12345", actor=None)


# --- Model card honesty ------------------------------------------------------

def test_model_card_makes_no_accuracy_claims():
    card = ret.model_card()
    assert card["synthetic_data"] is True
    assert card["trained_artifact"] is None
    assert "no production accuracy" in card["metrics"]["note"].lower()
