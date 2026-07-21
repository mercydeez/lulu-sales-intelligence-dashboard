"""
Phase 1 GATE — scenario mathematics (board pack v3, p.7/p.9/p.10/p.14).

Covers quantile base demand (incl. the intermittent-demand guard), Monte Carlo
profit distribution, CVaR/cash-at-risk, and determinism (a board decision must
reproduce exactly from stored inputs).
"""
from decimal import Decimal

from app.services import scenario_math as sm


# --- Empirical quantiles ----------------------------------------------------

def test_empirical_quantiles_basic():
    q = sm.empirical_quantiles(list(range(1, 101)))
    assert 9 <= q["p10"] <= 12
    assert 49 <= q["p50"] <= 52
    assert 89 <= q["p90"] <= 92


def test_empirical_quantiles_handles_empty_and_single():
    assert sm.empirical_quantiles([])["p50"] == 0.0
    q = sm.empirical_quantiles([7.0])
    assert q["p10"] == q["p50"] == q["p90"] == 7.0


# --- Quantile base demand ---------------------------------------------------

def test_base_demand_quantiles_ordered_and_scaled():
    series = [10, 12, 8, 11, 9, 13, 10, 12, 9, 11] * 8
    out = sm.base_demand_quantiles(series, horizon_days=14)
    assert out["p10"] < out["p50"] < out["p90"]
    # Median-anchored horizon scaling.
    assert out["p50"] == round(out["daily_p50"] * 14)
    assert out["status"] == "ready"
    assert out["intermittent"] is False


def test_horizon_spread_grows_slower_than_linear():
    """Day-to-day noise partially cancels: the band must widen by ~sqrt(n),
    not n, or the downside is wildly overstated."""
    series = [10, 20, 0, 15, 5, 12, 8] * 12
    short = sm.base_demand_quantiles(series, 1)
    long = sm.base_demand_quantiles(series, 16)
    short_spread = short["p90"] - short["p10"]
    long_spread = long["p90"] - long["p10"]
    assert long_spread < short_spread * 16      # not linear
    assert long_spread > short_spread            # but does widen


def test_intermittent_series_is_flagged_not_smoothed():
    """Board pack p.7: sparse items must not be forced into a smooth model."""
    sparse = [0, 0, 0, 5, 0, 0, 0, 0, 3, 0] * 8
    out = sm.base_demand_quantiles(sparse, 14)
    assert out["intermittent"] is True
    assert out["status"] == "intermittent_low_confidence"


def test_no_history_returns_zero_not_a_guess():
    out = sm.base_demand_quantiles([], 14)
    assert out["p50"] == 0 and out["status"] == "no_history"


# --- Monte Carlo ------------------------------------------------------------

_MC = dict(base_p10=800, base_p50=1000, base_p90=1300, lift_fraction=0.22,
           contacted=200, response_prob=0.3, price=Decimal("20"),
           cost=Decimal("12"), discount_pct=Decimal("10"),
           supply_units=5000, units_expiring=0, fixed_cost=Decimal("30"),
           trials=800, seed=42)


def test_monte_carlo_produces_ordered_distribution():
    mc = sm.monte_carlo(**_MC)
    p10 = Decimal(mc["profit_p10_aed"]); p50 = Decimal(mc["profit_p50_aed"])
    p90 = Decimal(mc["profit_p90_aed"])
    assert p10 < p50 < p90
    assert mc["trials"] == 800


def test_monte_carlo_is_deterministic_for_a_seed():
    a = sm.monte_carlo(**_MC)
    b = sm.monte_carlo(**_MC)
    assert a == b, "same seed must reproduce the same board decision"


def test_different_seeds_differ():
    a = sm.monte_carlo(**_MC)
    b = sm.monte_carlo(**{**_MC, "seed": 7})
    assert a["profit_p50_aed"] != b["profit_p50_aed"]


def test_cvar_is_worse_than_p10():
    """CVaR is the MEAN of the worst tail, so it must sit at or below P10."""
    mc = sm.monte_carlo(**_MC)
    assert Decimal(mc["cvar_5pct_aed"]) <= Decimal(mc["profit_p10_aed"])


def test_constrained_supply_creates_stockout_probability():
    tight = sm.monte_carlo(**{**_MC, "supply_units": 900})
    loose = sm.monte_carlo(**{**_MC, "supply_units": 9000})
    assert tight["stockout_probability"] > loose["stockout_probability"]
    assert loose["stockout_probability"] == 0.0


def test_expiring_stock_drives_expected_expiry_loss():
    none_expiring = sm.monte_carlo(**{**_MC, "supply_units": 4000, "units_expiring": 0})
    some_expiring = sm.monte_carlo(**{**_MC, "supply_units": 4000, "units_expiring": 300})
    assert Decimal(some_expiring["expected_expiry_loss_aed"]) > \
        Decimal(none_expiring["expected_expiry_loss_aed"])


def test_unknown_cost_yields_no_fabricated_margin():
    mc = sm.monte_carlo(**{**_MC, "cost": None})
    # With no cost there is no margin to claim — every trial is fixed cost only.
    assert Decimal(mc["profit_p90_aed"]) <= Decimal("0")


def test_loss_probability_between_zero_and_one():
    mc = sm.monte_carlo(**_MC)
    assert 0.0 <= mc["loss_probability"] <= 1.0


# --- Cash at risk -----------------------------------------------------------

def test_cash_at_risk_includes_committed_cash():
    mc = sm.monte_carlo(**{**_MC, "supply_units": 900})
    car = sm.cash_at_risk(mc, Decimal("5000"))
    assert Decimal(car["committed_cash_aed"]) == Decimal("5000.00")
    # Cash at risk is never positive-looking when cash is committed.
    assert Decimal(car["cash_at_risk_aed"]) <= Decimal("-5000.00")


def test_cash_at_risk_with_no_commitment_tracks_tail_only():
    mc = sm.monte_carlo(**_MC)
    car = sm.cash_at_risk(mc, Decimal("0"))
    cvar = Decimal(mc["cvar_5pct_aed"])
    expected = min(cvar, Decimal("0"))
    assert Decimal(car["cash_at_risk_aed"]) == expected.quantize(Decimal("0.01"))
