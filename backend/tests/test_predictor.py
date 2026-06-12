"""
Predictor Tests (Phase 2.4) — seasonal decomposition model math.

All tests use synthetic series with known seasonality/trend so the model has
ground truth to be checked against. No DB or Redis required.
"""
import math
import pytest
from datetime import date, timedelta

from app.services.predictor import (
    MIN_TRAINING_DAYS,
    SeasonalTrendModel,
    backtest_series,
    fit_dow_indices,
    fit_trend,
    mape,
)

START = date(2025, 1, 6)  # a Monday


def make_series(days, level=100.0, slope=0.0, dow_factors=None, start=START):
    """Synthetic daily series: (level + slope*t) * dow_factor[weekday]."""
    dow_factors = dow_factors or [1.0] * 7
    return [
        (start + timedelta(days=t), (level + slope * t) * dow_factors[(start + timedelta(days=t)).weekday()])
        for t in range(days)
    ]


# Weekend-heavy pattern (typical retail), already normalized to mean 1.0
WEEKEND_HEAVY = [0.9, 0.85, 0.9, 0.95, 1.05, 1.2, 1.15]


class TestDowIndices:

    def test_flat_series_gives_unit_indices(self):
        indices = fit_dow_indices(make_series(70))
        assert all(abs(i - 1.0) < 1e-9 for i in indices)

    def test_recovers_known_seasonality(self):
        indices = fit_dow_indices(make_series(70, dow_factors=WEEKEND_HEAVY))
        for got, expected in zip(indices, WEEKEND_HEAVY):
            assert abs(got - expected) < 0.01

    def test_indices_normalized_to_mean_one(self):
        indices = fit_dow_indices(make_series(70, dow_factors=[0.5, 0.5, 0.5, 0.5, 0.5, 3.0, 1.0]))
        assert abs(sum(indices) / 7 - 1.0) < 1e-9

    def test_all_zero_series(self):
        indices = fit_dow_indices(make_series(70, level=0.0))
        assert indices == [1.0] * 7


class TestTrendFit:

    def test_recovers_linear_trend(self):
        intercept, slope = fit_trend([10 + 2.5 * t for t in range(100)])
        assert abs(intercept - 10) < 1e-6
        assert abs(slope - 2.5) < 1e-6

    def test_flat_series_zero_slope(self):
        intercept, slope = fit_trend([42.0] * 50)
        assert abs(slope) < 1e-9
        assert abs(intercept - 42) < 1e-9

    def test_single_point(self):
        assert fit_trend([7.0]) == (7.0, 0.0)


class TestSeasonalTrendModel:

    def test_rejects_short_history(self):
        with pytest.raises(ValueError):
            SeasonalTrendModel(make_series(MIN_TRAINING_DAYS - 1))

    def test_forecast_shape_and_dates(self):
        series = make_series(60)
        forecasts = SeasonalTrendModel(series).forecast(14)
        assert len(forecasts) == 14
        assert forecasts[0]["prediction_date"] == (series[-1][0] + timedelta(days=1)).isoformat()
        for f in forecasts:
            assert f["confidence_lower"] <= f["predicted_sales"] <= f["confidence_upper"]

    def test_forecasts_flat_series_accurately(self):
        forecasts = SeasonalTrendModel(make_series(120, level=100.0)).forecast(7)
        for f in forecasts:
            assert abs(f["predicted_sales"] - 100.0) < 1.0

    def test_extrapolates_trend(self):
        # 1 unit/day growth over 100 days ending at ~199 — day 110 should be ~209
        forecasts = SeasonalTrendModel(make_series(100, level=100.0, slope=1.0)).forecast(10)
        assert abs(forecasts[-1]["predicted_sales"] - 209.0) < 2.0

    def test_applies_weekly_seasonality(self):
        forecasts = SeasonalTrendModel(
            make_series(140, level=100.0, dow_factors=WEEKEND_HEAVY)
        ).forecast(7)
        by_dow = {
            date.fromisoformat(f["prediction_date"]).weekday(): f["predicted_sales"]
            for f in forecasts
        }
        assert by_dow[5] > by_dow[1]  # Saturday clearly above Tuesday
        assert abs(by_dow[5] / by_dow[1] - WEEKEND_HEAVY[5] / WEEKEND_HEAVY[1]) < 0.05

    def test_never_negative(self):
        # Steep downward trend would cross zero — forecasts must floor at 0
        forecasts = SeasonalTrendModel(make_series(60, level=50.0, slope=-2.0)).forecast(30)
        assert all(f["predicted_sales"] >= 0 for f in forecasts)
        assert all(f["confidence_lower"] >= 0 for f in forecasts)


class TestMape:

    def test_perfect_forecast(self):
        assert mape([10, 20, 30], [10, 20, 30]) == 0.0

    def test_known_error(self):
        assert mape([100, 100], [90, 110]) == 10.0

    def test_skips_zero_actuals(self):
        assert mape([0, 100], [50, 110]) == 10.0

    def test_all_zero_actuals_returns_none(self):
        assert mape([0, 0], [1, 2]) is None


class TestBacktest:

    def test_seasonal_model_beats_naive_on_trending_series(self):
        # Trending + seasonal series: the model should beat seasonal-naive,
        # which ignores trend entirely.
        series = make_series(365, level=100.0, slope=0.3, dow_factors=WEEKEND_HEAVY)
        result = backtest_series(series, holdout_days=28)
        assert result["mape"] is not None
        assert result["mape"] < 5.0  # noiseless series → near-perfect fit
        assert result["mape"] <= result["baseline_mape"]

    def test_backtest_structure(self):
        result = backtest_series(make_series(120), holdout_days=14)
        assert result["holdout_days"] == 14
        assert len(result["points"]) == 14
        point = result["points"][0]
        assert set(point) == {"date", "actual", "predicted", "baseline"}

    def test_rejects_insufficient_history(self):
        with pytest.raises(ValueError):
            backtest_series(make_series(30), holdout_days=28)

    def test_handles_noisy_series(self):
        # Deterministic pseudo-noise; model should still land within sane MAPE
        series = [
            (d, y * (1 + 0.1 * math.sin(t * 1.7)))
            for t, (d, y) in enumerate(make_series(365, level=100.0, dow_factors=WEEKEND_HEAVY))
        ]
        result = backtest_series(series, holdout_days=28)
        assert result["mape"] is not None
        assert result["mape"] < 20.0
