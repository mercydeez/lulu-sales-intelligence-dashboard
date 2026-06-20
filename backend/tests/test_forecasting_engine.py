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
