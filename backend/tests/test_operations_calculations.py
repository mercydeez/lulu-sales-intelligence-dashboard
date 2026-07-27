"""Operations Copilot — deterministic calculator tests.

These functions produce the only numbers a human ever approves, so the tests
assert the SAFETY properties, not just the arithmetic: a transfer must never
strand the source store, a noisy velocity must produce a refusal rather than a
confident small number, and every draft must carry the assumptions it rests on.
"""
import pytest

from app.services.operations.calculations import (
    calculate_measurement_baseline,
    calculate_replenishment,
    calculate_transfer,
    days_of_cover,
)
from app.services.operations.policy import (
    DEFAULT_POLICY,
    OperationsPolicy,
    ReplenishmentSettings,
    TransferSettings,
)

R = DEFAULT_POLICY.replenishment
T = DEFAULT_POLICY.transfer


class TestDaysOfCover:
    def test_basic_cover(self):
        assert days_of_cover(100, 10) == 10.0

    def test_zero_velocity_is_none_not_infinity(self):
        """An item that isn't selling has no meaningful cover — callers must be
        forced to say 'unknown' rather than print a fabricated number."""
        assert days_of_cover(100, 0) is None
        assert days_of_cover(100, None) is None

    def test_negative_stock_floors_at_zero(self):
        assert days_of_cover(-5, 10) == 0.0


class TestReplenishment:
    def test_quantity_follows_the_order_up_to_rule(self):
        # target = 5/day * (7 lead + 7 review) + 5/day * 7 safety = 70 + 35 = 105
        # order  = 105 - 20 on hand = 85
        result = calculate_replenishment(current_stock=20, daily_velocity=5,
                                         settings=R, lead_time_days=7)
        assert result.is_actionable
        assert result.quantity == 85
        assert result.inputs["target_level"] == 105.0

    def test_missing_lead_time_is_recorded_as_an_assumption(self):
        result = calculate_replenishment(current_stock=20, daily_velocity=5,
                                         settings=R, lead_time_days=None)
        assert any("lead time" in a.lower() for a in result.assumptions)
        assert result.inputs["lead_time_days"] == R.default_lead_time_days

    def test_known_lead_time_adds_no_lead_time_assumption(self):
        result = calculate_replenishment(current_stock=20, daily_velocity=5,
                                         settings=R, lead_time_days=3)
        assert not any("assuming" in a.lower() and "lead time" in a.lower()
                       for a in result.assumptions)

    def test_open_orders_are_flagged_as_uncounted(self):
        result = calculate_replenishment(current_stock=20, daily_velocity=5, settings=R)
        assert any("inbound" in a.lower() or "purchase order" in a.lower()
                   for a in result.assumptions)

    def test_on_order_quantity_reduces_the_draft(self):
        without = calculate_replenishment(current_stock=20, daily_velocity=5,
                                          settings=R, lead_time_days=7)
        with_inbound = calculate_replenishment(current_stock=20, daily_velocity=5,
                                               settings=R, lead_time_days=7,
                                               on_order_quantity=50)
        assert with_inbound.quantity == without.quantity - 50

    def test_sufficient_stock_refuses_instead_of_ordering_zero(self):
        result = calculate_replenishment(current_stock=1000, daily_velocity=5,
                                         settings=R, lead_time_days=7)
        assert not result.is_actionable
        assert result.quantity == 0
        assert "order-up-to level" in result.refusal_reason

    def test_noisy_velocity_refuses(self):
        result = calculate_replenishment(current_stock=0, daily_velocity=0.01,
                                         settings=R)
        assert not result.is_actionable
        assert "velocity" in result.refusal_reason
        assert result.quantity == 0

    def test_zero_velocity_refuses(self):
        assert not calculate_replenishment(current_stock=0, daily_velocity=0,
                                           settings=R).is_actionable

    def test_none_velocity_refuses_without_raising(self):
        result = calculate_replenishment(current_stock=0, daily_velocity=None, settings=R)
        assert not result.is_actionable

    def test_rounding_to_case_size_rounds_up(self):
        settings = ReplenishmentSettings(round_to_multiple=12)
        result = calculate_replenishment(current_stock=20, daily_velocity=5,
                                         settings=settings, lead_time_days=7)
        assert result.quantity % 12 == 0
        assert result.quantity >= 85

    def test_absurd_quantity_refuses_rather_than_drafting(self):
        """A number this large means the inputs are wrong. Escalate to a human
        buyer instead of drafting a plausible-looking catastrophe."""
        settings = ReplenishmentSettings(max_order_quantity=100)
        result = calculate_replenishment(current_stock=0, daily_velocity=50,
                                         settings=settings, lead_time_days=7)
        assert not result.is_actionable
        assert result.quantity == 0
        assert "maximum" in result.refusal_reason

    def test_min_order_quantity_is_respected(self):
        settings = ReplenishmentSettings(min_order_quantity=25)
        result = calculate_replenishment(current_stock=104, daily_velocity=5,
                                         settings=settings, lead_time_days=7)
        assert result.quantity >= 25

    def test_steps_explain_every_term(self):
        result = calculate_replenishment(current_stock=20, daily_velocity=5,
                                         settings=R, lead_time_days=7)
        joined = " ".join(result.steps).lower()
        assert "expected demand" in joined and "safety stock" in joined
        assert "order-up-to" in joined

    def test_out_of_stock_item_gets_a_full_target_order(self):
        result = calculate_replenishment(current_stock=0, daily_velocity=5,
                                         settings=R, lead_time_days=7)
        assert result.quantity == 105


class TestTransfer:
    def test_transfer_respects_all_three_caps(self):
        # dest needs 10/day * 10d = 100 - 10 on hand = 90
        # source spare = 500 - (5/day * 10d = 50) = 450; share cap = 250
        # -> 90 is binding
        result = calculate_transfer(source_stock=500, source_velocity=5,
                                    destination_stock=10, destination_velocity=10,
                                    settings=T)
        assert result.quantity == 90

    def test_source_reserve_binds_before_destination_need(self):
        # source spare = 100 - (8/day * 10d = 80) = 20
        result = calculate_transfer(source_stock=100, source_velocity=8,
                                    destination_stock=0, destination_velocity=10,
                                    settings=T)
        assert result.quantity == 20

    def test_share_cap_binds_when_source_is_idle(self):
        # idle source spares everything, but the share cap holds at 50%
        result = calculate_transfer(source_stock=200, source_velocity=0,
                                    destination_stock=0, destination_velocity=50,
                                    settings=T)
        assert result.quantity == 100

    def test_transfer_never_strands_the_source(self):
        """The property that matters: after the transfer the source still holds
        at least its policy minimum days of cover."""
        result = calculate_transfer(source_stock=200, source_velocity=10,
                                    destination_stock=0, destination_velocity=20,
                                    settings=T)
        assert result.is_actionable
        remaining = 200 - result.quantity
        assert remaining >= 10 * T.source_min_days_cover
        assert result.inputs["source_days_of_cover_after"] >= T.source_min_days_cover

    @pytest.mark.parametrize("src_stock,src_vel,dst_stock,dst_vel", [
        (200, 10, 0, 20), (500, 5, 10, 10), (100, 8, 0, 10),
        (60, 6, 5, 12), (1000, 1, 0, 100),
    ])
    def test_source_cover_invariant_holds_across_scenarios(self, src_stock, src_vel,
                                                            dst_stock, dst_vel):
        result = calculate_transfer(source_stock=src_stock, source_velocity=src_vel,
                                    destination_stock=dst_stock, destination_velocity=dst_vel,
                                    settings=T)
        if result.is_actionable:
            remaining = src_stock - result.quantity
            assert remaining >= src_vel * T.source_min_days_cover - 1e-9
            assert result.quantity <= src_stock * T.max_share_of_source + 1e-9

    def test_source_with_no_spare_refuses(self):
        result = calculate_transfer(source_stock=50, source_velocity=10,
                                    destination_stock=0, destination_velocity=10,
                                    settings=T)
        assert not result.is_actionable
        assert "spare" in result.refusal_reason

    def test_destination_without_demand_refuses(self):
        result = calculate_transfer(source_stock=500, source_velocity=1,
                                    destination_stock=0, destination_velocity=0,
                                    settings=T)
        assert not result.is_actionable
        assert "velocity" in result.refusal_reason

    def test_well_stocked_destination_refuses(self):
        result = calculate_transfer(source_stock=500, source_velocity=1,
                                    destination_stock=1000, destination_velocity=10,
                                    settings=T)
        assert not result.is_actionable

    def test_idle_source_records_the_assumption(self):
        result = calculate_transfer(source_stock=200, source_velocity=0,
                                    destination_stock=0, destination_velocity=50,
                                    settings=T)
        assert any("no sales velocity" in a.lower() for a in result.assumptions)

    def test_absolute_maximum_caps_the_draft(self):
        settings = TransferSettings(max_transfer_quantity=10)
        result = calculate_transfer(source_stock=10000, source_velocity=0,
                                    destination_stock=0, destination_velocity=500,
                                    settings=settings)
        assert result.quantity == 10

    def test_cover_after_is_reported_for_both_stores(self):
        result = calculate_transfer(source_stock=500, source_velocity=5,
                                    destination_stock=10, destination_velocity=10,
                                    settings=T)
        assert result.inputs["destination_days_of_cover_after"] > \
            result.inputs["destination_days_of_cover_before"]
        assert result.inputs["source_days_of_cover_after"] < \
            result.inputs["source_days_of_cover_before"]


class TestMeasurementBaseline:
    def test_stock_actions_measure_days_of_cover(self):
        plan = calculate_measurement_baseline(
            action_type="replenishment_draft", policy=DEFAULT_POLICY,
            current_stock=20, daily_velocity=5)
        assert plan.metric_name == "days_of_cover"
        assert plan.baseline_value == 4.0
        assert plan.unit == "days"
        assert plan.window_days == DEFAULT_POLICY.measurement_window_days

    def test_unknown_baseline_is_none_and_says_so(self):
        plan = calculate_measurement_baseline(
            action_type="stock_transfer_draft", policy=DEFAULT_POLICY,
            current_stock=20, daily_velocity=0)
        assert plan.baseline_value is None
        assert "no baseline" in plan.success_criterion.lower()

    def test_investigation_measures_the_findings_own_metric(self):
        plan = calculate_measurement_baseline(
            action_type="investigation_task", policy=DEFAULT_POLICY,
            finding_metric_value=-0.32, finding_rule="revenue_drop")
        assert plan.metric_name == "revenue_drop"
        assert plan.baseline_value == -0.32
        assert "no longer fires" in plan.success_criterion

    def test_window_follows_tenant_policy(self):
        policy = OperationsPolicy(measurement_window_days=21)
        plan = calculate_measurement_baseline(
            action_type="investigation_task", policy=policy, finding_rule="return_spike")
        assert plan.window_days == 21


def test_calculators_are_pure():
    """Same inputs, same answer — no clock, no randomness, no I/O."""
    kwargs = dict(current_stock=37, daily_velocity=4.5, settings=R, lead_time_days=5)
    first = calculate_replenishment(**kwargs)
    second = calculate_replenishment(**kwargs)
    assert first.model_dump() == second.model_dump()


def test_refusals_always_carry_zero_quantity():
    """A refusal must never ship a number a UI could render as a draft."""
    refusals = [
        calculate_replenishment(current_stock=0, daily_velocity=0, settings=R),
        calculate_replenishment(current_stock=9999, daily_velocity=5, settings=R),
        calculate_transfer(source_stock=10, source_velocity=10, destination_stock=0,
                           destination_velocity=10, settings=T),
        calculate_transfer(source_stock=500, source_velocity=1, destination_stock=0,
                           destination_velocity=0, settings=T),
    ]
    for result in refusals:
        assert result.refusal_reason
        assert result.quantity == 0
        assert not result.is_actionable
