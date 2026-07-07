"""
Forecasting engine internals.

A small registry of deterministic forecasters that share one interface
(`fit(history_df)` then `predict(horizon)`), a feature builder, and a
rolling-origin backtest that scores each model on held-out actuals (MAPE +
WAPE) and selects the winner per series.

Tiers:
  - seasonal_naive   : value from 7 days earlier (the honesty baseline)
  - seasonal_trend   : day-of-week seasonality x OLS trend (classical)
  - lightgbm         : gradient-boosted trees on lag/calendar/rolling features (ML)
  - lstm             : deep model (see deep.py), slots into the same interface

Nothing here uses randomness; given the same history the output is identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .calendar_features import uae_calendar_features, UAE_FEATURE_COLUMNS

LAGS = (1, 7, 14, 28)
ROLL = (7, 14, 28)


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def _calendar(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Base calendar features + the UAE retail-calendar features (E7-1). The UAE
    features are FUTURE-KNOWN (derivable from the date), so they are safe for
    recursive forecasting and never introduce target leakage."""
    base = pd.DataFrame(
        {
            "dow": idx.dayofweek,
            "dom": idx.day,
            "month": idx.month,
            "weekofyear": idx.isocalendar().week.astype(int).values,
            "is_weekend": (idx.dayofweek >= 5).astype(int),
        },
        index=idx,
    )
    uae = uae_calendar_features(idx)
    return pd.concat([base, uae], axis=1)


def _feature_columns(exog_cols: Optional[List[str]] = None) -> List[str]:
    """Model feature columns. UAE calendar features are always included (E7-1);
    `exog_cols` (e.g. weather) are appended only when exogenous features are
    supplied to _build_features — the default path is unchanged."""
    cols = ["dow", "dom", "month", "weekofyear", "is_weekend"]
    cols += list(UAE_FEATURE_COLUMNS)
    cols += [f"lag_{l}" for l in LAGS]
    cols += [f"rollmean_{w}" for w in ROLL]
    cols += [f"rollstd_{w}" for w in ROLL]
    if exog_cols:
        cols += list(exog_cols)
    return cols


def _build_features(series: pd.Series, exog: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """series: a daily, date-indexed float series. Returns a feature frame
    (lags/rolling are shifted to avoid leakage from the target day; calendar and
    exogenous features are future-known and used as-is).

    `exog`: an optional date-indexed DataFrame of exogenous features (e.g. weather
    from weather_features). Reindexed to the series; missing rows are neutral 0.
    Off by default so existing behaviour is byte-for-byte unchanged."""
    df = _calendar(series.index)
    for l in LAGS:
        df[f"lag_{l}"] = series.shift(l)
    shifted = series.shift(1)
    for w in ROLL:
        df[f"rollmean_{w}"] = shifted.rolling(w).mean()
        df[f"rollstd_{w}"] = shifted.rolling(w).std()
    if exog is not None and not exog.empty:
        aligned = exog.reindex(series.index).fillna(0.0)
        for c in aligned.columns:
            df[c] = aligned[c].values
    df["y"] = series.values
    return df


def _to_series(history: pd.DataFrame) -> pd.Series:
    """Normalize [date, sales] rows into a contiguous daily series (gaps -> 0)."""
    s = history.copy()
    s["date"] = pd.to_datetime(s["date"])
    s = s.groupby("date")["sales"].sum().sort_index()
    full = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(full, fill_value=0.0).astype(float)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class BaseForecaster:
    name = "base"
    tier = "baseline"
    available = True

    def fit(self, series: pd.Series) -> "BaseForecaster":
        self.series = series
        return self

    def predict(self, horizon: int) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class SeasonalNaive(BaseForecaster):
    name = "seasonal_naive"
    tier = "baseline"

    def predict(self, horizon: int) -> np.ndarray:
        last = self.series.values
        period = 7
        out = []
        for h in range(horizon):
            idx = len(last) - period + (h % period)
            out.append(last[idx] if idx >= 0 else last[-1])
        return np.clip(np.array(out, dtype=float), 0, None)


class SeasonalTrend(BaseForecaster):
    """Multiplicative day-of-week indices x OLS linear trend (deterministic)."""
    name = "seasonal_trend"
    tier = "classical"

    def fit(self, series: pd.Series) -> "SeasonalTrend":
        self.series = series
        vals = series.values.astype(float)
        dow = series.index.dayofweek.values
        overall = vals.mean() if vals.mean() > 0 else 1.0
        self.dow_idx = np.ones(7)
        for d in range(7):
            mask = dow == d
            if mask.any() and overall > 0:
                self.dow_idx[d] = (vals[mask].mean()) / overall
        self.dow_idx /= self.dow_idx.mean() if self.dow_idx.mean() > 0 else 1.0
        deseason = np.array(
            [v / self.dow_idx[d] if self.dow_idx[d] > 0 else v for v, d in zip(vals, dow)]
        )
        t = np.arange(len(deseason))
        if len(t) >= 2:
            self.slope, self.intercept = np.polyfit(t, deseason, 1)
        else:
            self.slope, self.intercept = 0.0, float(deseason[-1] if len(deseason) else 0.0)
        self._n = len(vals)
        self._last_date = series.index[-1]
        return self

    def predict(self, horizon: int) -> np.ndarray:
        out = []
        for h in range(1, horizon + 1):
            t = self._n - 1 + h
            day = (self._last_date + timedelta(days=h)).dayofweek
            point = (self.intercept + self.slope * t) * self.dow_idx[day]
            out.append(point)
        return np.clip(np.array(out, dtype=float), 0, None)


class LightGBMForecaster(BaseForecaster):
    """Gradient-boosted trees on lag/calendar/rolling features, forecast
    recursively. Guarded import: if lightgbm isn't installed it reports
    unavailable and the registry skips it (app never crashes)."""
    name = "lightgbm"
    tier = "ml"

    def __init__(self):
        try:
            import lightgbm  # noqa: F401
            self.available = True
        except Exception:
            self.available = False

    def fit(self, series: pd.Series) -> "LightGBMForecaster":
        import lightgbm as lgb

        self.series = series
        feats = _build_features(series).dropna()
        cols = _feature_columns()
        X, y = feats[cols], feats["y"]
        self._cols = cols
        self.model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        self.model.fit(X, y)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        working = self.series.copy()
        preds = []
        for _ in range(horizon):
            next_day = working.index[-1] + timedelta(days=1)
            extended = pd.concat([working, pd.Series([np.nan], index=[next_day])])
            row = _build_features(extended).iloc[[-1]][self._cols]
            yhat = float(self.model.predict(row)[0])
            yhat = max(0.0, yhat)
            preds.append(yhat)
            working = pd.concat([working, pd.Series([yhat], index=[next_day])])
        return np.array(preds, dtype=float)

    def importances(self) -> Dict[str, float]:
        if not hasattr(self, "model"):
            return {}
        return dict(zip(self._cols, [float(v) for v in self.model.feature_importances_]))


def available_models() -> List[BaseForecaster]:
    """Instantiate every model that can run in this environment. The DL tier is
    imported lazily so torch is only loaded if it's installed."""
    candidates: List[BaseForecaster] = [SeasonalNaive(), SeasonalTrend(), LightGBMForecaster()]
    try:
        from .deep import (
            LSTMForecaster,
            GRUForecaster,
            CNNForecaster,
            TCNForecaster,
            TransformerForecaster,
            NBEATSForecaster,
        )
        for cls in (
            LSTMForecaster,
            GRUForecaster,
            CNNForecaster,
            TCNForecaster,
            TransformerForecaster,
            NBEATSForecaster,
        ):
            candidates.append(cls())
    except Exception:
        pass
    return [m for m in candidates if getattr(m, "available", True)]


# ---------------------------------------------------------------------------
# Error metrics (computed only on real held-out actuals)
# ---------------------------------------------------------------------------
def _mape(actual: np.ndarray, pred: np.ndarray) -> Optional[float]:
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def _wape(actual: np.ndarray, pred: np.ndarray) -> Optional[float]:
    denom = np.abs(actual).sum()
    if denom == 0:
        return None
    return float(np.abs(actual - pred).sum() / denom * 100)


# ---------------------------------------------------------------------------
# Backtest + selection
# ---------------------------------------------------------------------------
# Width of the forward prediction band, derived from backtest residuals.
# 1.2816 ≈ the two-sided 80% interval of a normal distribution.
Z80 = 1.2816


@dataclass
class ForecastResult:
    model: str
    horizon: int
    points: List[Dict] = field(default_factory=list)
    scores: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    selected_mape: Optional[float] = None
    selected_wape: Optional[float] = None
    # Winner's predictions on the held-out test window vs the real values:
    # [{date, actual, predicted}] — the visual proof the model tracks reality.
    backtest: List[Dict] = field(default_factory=list)
    interval_pct: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "horizon": self.horizon,
            "points": self.points,
            "scores": self.scores,
            "selected_mape": self.selected_mape,
            "selected_wape": self.selected_wape,
            "backtest": self.backtest,
            "interval_pct": self.interval_pct,
        }


def backtest_and_select(history: pd.DataFrame, horizon: int = 14) -> ForecastResult:
    """Rolling-origin holdout: fit each model on all but the last `horizon`
    days, forecast them, score against the held-out actuals, and pick the
    lowest-WAPE model (falling back to MAPE, then the baseline)."""
    series = _to_series(history)
    if len(series) < max(LAGS) + horizon + 7:
        m = SeasonalTrend().fit(series)
        preds = m.predict(horizon)
        return _result(m.name, series, preds, horizon, {})

    train, test = series.iloc[:-horizon], series.iloc[-horizon:]
    actual = test.values
    scores: Dict[str, Dict[str, Optional[float]]] = {}
    preds_by_model: Dict[str, np.ndarray] = {}
    best_name, best_wape = None, np.inf

    for model in available_models():
        try:
            model.fit(train)
            pred = model.predict(horizon)
            preds_by_model[model.name] = pred
            mape, wape = _mape(actual, pred), _wape(actual, pred)
            scores[model.name] = {"mape": mape, "wape": wape, "tier": model.tier}
            if wape is not None and wape < best_wape:
                best_wape, best_name = wape, model.name
        except Exception as e:
            scores[model.name] = {"error": str(e)}

    if best_name is None:
        best_name = "seasonal_trend"

    # The winner's held-out predictions vs the real values + the residual spread
    # that sizes the forward band (both reuse values already computed above).
    win_pred = preds_by_model.get(best_name)
    backtest_points: List[Dict] = []
    resid_std: Optional[float] = None
    if win_pred is not None:
        backtest_points = [
            {"date": d.strftime("%Y-%m-%d"),
             "actual": round(float(a), 2),
             "predicted": round(float(p), 2)}
            for d, a, p in zip(test.index, actual, win_pred)
        ]
        resid_std = float(np.std(np.asarray(actual, dtype=float) - win_pred))

    winner = next((m for m in available_models() if m.name == best_name), SeasonalTrend())
    winner.fit(series)
    forecast = winner.predict(horizon)
    return _result(best_name, series, forecast, horizon, scores,
                   backtest=backtest_points, resid_std=resid_std)


def _result(name, series, preds, horizon, scores,
            backtest=None, resid_std=None) -> ForecastResult:
    last = series.index[-1]
    points = []
    for i, v in enumerate(preds):
        pt = {"date": (last + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
              "forecast": round(float(v), 2)}
        if resid_std is not None:
            margin = Z80 * resid_std
            pt["lower"] = round(max(0.0, float(v) - margin), 2)
            pt["upper"] = round(float(v) + margin, 2)
        points.append(pt)
    sel = scores.get(name, {}) if scores else {}
    return ForecastResult(
        model=name,
        horizon=horizon,
        points=points,
        scores=scores,
        selected_mape=sel.get("mape"),
        selected_wape=sel.get("wape"),
        backtest=backtest or [],
        interval_pct=80 if resid_std is not None else None,
    )


def forecast_series(history: pd.DataFrame, horizon: int = 14) -> ForecastResult:
    """Public entry point: history is a DataFrame with columns [date, sales]."""
    return backtest_and_select(history, horizon)


def _model_by_name(name: str) -> BaseForecaster:
    """A fresh, unfitted instance of the named model (fitting mutates state, so
    each rolling window needs its own)."""
    return next((m for m in available_models() if m.name == name), SeasonalTrend())


def rolling_accuracy(
    history: pd.DataFrame,
    horizon: int = 14,
    model_name: Optional[str] = None,
    points: int = 6,
) -> List[Dict]:
    """Rolling-origin trend for ONE model: score `model_name` on the last
    `points` non-overlapping held-out windows (step = horizon) and return
    [{date, accuracy}] oldest→newest. Answers "is our model holding up?" without
    re-selecting per window. Each window refits a fresh instance on the data
    before it and scores WAPE→accuracy on the held-out days."""
    series = _to_series(history)
    name = model_name or "seasonal_trend"
    step = horizon
    min_train = max(LAGS) + horizon + 7

    out: List[Dict] = []
    for k in range(points):
        end = len(series) - k * step
        train = series.iloc[: end - horizon]
        test = series.iloc[end - horizon : end]
        if len(test) != horizon or len(train) < min_train:
            continue
        try:
            model = _model_by_name(name).fit(train)
            pred = model.predict(horizon)
            wape = _wape(test.values, pred)
            if wape is None:
                continue
            out.append({
                "date": test.index[-1].strftime("%Y-%m-%d"),
                "accuracy": round(max(0.0, 100.0 - wape), 1),
            })
        except Exception:
            continue

    out.reverse()  # oldest → newest
    return out
