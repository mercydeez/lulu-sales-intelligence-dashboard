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
    rolling_accuracy,
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
        "backtest": res.get("backtest", []),
        "interval_pct": res.get("interval_pct"),
    }


def accuracy_over_time(
    history: pd.DataFrame, horizon: int, model_name: Optional[str], points: int = 6
) -> List[dict]:
    """Rolling-origin accuracy trend for the selected model. Empty on failure or
    when no model is selected (degrades gracefully like the other diagnostics)."""
    if not model_name:
        return []
    try:
        return rolling_accuracy(history, horizon, model_name, points)
    except Exception:
        return []


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


def accuracy_by_group(
    records: List[dict], group_fields: List[str], holdout: int = 14
) -> List[dict]:
    """Per-group forecast accuracy. Groups raw `[{...group_fields, date, sales}]`
    rows by the tuple of `group_fields`, scores each group's daily series with
    `classical_accuracy`, and returns `[{**group_fields, "accuracy": ...}]`.
    Used for the store×category heatmap and per-item drill-down."""
    groups: Dict[tuple, List[dict]] = {}
    for r in records:
        key = tuple(r[f] for f in group_fields)
        groups.setdefault(key, []).append(
            {"date": r["date"], "sales": float(r.get("sales") or 0)}
        )
    out: List[dict] = []
    for key, recs in groups.items():
        entry = {f: v for f, v in zip(group_fields, key)}
        entry["accuracy"] = classical_accuracy(pd.DataFrame(recs), holdout)
        out.append(entry)
    return out


def stockout_classifier(history: pd.DataFrame, holdout: int = 60) -> dict:
    """A real classification model: predict 'low-stock-risk day' (daily units in
    the bottom 20%) from calendar/lag features. Backtested on a holdout to
    produce probabilities (predict_proba), ROC + precision-recall curves with
    AUC/AP, and a confusion matrix at the F1-tuned operating threshold (not a
    fixed 0.5)."""
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

        # Risk probabilities on the held-out window.
        try:
            import lightgbm as lgb
            clf = lgb.LGBMClassifier(
                n_estimators=200, learning_rate=0.05, random_state=42, n_jobs=-1, verbose=-1
            )
            clf.fit(Xtr, ytr)
            proba = clf.predict_proba(Xte)[:, 1].astype(float)
            model_name = "lightgbm_classifier"
        except Exception:
            # Continuous risk score so the curves still render: the further daily
            # demand falls below the risk threshold, the higher the score.
            roll = feats["rollmean_7"].values[-holdout:]
            raw = thr - roll
            span = float(raw.max() - raw.min())
            proba = (raw - raw.min()) / span if span > 0 else np.zeros_like(raw, dtype=float)
            model_name = "rule_baseline"

        # Curves + F1-tuned threshold (need both classes present in the holdout).
        roc_points: List[dict] = []
        pr_points: List[dict] = []
        roc_auc = avg_precision = None
        tuned = 0.5
        if len(np.unique(yte)) >= 2:
            from sklearn.metrics import (
                roc_curve, auc, precision_recall_curve, average_precision_score,
            )
            fpr, tpr, _ = roc_curve(yte, proba)
            roc_auc = round(float(auc(fpr, tpr)), 3)
            roc_points = [{"fpr": round(float(a), 4), "tpr": round(float(b), 4)}
                          for a, b in zip(fpr, tpr)]

            prec_arr, rec_arr, pr_thr = precision_recall_curve(yte, proba)
            avg_precision = round(float(average_precision_score(yte, proba)), 3)
            pr_points = [{"recall": round(float(r), 4), "precision": round(float(p), 4)}
                         for r, p in zip(rec_arr, prec_arr)]
            if len(pr_thr):
                f1s = 2 * prec_arr[:-1] * rec_arr[:-1] / (prec_arr[:-1] + rec_arr[:-1] + 1e-12)
                tuned = float(pr_thr[int(np.argmax(f1s))])

        pred = (proba >= tuned).astype(int)
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
            "threshold": round(tuned, 3),
            "threshold_units": round(thr, 1),
            "tested_days": int(holdout),
            "roc": roc_points,
            "roc_auc": roc_auc,
            "pr": pr_points,
            "average_precision": avg_precision,
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
