# Forecasting v2 — UAE calendar-aware accuracy (E7-1)

> Backend/data-science methodology note. This is the **internal** foundation for
> UAE-seasonality-aware forecasting. The **public** Ramadan accuracy publication is
> a separate task (E7-2) and is **not** covered here.

## What was already there (unchanged)

Forecast Lab already runs a rolling-origin backtest that fits several models
(seasonal-naive, seasonal-trend, LightGBM, and a deep tier), scores each on
**held-out actuals** with MAPE/WAPE, and selects the lowest-error model per
series. The selected model's error travels with the forecast so it can be shown
honestly. **Seasonal-naive is the honesty baseline** and is preserved exactly.

All pre-existing fields (`accuracy`, `selected_model`, `mape`, `leaderboard`,
`forecast`, `backtest`, `interval_pct`, `feature_importance`, `classifier`, …)
are unchanged and backward-compatible.

## What E7-1 adds

1. **UAE retail-calendar features** (`forecasting/calendar_features.py`), built
   from the single source of truth `UAE_CALENDAR` in `services/uae_intelligence.py`
   (no second calendar). Per date: Ramadan (in-window day counter + 14-day
   pre/post windows + bounded days-to/from ramps), Eid Al-Fitr / Eid Al-Adha
   (+ 7-day pre-Eid), DSF (cross-year aware), UAE National Day, back-to-school,
   summer, an active-event count, and an `uae_lunar_date_approx` honesty flag.
   These are **future-known** (derivable from the date), so they feed recursive
   multi-step forecasting without target leakage. They flow into the LightGBM
   feature set; the seasonal-naive baseline and classical models are unaffected.

2. **Optional weather features** (`forecasting/weather_features.py`) — a
   **foundation only**. The default is a neutral no-op (`weather_available = 0`,
   zeros); observations can be dependency-injected for tests or a future ingestion
   path. **No network call, no API key, disabled by default.** When weather is
   unavailable (the normal case today), features degrade to neutral.

3. **v2 accuracy fields** added to the Forecast Lab / `model-metrics` payload:
   `forecasting_version`, `baseline_model`, `baseline_mape`/`baseline_wape`,
   `selected_model_mape`/`selected_model_wape`, `wape_improvement_vs_baseline_pct`
   (selected vs seasonal-naive, positive = better, `None` when the baseline is
   zero/missing), the Ramadan block, `calendar_feature_summary`, and a
   `methodology_note`.

## Honesty guarantees

- **UAE lunar dates (Ramadan/Eid) are approximate** until confirmed against an
  official UAE source. This is surfaced per row (`uae_lunar_date_approx`) and in
  `calendar_feature_summary.lunar_dates_approximate`.
- **Ramadan-window accuracy is reported only when the backtest window contains
  Ramadan dates.** The selected model's held-out predictions are filtered to the
  Ramadan subset and scored (MAPE/WAPE). If the window has **no** Ramadan dates,
  the API returns `ramadan_accuracy = None` with
  `ramadan_accuracy_reason = "no_ramadan_dates_in_backtest_window"`. With no
  backtest window at all (short history), the reason is `"no_backtest_window"`.
- **Weather is neutral when unavailable** — it never fabricates conditions.
- **No LLM is involved** in forecasting or accuracy. Everything is deterministic.

## Serving model (unchanged)

`GET /api/analytics/model-metrics` stays **cache-first with background warming** —
it never trains synchronously in the request path. Training runs in a worker
thread and the result (including the new v2 fields) is cached. Tenant scoping
(`tenant_id`) and store scoping (`accessible_store_ids`) are unchanged.

## Units vs AED

Forecast Lab forecasts **units** (volume) from `sales_fact_view`; that convention
is preserved. Business-impact figures that multiply by price are explicitly
labelled **AED estimates** with the derivation shown — no fabricated margins/costs.
