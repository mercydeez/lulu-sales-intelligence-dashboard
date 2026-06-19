"""
Forecasting engine — tiered, backtested, deterministic.

Public API:
    from app.services.forecasting import forecast_series, backtest_and_select, available_models

Design principle (per product spec): every forecast is produced by a fitted
model whose error is measured against held-out actuals via a rolling backtest —
no random or hand-waved numbers. Models compete; the lowest-error one wins per
series, and its MAPE/WAPE travels with the forecast so it can be shown honestly.
"""
from .engine import (
    forecast_series,
    backtest_and_select,
    available_models,
    ForecastResult,
)

__all__ = [
    "forecast_series",
    "backtest_and_select",
    "available_models",
    "ForecastResult",
]
