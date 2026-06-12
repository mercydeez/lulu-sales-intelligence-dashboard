"""
Sales forecasting — explainable seasonal decomposition model.

Model (seasonal_v2):
  1. Weekly seasonality: multiplicative day-of-week indices learned from the
     full history (mean sales per weekday / overall mean, normalized).
  2. Trend: ordinary least squares on the deseasonalized series over the most
     recent TREND_WINDOW_DAYS.
  3. Forecast: (level + slope * t) * dow_index, floored at zero.
  4. Confidence: 95% interval from the in-sample residual standard deviation.

Backtesting: hold out the last N days, fit on the rest, and report MAPE next
to a seasonal-naive baseline (value from 7 days earlier) so the model has to
prove it beats the obvious heuristic.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select

from app.services.database import async_session
from app.services.redis_client import cache_get, cache_set
from app.models.sales import Sale
from app.config import get_settings

settings = get_settings()

TREND_WINDOW_DAYS = 365
MIN_TRAINING_DAYS = 14


# =============================================================================
# Pure model math (no I/O — unit-testable)
# =============================================================================

def fit_dow_indices(series: Sequence[Tuple[date, float]]) -> List[float]:
    """Multiplicative day-of-week indices (Mon=0..Sun=6), normalized to mean 1."""
    totals = [0.0] * 7
    counts = [0] * 7
    for d, y in series:
        totals[d.weekday()] += y
        counts[d.weekday()] += 1

    overall_mean = sum(totals) / max(sum(counts), 1)
    if overall_mean <= 0:
        return [1.0] * 7

    indices = [
        (totals[i] / counts[i]) / overall_mean if counts[i] else 1.0
        for i in range(7)
    ]
    # Normalize so the indices average to exactly 1 (keeps level unbiased)
    mean_idx = sum(indices) / 7
    return [i / mean_idx if mean_idx > 0 else 1.0 for i in indices]


def fit_trend(deseasonalized: Sequence[float]) -> Tuple[float, float]:
    """OLS fit y = intercept + slope * t over t = 0..n-1."""
    n = len(deseasonalized)
    if n < 2:
        return (deseasonalized[0] if n else 0.0), 0.0

    t_mean = (n - 1) / 2
    y_mean = sum(deseasonalized) / n
    ss_tt = sum((t - t_mean) ** 2 for t in range(n))
    ss_ty = sum((t - t_mean) * (y - y_mean) for t, y in enumerate(deseasonalized))
    slope = ss_ty / ss_tt if ss_tt > 0 else 0.0
    return y_mean - slope * t_mean, slope


class SeasonalTrendModel:
    """Weekly-seasonality + linear-trend forecaster over a daily series."""

    def __init__(self, series: Sequence[Tuple[date, float]]):
        if len(series) < MIN_TRAINING_DAYS:
            raise ValueError(
                f"Need at least {MIN_TRAINING_DAYS} days of history, got {len(series)}"
            )
        self.series = sorted(series, key=lambda p: p[0])
        self.dow_indices = fit_dow_indices(self.series)

        window = self.series[-TREND_WINDOW_DAYS:]
        deseasonalized = [
            y / self.dow_indices[d.weekday()] if self.dow_indices[d.weekday()] > 0 else y
            for d, y in window
        ]
        self.intercept, self.slope = fit_trend(deseasonalized)
        self._window_len = len(window)

        # In-sample residual std (original scale) for confidence intervals
        residuals = [
            y - self._point_forecast(t, d)
            for t, (d, y) in enumerate(window)
        ]
        self.residual_std = (
            (sum(r ** 2 for r in residuals) / len(residuals)) ** 0.5 if residuals else 0.0
        )

    def _point_forecast(self, t: int, day: date) -> float:
        level = self.intercept + self.slope * t
        return max(0.0, level * self.dow_indices[day.weekday()])

    def forecast(self, days: int) -> List[Dict]:
        last_date = self.series[-1][0]
        out = []
        for h in range(1, days + 1):
            pred_date = last_date + timedelta(days=h)
            point = self._point_forecast(self._window_len - 1 + h, pred_date)
            out.append({
                "prediction_date": pred_date.isoformat(),
                "predicted_sales": round(point, 2),
                "confidence_lower": max(0.0, round(point - 1.96 * self.residual_std, 2)),
                "confidence_upper": round(point + 1.96 * self.residual_std, 2),
            })
        return out


def mape(actuals: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    """Mean absolute percentage error over points with non-zero actuals."""
    pairs = [(a, p) for a, p in zip(actuals, predicted) if a != 0]
    if not pairs:
        return None
    return round(100 * sum(abs((a - p) / a) for a, p in pairs) / len(pairs), 2)


def backtest_series(
    series: Sequence[Tuple[date, float]], holdout_days: int
) -> Dict:
    """Fit on all but the last holdout_days, forecast them, report MAPE
    against the actuals and against a seasonal-naive baseline (t-7)."""
    series = sorted(series, key=lambda p: p[0])
    if len(series) < MIN_TRAINING_DAYS + holdout_days:
        raise ValueError(
            f"Need at least {MIN_TRAINING_DAYS + holdout_days} days for a "
            f"{holdout_days}-day backtest, got {len(series)}"
        )

    train, holdout = series[:-holdout_days], series[-holdout_days:]
    model = SeasonalTrendModel(train)
    forecasts = model.forecast(holdout_days)

    actuals = [y for _, y in holdout]
    predicted = [f["predicted_sales"] for f in forecasts]

    # Seasonal-naive baseline: the value observed 7 days before each holdout day
    by_date = dict(series)
    baseline = [by_date.get(d - timedelta(days=7), train[-1][1]) for d, _ in holdout]

    return {
        "model_version": SalesPredictor.MODEL_VERSION,
        "holdout_days": holdout_days,
        "mape": mape(actuals, predicted),
        "baseline_mape": mape(actuals, baseline),
        "points": [
            {
                "date": d.isoformat(),
                "actual": y,
                "predicted": f["predicted_sales"],
                "baseline": b,
            }
            for (d, y), f, b in zip(holdout, forecasts, baseline)
        ],
    }


# =============================================================================
# Service (I/O wrapper)
# =============================================================================

class SalesPredictor:
    """Forecasting service: loads a store/item daily series and runs the model."""

    MODEL_VERSION = "seasonal_v2.0"
    CACHE_KEY_PREFIX = "prediction"
    CACHE_TTL = 3600  # 1 hour

    async def _get_daily_series(self, store_id: int, item_id: int) -> List[Tuple[date, float]]:
        """Daily totals — aggregated so multiple streaming rows per day don't
        distort the series."""
        async with async_session() as session:
            result = await session.execute(
                select(Sale.date, func.sum(Sale.sales).label("sales"))
                .where(Sale.store_id == store_id)
                .where(Sale.item_id == item_id)
                .group_by(Sale.date)
                .order_by(Sale.date)
            )
            return [(row.date, float(row.sales)) for row in result.fetchall()]

    async def predict(self, store_id: int, item_id: int, days: int = None) -> List[Dict]:
        """Generate sales predictions"""
        days = days or settings.forecast_days
        cache_key = f"{self.CACHE_KEY_PREFIX}:{self.MODEL_VERSION}:{store_id}:{item_id}:{days}"

        cached = await cache_get(cache_key)
        if cached:
            return cached

        series = await self._get_daily_series(store_id, item_id)
        if len(series) < MIN_TRAINING_DAYS:
            return []

        predictions = SeasonalTrendModel(series).forecast(days)
        if predictions:
            await cache_set(cache_key, predictions, self.CACHE_TTL)
        return predictions

    async def backtest(self, store_id: int, item_id: int, holdout_days: int = 28) -> Optional[Dict]:
        """Walk-forward holdout evaluation. Returns None when there isn't
        enough history."""
        cache_key = f"backtest:{self.MODEL_VERSION}:{store_id}:{item_id}:{holdout_days}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        series = await self._get_daily_series(store_id, item_id)
        try:
            result = backtest_series(series, holdout_days)
        except ValueError:
            return None

        await cache_set(cache_key, result, self.CACHE_TTL)
        return result
