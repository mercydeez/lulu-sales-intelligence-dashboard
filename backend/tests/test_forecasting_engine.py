"""
Forecasting engine tests (B1.2) — registry + DL-tier sanity.

Covers the newer `app.services.forecasting` engine (the older
`app.services.predictor` is covered by test_predictor.py). The DL tier needs
torch, so the whole module skips cleanly where torch isn't installed.
"""
import math

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from app.services.forecasting.engine import (  # noqa: E402
    available_models,
    backtest_and_select,
    rolling_accuracy,
    _to_series,
)
from app.services.forecasting.deep import (  # noqa: E402
    TCNForecaster,
    TransformerForecaster,
    NBEATSForecaster,
)

NEW_DL_MODELS = (TCNForecaster, TransformerForecaster, NBEATSForecaster)


def _synthetic_history(days: int = 400) -> pd.DataFrame:
    """A deterministic seasonal+trend daily series as [date, sales] rows."""
    dow_factors = [0.9, 0.85, 0.9, 0.95, 1.05, 1.2, 1.15]
    start = pd.Timestamp("2024-01-01")
    rows = []
    for t in range(days):
        d = start + pd.Timedelta(days=t)
        level = 100.0 + 0.2 * t
        seasonal = dow_factors[d.dayofweek]
        wobble = 1 + 0.05 * math.sin(t * 1.3)
        rows.append({"date": d, "sales": level * seasonal * wobble})
    return pd.DataFrame(rows)


def _stationary_history(days: int = 400) -> pd.DataFrame:
    """A deterministic *stationary* series with strong weekly seasonality (no
    trend), so low-demand 'risk' days recur in every window — including the
    held-out tail. The classifier's bottom-20% label therefore has both classes
    in the holdout, which is what ROC/PR curves require."""
    dow_factors = [0.55, 0.6, 0.7, 0.9, 1.1, 1.75, 1.7]  # Mon/Tue low, weekend high
    start = pd.Timestamp("2024-01-01")
    rows = []
    for t in range(days):
        d = start + pd.Timedelta(days=t)
        val = 100.0 * dow_factors[d.dayofweek] * (1 + 0.05 * math.sin(t * 1.3))
        rows.append({"date": d, "sales": val})
    return pd.DataFrame(rows)


def test_registry_includes_new_dl_models():
    names = {m.name for m in available_models()}
    assert {"tcn", "transformer", "nbeats"}.issubset(names)
    # all DL forecasters report the dl tier
    for m in available_models():
        if m.name in {"tcn", "transformer", "nbeats"}:
            assert m.tier == "dl"


@pytest.mark.parametrize("cls", NEW_DL_MODELS)
def test_new_dl_model_predicts_valid_horizon(cls):
    series = _to_series(_synthetic_history())
    horizon = 14
    preds = cls().fit(series).predict(horizon)
    assert len(preds) == horizon
    assert np.all(np.isfinite(preds))
    assert np.all(preds >= 0)


def test_backtest_selects_a_registered_model():
    valid = {m.name for m in available_models()}
    result = backtest_and_select(_synthetic_history(), horizon=14)
    assert result.model in valid
    assert len(result.points) == 14
    # the new DL models should have competed (have a score entry)
    assert {"tcn", "transformer", "nbeats"}.issubset(set(result.scores))


def test_backtest_returns_held_out_actual_vs_predicted():
    horizon = 14
    result = backtest_and_select(_synthetic_history(), horizon=horizon)
    assert len(result.backtest) == horizon
    for pt in result.backtest:
        assert set(pt) == {"date", "actual", "predicted"}
        assert pt["actual"] >= 0 and pt["predicted"] >= 0


def test_forward_points_carry_prediction_band():
    result = backtest_and_select(_synthetic_history(), horizon=14)
    assert result.interval_pct == 80
    for pt in result.points:
        assert "lower" in pt and "upper" in pt
        assert pt["lower"] <= pt["forecast"] <= pt["upper"]
        assert pt["lower"] >= 0


def test_stockout_classifier_returns_curves_and_threshold():
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")
    from app.services.forecasting import diagnostics as diag

    # Stationary series so the held-out tail contains both classes (risk + normal).
    clf = diag.stockout_classifier(_stationary_history())
    assert clf, "classifier should return a payload for 400 days of history"
    assert clf["model"] in {"lightgbm_classifier", "rule_baseline"}
    assert "threshold" in clf
    # curves require both classes in the holdout (guaranteed by the stationary series)
    assert clf["roc"] and clf["pr"]
    for p in clf["roc"]:
        assert 0 <= p["fpr"] <= 1 and 0 <= p["tpr"] <= 1
    for p in clf["pr"]:
        assert 0 <= p["recall"] <= 1 and 0 <= p["precision"] <= 1
    assert 0 <= clf["roc_auc"] <= 1
    assert 0 <= clf["average_precision"] <= 1


def test_accuracy_by_group_scores_each_group():
    from app.services.forecasting import diagnostics as diag

    # 2 stores × 2 categories over enough days for classical_accuracy.
    base = _stationary_history(120)
    records = []
    for sid in (1, 2):
        for cat in ("Dairy", "Bakery"):
            for _, row in base.iterrows():
                records.append({
                    "store_id": sid, "store_name": f"Store {sid}", "category": cat,
                    "date": row["date"], "sales": row["sales"],
                })
    out = diag.accuracy_by_group(records, ["store_id", "store_name", "category"])
    assert len(out) == 4  # one entry per (store, category)
    for entry in out:
        assert set(entry) == {"store_id", "store_name", "category", "accuracy"}
        assert entry["accuracy"] is None or 0 <= entry["accuracy"] <= 100


def test_rolling_accuracy_returns_ascending_trend():
    history = _synthetic_history()
    winner = backtest_and_select(history, horizon=14).model
    trend = rolling_accuracy(history, horizon=14, model_name=winner, points=6)
    assert len(trend) >= 2
    for pt in trend:
        assert set(pt) == {"date", "accuracy"}
        assert 0 <= pt["accuracy"] <= 100
    dates = [pt["date"] for pt in trend]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
