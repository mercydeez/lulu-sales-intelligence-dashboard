"""
Outcome-based pricing — pure fee/guarantee math (no DB).

The fee is only ever computed on CONFIRMED value, and the savings guarantee waives
the variable portion when the bar isn't met. These guard that the customer never
overpays and the math is non-circular.
"""
from app.services.outcome_pricing import build_statement, suggest_from_daily, RECOVERY_DAYS

PLAN = {"base_fee_aed": 1000, "value_share_pct": 10, "savings_guarantee_multiple": 5, "currency": "AED"}


def test_variable_is_share_of_confirmed_value():
    s = build_statement(50000, {**PLAN, "savings_guarantee_multiple": 0})
    assert s["variable_fee_aed"] == 5000   # 10% of 50000
    assert s["total_fee_aed"] == 6000      # base 1000 + 5000


def test_guarantee_met_keeps_variable():
    # required = 5 x base = 5000; confirmed 50000 >= 5000 -> met, variable kept
    s = build_statement(50000, PLAN)
    assert s["guarantee"]["met"] is True
    assert s["guarantee"]["variable_waived"] is False
    assert s["variable_fee_aed"] == 5000


def test_guarantee_not_met_waives_variable():
    # required = 5000; confirmed 3000 < 5000 -> not met -> variable waived, pay base only
    s = build_statement(3000, PLAN)
    assert s["guarantee"]["met"] is False
    assert s["guarantee"]["variable_waived"] is True
    assert s["variable_fee_aed"] == 0
    assert s["total_fee_aed"] == 1000


def test_no_guarantee_never_waives():
    s = build_statement(100, {**PLAN, "savings_guarantee_multiple": 0})
    assert s["guarantee"]["met"] is True
    assert s["variable_fee_aed"] == 10  # 10% of 100


def test_zero_value_is_just_base():
    s = build_statement(0, PLAN)
    assert s["variable_fee_aed"] == 0
    assert s["total_fee_aed"] == 1000


def test_value_to_fee_ratio_reported():
    s = build_statement(50000, PLAN)
    assert s["value_to_fee_ratio"] == round(50000 / 6000, 2)


def test_currency_is_aed():
    assert build_statement(1000, PLAN)["currency"] == "AED"


def test_suggestion_is_daily_times_recovery_window():
    # Conservative: entity daily revenue × the recovery window. Operator confirms.
    assert suggest_from_daily(1000) == round(1000 * RECOVERY_DAYS, 2)


def test_zero_daily_revenue_suggests_zero():
    assert suggest_from_daily(0) == 0
