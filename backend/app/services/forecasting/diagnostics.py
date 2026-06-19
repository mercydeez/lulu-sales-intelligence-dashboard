"""
Model diagnostics for the Forecast Lab tab.

Assembles an executive + technical summary from the forecasting engine, plus a
stockout-risk *classification* model (so a confusion matrix is genuinely
meaningful — forecasting alone is regression). Everything is deterministic and
degrades gracefully: any piece that can't be computed returns empty rather than
raising, so the tab always renders.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .engine import (
    forecast_series,
    _to_series,
    _build_features,
    _feature_columns,
    SeasonalTrend,
    LightGBMForecaster,
    _wape,
)

_FEATURE_LABELS = {
    "dow": "Day of week",
    "dom": "Day of month",
    "month": "Month",
    "weekofyear": "Week of year",
    "is_weekend": "Weekend",
    "lag_1": "Yesterday's sales",
    "lag_7": "Same day last week",
    "lag_14": "Two weeks ago",
    "lag_28": "Four weeks ago",
    "rollmean_7": "7-day average",
    "rollmean_14": "14-day average",
    "rollmean_28": "28-day average",
    "rollstd_7": "7-day volatility",
    "rollstd_14": "14-day volatility",
    "rollstd_28": "28-day volatility",
}


def _acc_from_wape(wape: Optional[float]) -> Optional[float]:
    if wape is None:
        return None
    return max(0.0, round(100 - wape, 1))


def forecast_summary(history: pd.DataFrame, horizon: int = 14) -> dict:
    """Run the engine's backtest and shape it for the exec view + leaderboard."""
    res = forecast_series(history, horizon).to_dict()
    leaderboard = []
    for name, sc in (res.get("scores") or {}).items():
        if isinstance(sc, dict) and sc.get("wape") is not None:
            leaderboard.append({
                "model": name,
                "tier": sc.get("tier"),
                "accuracy": _acc_from_wape(sc.get("wape")),
                "mape": round(sc["mape"], 1) if sc.get("mape") is not None else None,
            })
    leaderboard.sort(key=lambda x: (x["accuracy"] is not None, x["accuracy"] or 0), reverse=True)
    return {
        "selected_model": res.get("model"),
        "accuracy": _acc_from_wape(res.get("selected_wape")),
        "mape": round(res["selected_mape"], 1) if res.get("selected_mape") is not None else None,
        "leaderboard": leaderboard,
        "forecast": res.get("points", []),
    }


def feature_importance(history: pd.DataFrame) -> List[dict]:
    """LightGBM feature importances, normalized to %, with friendly labels."""
    try:
        m = LightGBMForecaster()
        if not getattr(m, "available", False):
            return []
        m.fit(_to_series(history))
        imp = m.importances()
        total = sum(imp.values()) or 1.0
        rows = [
            {"feature": _FEATURE_LABELS.get(k, k), "weight": round(v / total * 100, 1)}
            for k, v in imp.items()
        ]
        rows.sort(key=lambda x: x["weight"], reverse=True)
        return rows[:8]
    except Exception:
        return []


def classical_accuracy(history: pd.DataFrame, holdout: int = 14) -> Optional[float]:
    """Cheap, deterministic accuracy for one series (used for the heatmap)."""
    try:
        series = _to_series(history)
        if len(series) < holdout + 30:
            return None
        train, test = series.iloc[:-holdout], series.iloc[-holdout:]
        pred = SeasonalTrend().fit(train).predict(holdout)
        return _acc_from_wape(_wape(test.values, pred))
    except Exception:
        return None


def stockout_classifier(history: pd.DataFrame, holdout: int = 30) -> dict:
    """A real classification model: predict 'low-stock-risk day' (daily units in
    the bottom 20%) from calendar/lag features. Backtested on a holdout to
    produce an honest confusion matrix + precision/recall/F1."""
    try:
        series = _to_series(history)
        if len(series) < 90:
            return {}
        feats = _build_features(series).dropna()
        cols = _feature_columns()
        thr = float(np.percentile(series.values, 20))
        y = (feats["y"].values <= thr).astype(int)
        X = feats[cols].values
        if len(X) <= holdout + 20:
            return {}
        Xtr, ytr = X[:-holdout], y[:-holdout]
        Xte, yte = X[-holdout:], y[-holdout:]

        try:
            import lightgbm as lgb
            clf = lgb.LGBMClassifier(
                n_estimators=200, learning_rate=0.05, random_state=42, n_jobs=-1, verbose=-1
            )
            clf.fit(Xtr, ytr)
            pred = clf.predict(Xte).astype(int)
            model_name = "lightgbm_classifier"
        except Exception:
            roll = feats["rollmean_7"].values[-holdout:]
            pred = (roll <= thr).astype(int)
            model_name = "rule_baseline"

        tp = int(((pred == 1) & (yte == 1)).sum())
        tn = int(((pred == 0) & (yte == 0)).sum())
        fp = int(((pred == 1) & (yte == 0)).sum())
        fn = int(((pred == 0) & (yte == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        acc = (tp + tn) / max(1, tp + tn + fp + fn)
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return {
            "model": model_name,
            "labels": ["Normal", "Low-stock risk"],
            "matrix": [[tn, fp], [fn, tp]],   # rows=actual, cols=predicted
            "precision": round(prec * 100, 1),
            "recall": round(rec * 100, 1),
            "accuracy": round(acc * 100, 1),
            "f1": round(f1 * 100, 1),
            "threshold_units": round(thr, 1),
            "tested_days": int(holdout),
        }
    except Exception:
        return {}


def business_impact(forecast_points, classifier, avg_price, recent_daily_units) -> dict:
    """Translate model output into money, with the formula spelled out so a
    non-technical reader sees exactly HOW each number is derived."""
    try:
        horizon = len(forecast_points)
        proj_units = sum(p.get("forecast", 0) for p in forecast_points)
        price = float(avg_price or 0)
        proj_revenue = proj_units * price
        avg_daily_revenue = float(recent_daily_units or 0) * price
        tp = risk_total = 0
        if classifier and classifier.get("matrix"):
            m = classifier["matrix"]
            tp = m[1][1]
            risk_total = m[1][0] + m[1][1]
        revenue_protected = tp * avg_daily_revenue
        return {
            "horizon_days": horizon,
            "projected_units": int(round(proj_units)),
            "avg_unit_price_aed": round(price, 2),
            "projected_revenue_aed": round(proj_revenue, 2),
            "revenue_formula": f"{int(round(proj_units)):,} forecast units × AED {round(price, 2)} avg price",
            "risk_days_caught": int(tp),
            "risk_days_total": int(risk_total),
            "avg_daily_revenue_aed": round(avg_daily_revenue, 2),
            "revenue_protected_aed": round(revenue_protected, 2),
            "protected_formula": f"{int(tp)} risk days the model caught × AED {round(avg_daily_revenue, 2)} avg daily revenue",
        }
    except Exception:
        return {}
