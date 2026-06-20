"""
B1.7 — forecasts wired across the product.

Covers the pure forecast-derived math (uplift) and confirms the new
forecast-driven endpoints are registered on the app, so the engine reaches
inventory reorder, promotion uplift, the dashboard projection, and the
assistant. Live-DB behaviour is exercised by the integration suite.
"""
import datetime

import pytest

from app.services import forecast_service as fs
from app.services.predictor import SeasonalTrendModel


def _synthetic_series(days: int = 120):
    base = datetime.date(2024, 1, 1)
    # Weekly seasonality + gentle upward trend, deterministic.
    return [(base + datetime.timedelta(days=i), 100 + (i % 7) * 10 + i * 0.5)
            for i in range(days)]


def test_expected_uplift_basic():
    out = fs.expected_uplift(actual_units=1200, baseline_units=1000)
    assert out["uplift_units"] == 200
    assert out["uplift_pct"] == 20.0
    assert out["baseline_units"] == 1000


def test_expected_uplift_zero_baseline_is_safe():
    out = fs.expected_uplift(actual_units=50, baseline_units=0)
    assert out["uplift_pct"] == 0.0
    assert out["uplift_units"] == 50


def test_predictor_powers_baseline_forecast():
    """The same lightweight engine the service uses produces a horizon-length,
    non-negative forecast — the baseline/projection inputs."""
    points = SeasonalTrendModel(_synthetic_series()).forecast(14)
    assert len(points) == 14
    assert all(p["predicted_sales"] >= 0 for p in points)
    assert all("confidence_lower" in p and "confidence_upper" in p for p in points)


def test_forecast_endpoints_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/kpis/projection" in paths
    assert "/api/inventory/reorder-suggestions" in paths
    assert "/api/promotions/uplift-baseline" in paths


def test_forecast_narrative_branch_in_assistant():
    """The assistant detects forecast intent and has an engine-driven branch."""
    from app.services.ai_assistant import detect_intent
    info = detect_intent("what's the forecast for next week?")
    assert "prediction" in info["intents"]
