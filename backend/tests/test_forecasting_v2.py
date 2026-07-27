"""
E7-1 — Forecasting v2 (UAE calendar + weather foundation + v2 accuracy).

All tests are PURE: deterministic, no DB, no network, and no hard dependency on
torch/lightgbm (LightGBM-only assertions are guarded with importorskip). They run
in the normal backend CI job.
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.services.forecasting.calendar_features import (
    uae_calendar_features,
    UAE_FEATURE_COLUMNS,
    lunar_dates_are_approximate,
)
from app.services.forecasting.weather_features import weather_features, WEATHER_FEATURE_COLUMNS
from app.services.forecasting.engine import _feature_columns, _build_features, _to_series
from app.services.forecasting import diagnostics as diag


# ---------------------------------------------------------------------------
# Calendar features
# ---------------------------------------------------------------------------
def _cal(dates):
    return uae_calendar_features(pd.to_datetime(dates))


def test_ramadan_dates_flagged():
    f = _cal(["2026-02-18", "2026-03-19", "2026-02-01"])
    assert f["uae_is_ramadan"].tolist() == [1, 1, 0]


def test_ramadan_day_increments():
    f = _cal(["2026-02-18", "2026-02-19", "2026-02-20"])
    assert f["uae_ramadan_day"].tolist() == [1, 2, 3]


def test_pre_ramadan_14d_window():
    # Ramadan starts 2026-02-18: 10 days before is inside the 14d pre-window,
    # 17 days before is outside it.
    f = _cal(["2026-02-08", "2026-02-01", "2026-01-01"])
    assert f["uae_pre_ramadan_14d"].tolist() == [1, 0, 0]
    assert f["uae_days_to_ramadan"].loc["2026-02-08"] == 10


def test_post_ramadan_14d_window():
    # Ramadan ends 2026-03-19; a few days after is inside the 14d post-window.
    f = _cal(["2026-03-25", "2026-04-10"])
    assert f["uae_post_ramadan_14d"].tolist() == [1, 0]
    assert f["uae_days_from_ramadan"].loc["2026-03-25"] == 6


def test_eid_fitr_and_adha_flagged():
    f = _cal(["2026-03-21", "2026-05-28", "2026-07-01"])
    assert f["uae_is_eid_fitr"].tolist() == [1, 0, 0]
    assert f["uae_is_eid_adha"].tolist() == [0, 1, 0]


def test_dsf_flagged_including_cross_year():
    # DSF spans 2026-12-15 .. 2027-01-31 — a January-2027 date must still flag.
    f = _cal(["2026-12-20", "2027-01-10", "2027-02-15"])
    assert f["uae_is_dsf"].tolist() == [1, 1, 0]


def test_national_day_and_back_to_school_flags():
    f = _cal(["2026-12-02", "2026-08-20", "2026-10-01"])
    assert f["uae_is_national_day"].tolist() == [1, 0, 0]
    assert f["uae_is_back_to_school"].tolist() == [0, 1, 0]


def test_non_event_dates_are_neutral():
    f = _cal(["2026-10-15"])  # no UAE season on this date
    assert int(f.sum(axis=1).iloc[0]) == 0  # every feature is 0


def test_leap_year_range_does_not_crash():
    idx = pd.date_range("2024-02-01", "2024-03-05", freq="D")  # includes Feb 29
    f = uae_calendar_features(idx)
    assert len(f) == len(idx)
    assert list(f.columns) == UAE_FEATURE_COLUMNS
    assert not f.isnull().any().any()


def test_lunar_date_approx_true_for_approximate_events():
    f = _cal(["2026-02-20", "2026-03-21", "2026-08-20"])  # ramadan, eid, summer
    assert f["uae_lunar_date_approx"].tolist() == [1, 1, 0]
    assert lunar_dates_are_approximate() is True


def test_out_of_calendar_range_is_neutral_not_crash():
    f = _cal(["2019-06-01", "2030-06-01"])  # far before/after known calendar
    # Every EVENT feature is neutral 0 outside the known calendar. uae_is_weekend
    # is a pure day-of-week signal (always defined), so it is excluded here.
    event_cols = [c for c in UAE_FEATURE_COLUMNS if c != "uae_is_weekend"]
    assert int(f[event_cols].abs().sum().sum()) == 0


# ---------------------------------------------------------------------------
# Weather features
# ---------------------------------------------------------------------------
def test_weather_noop_is_neutral():
    idx = pd.date_range("2026-02-01", periods=5, freq="D")
    w = weather_features(idx)
    assert list(w.columns) == WEATHER_FEATURE_COLUMNS
    assert (w["weather_available"] == 0).all()
    assert (w["weather_temp_c"] == 0).all() and (w["weather_rain_mm"] == 0).all()


def test_weather_injected_observations_are_deterministic():
    idx = pd.date_range("2026-02-01", periods=3, freq="D")
    obs = {
        "2026-02-01": {"temp_c": 24.0, "rain_mm": 1.5, "humidity_pct": 60},
        "2026-02-02": {"temp_c": 26.0, "rain_mm": 0.0, "humidity_pct": 55},
        # 2026-02-03 intentionally missing -> neutral row
    }
    w = weather_features(idx, observations=obs)
    assert w["weather_available"].tolist() == [1, 1, 0]
    assert w["weather_temp_c"].tolist() == [24.0, 26.0, 0.0]
    assert w["weather_humidity_pct"].tolist() == [60.0, 55.0, 0.0]


def test_weather_missing_dates_degrade_to_neutral():
    idx = pd.date_range("2026-02-01", periods=2, freq="D")
    w = weather_features(idx, observations={"2020-01-01": {"temp_c": 30}})
    assert (w["weather_available"] == 0).all()


# ---------------------------------------------------------------------------
# Forecasting engine feature wiring (no leakage; no torch/lightgbm required)
# ---------------------------------------------------------------------------
def _series(n=60, start="2026-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.Series([100.0 + i for i in range(n)], index=idx)


def test_feature_columns_include_uae_features():
    cols = _feature_columns()
    assert set(UAE_FEATURE_COLUMNS).issubset(cols)


def test_build_features_include_uae_and_are_leak_free():
    s = _series()
    f = _build_features(s)
    assert set(UAE_FEATURE_COLUMNS).issubset(f.columns)
    # lag_1 is yesterday's value (shifted), never today's -> no target leakage
    assert np.isnan(f["lag_1"].iloc[0])
    assert f["lag_1"].iloc[10] == s.iloc[9]
    # rollmean_7 uses values strictly BEFORE the current day (shift(1) then roll)
    assert f["rollmean_7"].iloc[7] == pytest.approx(s.iloc[0:7].mean())


def test_build_features_optional_exog_appends_columns():
    s = _series()
    exog = weather_features(s.index, observations={s.index[0].strftime("%Y-%m-%d"): {"temp_c": 25}})
    f = _build_features(s, exog=exog)
    assert set(WEATHER_FEATURE_COLUMNS).issubset(f.columns)
    # default (no exog) must NOT include weather columns -> backward compatible
    assert not set(WEATHER_FEATURE_COLUMNS).issubset(_build_features(s).columns)


def test_lightgbm_frame_can_include_uae_columns_when_installed():
    pytest.importorskip("lightgbm")
    from app.services.forecasting.engine import LightGBMForecaster
    m = LightGBMForecaster()
    m.fit(_to_series(pd.DataFrame({"date": _series(120).index, "sales": _series(120).values})))
    assert set(UAE_FEATURE_COLUMNS).issubset(set(m._cols))


# ---------------------------------------------------------------------------
# Diagnostics — v2 accuracy helpers (pure)
# ---------------------------------------------------------------------------
def test_wape_improvement_is_safe_and_signed():
    assert diag.wape_improvement_vs_baseline_pct(20.0, 10.0) == 50.0   # model beats baseline
    assert diag.wape_improvement_vs_baseline_pct(10.0, 20.0) == -100.0  # model worse
    assert diag.wape_improvement_vs_baseline_pct(0.0, 10.0) is None     # zero baseline safe
    assert diag.wape_improvement_vs_baseline_pct(None, 10.0) is None


def test_ramadan_accuracy_present_when_backtest_has_ramadan():
    bt = [
        {"date": "2026-02-20", "actual": 100.0, "predicted": 90.0},
        {"date": "2026-02-21", "actual": 100.0, "predicted": 110.0},
        {"date": "2026-07-01", "actual": 50.0, "predicted": 55.0},  # not Ramadan
    ]
    r = diag.ramadan_window_accuracy(bt)
    assert r["ramadan_accuracy_reason"] == "ok"
    assert r["ramadan_eval_days"] == 2  # only the two Ramadan days scored
    assert r["ramadan_mape"] == 10.0 and r["ramadan_accuracy"] is not None


def test_ramadan_accuracy_none_when_no_ramadan_dates():
    bt = [{"date": "2026-07-01", "actual": 50.0, "predicted": 55.0}]
    r = diag.ramadan_window_accuracy(bt)
    assert r["ramadan_accuracy"] is None
    assert r["ramadan_accuracy_reason"] == "no_ramadan_dates_in_backtest_window"
    assert r["ramadan_eval_days"] == 0


def test_ramadan_accuracy_empty_backtest_is_safe():
    r = diag.ramadan_window_accuracy([])
    assert r["ramadan_accuracy"] is None
    assert r["ramadan_accuracy_reason"] == "no_backtest_window"


def test_methodology_note_is_honest():
    note = diag.METHODOLOGY_NOTE.lower()
    assert "seasonal-naive" in note
    assert "approximate" in note and "lunar" in note


def test_forecast_summary_short_history_is_backward_compatible_and_v2():
    # Short history -> engine fallback (no model zoo, fast, torch/lightgbm free).
    hist = pd.DataFrame({"date": _series(30).index, "sales": _series(30).values})
    summ = diag.forecast_summary(hist, horizon=14)
    # backward-compatible fields still present
    for k in ("selected_model", "accuracy", "mape", "leaderboard", "forecast", "backtest", "interval_pct"):
        assert k in summ
    # v2 additive fields present with safe/honest defaults
    assert summ["forecasting_version"] == "v3_ensemble"
    assert summ["baseline_model"] == "seasonal_naive"
    assert summ["calendar_feature_summary"]["uses_uae_calendar"] is True
    assert summ["calendar_feature_summary"]["lunar_dates_approximate"] is True
    assert summ["ramadan_accuracy_reason"] in (
        "no_backtest_window", "no_ramadan_dates_in_backtest_window", "ok"
    )


# ---------------------------------------------------------------------------
# Analytics model-metrics payload
# ---------------------------------------------------------------------------
def test_empty_model_metrics_includes_v2_fields():
    from app.routes.analytics import _empty_model_metrics
    m = _empty_model_metrics()
    for k in ("forecasting_version", "baseline_model", "baseline_wape",
              "selected_model_wape", "wape_improvement_vs_baseline_pct",
              "ramadan_accuracy", "ramadan_accuracy_reason",
              "calendar_feature_summary", "methodology_note"):
        assert k in m
    assert m["calendar_feature_summary"]["uses_uae_calendar"] is True
    # existing fields remain untouched (backward compatibility)
    for k in ("accuracy", "selected_model", "mape", "leaderboard", "forecast",
              "backtest", "feature_importance", "classifier", "business_impact"):
        assert k in m


def test_compute_model_metrics_sync_populates_v2_fields():
    from app.routes.analytics import _compute_model_metrics_sync
    hist_records = [
        {"date": d.strftime("%Y-%m-%d"), "sales": float(v)}
        for d, v in zip(_series(30).index, _series(30).values)
    ]
    out = _compute_model_metrics_sync(hist_records, [], [], [], avg_price=10.0, horizon=14)
    assert out["forecasting_version"] == "v3_ensemble"
    assert "ramadan_accuracy_reason" in out
    assert out["calendar_feature_summary"]["lunar_dates_approximate"] is True


def test_model_metrics_route_registered():
    from app.routes.analytics import router
    paths = {r.path for r in router.routes}
    assert "/model-metrics" in paths  # mounts at /api/analytics/model-metrics
