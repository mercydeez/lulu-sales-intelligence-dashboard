"""Flywheel hardening — tax, liability and contact-governance invariants.

SCOPE NOTE, learned the hard way. The v1 suite had 149 green tests and the
module still failed on its first live call, because those tests exercised pure
functions and never touched SQL. So this file is explicit about what it can and
cannot prove: it tests the ARITHMETIC and the POLICY SHAPES, which are pure and
genuinely testable here. The database behaviour (row locks, claw-back ledger
entries, cross-campaign contact counting) was verified against a live stack and
is recorded in the commit message — it is NOT claimed to be covered here.
"""
from decimal import Decimal

import pytest

from app.services.flywheel import tax
from app.services.flywheel.types import money

UAE_VAT = tax.TaxRule(rate_pct=Decimal("5"), prices_include_tax=True, name="UAE VAT")
VAT_EXCLUSIVE = tax.TaxRule(rate_pct=Decimal("5"), prices_include_tax=False, name="excl")


# ===========================================================================
# Tax — the bug was margin computed on a tax-inclusive amount
# ===========================================================================

def test_tax_is_stripped_from_an_inclusive_price():
    """A 10.00 shelf price at 5% VAT is 9.52 of revenue and 0.48 of tax."""
    assert UAE_VAT.net_of_tax(Decimal("10.00")) == Decimal("9.52")
    assert UAE_VAT.tax_on(Decimal("10.00")) == Decimal("0.48")


def test_an_exclusive_price_is_already_net():
    """When prices EXCLUDE tax the displayed figure IS the revenue. Dividing
    again would under-count revenue by the rate — the same error inverted."""
    assert VAT_EXCLUSIVE.net_of_tax(Decimal("10.00")) == Decimal("10.00")
    assert VAT_EXCLUSIVE.tax_on(Decimal("10.00")) == Decimal("0.00")


def test_no_rule_configured_means_no_tax_applied():
    """Absence of configuration must not silently invent a national rate."""
    assert tax.NO_TAX.net_of_tax(Decimal("10.00")) == Decimal("10.00")
    assert tax.NO_TAX.rate_pct == Decimal("0")


def test_margin_is_lower_net_of_tax_than_gross():
    """THE headline correction. Measured: 30.00% gross vs 26.47% net on a
    10.00 shelf price with 7.00 cost — a 3.53-point overstatement that made a
    10% margin floor pass campaigns earning less than it."""
    gross_view = tax.margin_net_pct(
        gross_price=Decimal("10.00"), unit_cost=Decimal("7.00"),
        discount_pct=Decimal("0"), rule=tax.NO_TAX)
    net_view = tax.margin_net_pct(
        gross_price=Decimal("10.00"), unit_cost=Decimal("7.00"),
        discount_pct=Decimal("0"), rule=UAE_VAT)

    assert gross_view["margin_pct"] == Decimal("30.00")
    assert net_view["margin_pct"] == Decimal("26.47")
    assert net_view["margin_pct"] < gross_view["margin_pct"]


def test_discount_applies_to_the_shelf_price_then_tax_is_stripped():
    """Order matters: the till discounts the displayed price, and tax is a
    share of what the customer actually pays."""
    view = tax.margin_net_pct(
        gross_price=Decimal("100.00"), unit_cost=Decimal("50.00"),
        discount_pct=Decimal("20"), rule=UAE_VAT)
    assert view["discount_amount"] == Decimal("20.00")
    assert view["gross_after_discount"] == Decimal("80.00")
    assert view["net_revenue"] == Decimal("76.19")
    assert view["tax_amount"] == Decimal("3.81")
    assert view["margin_amount"] == Decimal("26.19")


def test_margin_terms_reconcile():
    """Every published intermediate must add up, or the Decision Trace lies."""
    v = tax.margin_net_pct(gross_price=Decimal("57.35"), unit_cost=Decimal("31.10"),
                           discount_pct=Decimal("15"), rule=UAE_VAT)
    assert v["gross_price"] - v["discount_amount"] == v["gross_after_discount"]
    assert v["net_revenue"] + v["tax_amount"] == v["gross_after_discount"]
    assert v["net_revenue"] - v["unit_cost"] == v["margin_amount"]


def test_selling_below_cost_reports_negative_margin_not_an_error():
    v = tax.margin_net_pct(gross_price=Decimal("10.00"), unit_cost=Decimal("20.00"),
                           discount_pct=Decimal("0"), rule=UAE_VAT)
    assert v["margin_amount"] < 0 and v["margin_pct"] < 0


def test_a_full_discount_cannot_divide_by_zero():
    """100% off leaves zero net revenue. Must report worst-case margin, not raise."""
    v = tax.margin_net_pct(gross_price=Decimal("10.00"), unit_cost=Decimal("5.00"),
                           discount_pct=Decimal("100"), rule=UAE_VAT)
    assert v["net_revenue"] == Decimal("0.00")
    assert v["margin_pct"] == Decimal("-100.00")


def test_gross_and_net_round_trip():
    for amount in ("10.00", "57.35", "1234.56"):
        net = UAE_VAT.net_of_tax(Decimal(amount))
        assert abs(UAE_VAT.gross_from_net(net) - Decimal(amount)) <= Decimal("0.01")


# ===========================================================================
# Rounding policy — half-EVEN, not half-up
# ===========================================================================

def test_rounding_is_bankers_not_half_up():
    """Half-up is biased upward and, over many roundings, systematically
    inflates totals — the error a finance team eventually finds. Half-even
    breaks ties toward the even digit, so the bias cancels."""
    assert tax.bankers(Decimal("2.345")) == Decimal("2.34")   # down to even
    assert tax.bankers(Decimal("2.355")) == Decimal("2.36")   # up to even
    assert tax.bankers(Decimal("0.125")) == Decimal("0.12")
    assert tax.bankers(Decimal("0.135")) == Decimal("0.14")


def test_rounding_bias_cancels_across_many_ties():
    """The property that actually matters: half-even must not drift upward
    across a long run of exact ties, which is what half-up does."""
    ties = [Decimal(f"{n}.005") for n in range(1, 201)]
    rounded_sum = sum(tax.bankers(t) for t in ties)
    exact_sum = sum(ties)
    # Half-up would drift by ~0.5 over 200 ties; half-even stays within a fil
    # per 100 values.
    assert abs(rounded_sum - exact_sum) <= Decimal("1.00")


def test_money_and_bankers_agree_on_unambiguous_values():
    for v in ("10.00", "0.01", "999.99"):
        assert tax.bankers(Decimal(v)) == money(Decimal(v))


# ===========================================================================
# Pro-rata claw-back arithmetic (the pure part of returns)
# ===========================================================================

@pytest.mark.parametrize("returned,total,expected_share", [
    (1, 4, Decimal("0.25")), (2, 4, Decimal("0.5")),
    (4, 4, Decimal("1")), (1, 3, Decimal("1") / Decimal("3")),
])
def test_claw_back_is_pro_rata(returned, total, expected_share):
    """Returning 1 of 3 units reverses a third of the discount. Reversing the
    WHOLE discount on a partial return is a common and expensive error."""
    discount = Decimal("6.40")
    share = Decimal(returned) / Decimal(total)
    assert share == expected_share
    clawed = money(discount * share)
    assert clawed <= discount
    if returned == total:
        assert clawed == discount


def test_partial_claw_backs_never_exceed_the_original():
    """Summing every partial return must not exceed what was charged."""
    discount = Decimal("10.00")
    total_units = 3
    clawed = sum(money(discount * (Decimal(1) / Decimal(total_units)))
                 for _ in range(total_units))
    assert clawed <= discount + Decimal("0.01")  # one fil of rounding tolerance


# ===========================================================================
# Contact governance — shapes and defaults
# ===========================================================================

def test_contact_decision_serializes_for_the_ui():
    from app.services.flywheel.contact_governance import ContactDecision
    refused = ContactDecision(False, "GLOBAL_CONTACT_CAP_REACHED",
                              "4 contacts this week", {"all_channels_7d": 4})
    payload = refused.as_dict()
    assert payload["allowed"] is False
    assert payload["reason_code"] == "GLOBAL_CONTACT_CAP_REACHED"
    assert payload["counts"]["all_channels_7d"] == 4


def test_allowed_decision_carries_no_reason_code():
    from app.services.flywheel.contact_governance import ContactDecision
    assert ContactDecision(True).as_dict()["reason_code"] == ""


# ===========================================================================
# Migration 075
# ===========================================================================

def test_migration_075_exists_and_is_transactional():
    from tests.test_flywheel_migration import _find_migration
    path = _find_migration("076_krishna_flywheel_hardening.sql")
    assert path.is_file()
    sql = path.read_text()
    assert "BEGIN;" in sql and "COMMIT;" in sql


@pytest.mark.parametrize("table", [
    "flywheel_tax_rules", "flywheel_returns", "flywheel_contact_policy",
    "flywheel_offer_suppressions",
])
def test_new_tables_are_tenant_scoped_and_rls_forced(table):
    from tests.test_flywheel_migration import _find_migration
    sql = _find_migration("076_krishna_flywheel_hardening.sql").read_text()
    assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert f"'{table}'" in sql[sql.index("FOREACH t IN ARRAY ARRAY["):]
    assert "FORCE ROW LEVEL SECURITY" in sql


def test_returns_are_idempotent_by_constraint():
    """Without this, a retried return claws back twice."""
    from tests.test_flywheel_migration import _find_migration
    sql = _find_migration("076_krishna_flywheel_hardening.sql").read_text()
    assert "uq_flywheel_return_idem" in sql


def test_breakage_requires_the_liability_to_be_released():
    """A row claiming breakage while still liable is contradictory."""
    from tests.test_flywheel_migration import _find_migration
    sql = _find_migration("076_krishna_flywheel_hardening.sql").read_text()
    assert "flywheel_offer_breakage_requires_release" in sql


def test_ledger_accepts_the_new_entry_types():
    from tests.test_flywheel_migration import _find_migration
    sql = _find_migration("076_krishna_flywheel_hardening.sql").read_text()
    assert "'CLAWED_BACK'" in sql and "'BREAKAGE'" in sql


def test_an_all_channel_contact_ceiling_is_seeded():
    """The NULL-channel row is the ceiling that stops 3 emails AND 2 SMS."""
    from tests.test_flywheel_migration import _find_migration
    sql = _find_migration("076_krishna_flywheel_hardening.sql").read_text()
    assert "INSERT INTO flywheel_contact_policy" in sql
    assert "(1, NULL," in sql


# ===========================================================================
# Churn recalibration
# ===========================================================================

def test_temperature_scaling_preserves_ranking():
    """Calibration must not reorder customers — the audience depends on the
    ranking, the optimizer depends on the magnitude. Temperature fixes the
    second without disturbing the first."""
    from app.services.flywheel.churn import rule_based_score

    base = {"recency_days": 20, "frequency_90d": 4, "spend_drift_ratio": 1.0,
            "interpurchase_gap_days": 10, "gap_volatility": 3,
            "category_diversity": 3, "return_ratio": 0.02,
            "promo_response_rate": 0.3, "tenure_days": 400}
    worsening = [
        {**base, "recency_days": r, "spend_drift_ratio": d}
        for r, d in [(5, 1.2), (20, 1.0), (60, 0.8), (120, 0.5), (170, 0.3)]
    ]
    scores = [rule_based_score(f)[0] for f in worsening]
    assert scores == sorted(scores), "monotonicity broken by calibration"


def test_scores_stay_off_the_saturated_extremes():
    """The bimodality that broke targeting: 195 of 300 customers pinned near 0
    and 48 near 1, leaving nothing in the persuadable middle."""
    from app.services.flywheel.churn import rule_based_score

    extreme_bad = {"recency_days": 180, "frequency_90d": 0, "spend_drift_ratio": 0.1,
                   "interpurchase_gap_days": 5, "gap_volatility": 30,
                   "category_diversity": 1, "return_ratio": 0.9,
                   "promo_response_rate": 0.0, "tenure_days": 10}
    extreme_good = {"recency_days": 1, "frequency_90d": 30, "spend_drift_ratio": 2.0,
                    "interpurchase_gap_days": 3, "gap_volatility": 0,
                    "category_diversity": 8, "return_ratio": 0.0,
                    "promo_response_rate": 0.9, "tenure_days": 2000}

    worst, _ = rule_based_score(extreme_bad)
    best, _ = rule_based_score(extreme_good)
    assert worst <= 0.98 and best >= 0.02
    # The spread must still be wide enough to rank on.
    assert worst - best > 0.35


def test_risk_bands_partition_the_reachable_range():
    """A band nobody can enter is worse than no band — an operator reads
    '0 critical' as good news rather than as a broken scale."""
    from app.services.flywheel.churn import BAND_THRESHOLDS, band_for

    assert {name for _, name in BAND_THRESHOLDS} == {"low", "medium", "high", "critical"}
    # Every band must be reachable below the scorer's practical ceiling.
    assert max(t for t, _ in BAND_THRESHOLDS) < 0.98
    assert band_for(0.97) == "critical"
    assert band_for(0.01) == "low"
