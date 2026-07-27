"""
UAE retail-calendar features for Forecasting v2 (E7-1).

Deterministic, network-free feature builder that turns a date index into the
UAE seasonality signals a generic forecaster misses (Ramadan/Eid/DSF/National
Day/back-to-school/summer + pre/post windows). It REUSES the single source of
truth — `UAE_CALENDAR` in app.services.uae_intelligence — so there is never a
second calendar to drift out of sync.

Honesty (kept from uae_intelligence): lunar events (Ramadan/Eid) are APPROXIMATE
until confirmed against an official UAE source. Every row exposes
`uae_lunar_date_approx` (1 while an approximate lunar event is active), and the
calendar only covers the seasons defined in UAE_CALENDAR — dates outside those
windows get NEUTRAL ZERO features, and ranges before/after the known calendar
(e.g. a 2019 or 2028 date) simply yield zeros rather than crashing.

These are FUTURE-KNOWN features (derivable from the date alone), so they are safe
to use for recursive multi-step forecasting without target leakage.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from app.services.uae_intelligence import UAE_CALENDAR

# Stable, ordered feature set. Keep in sync with the engine's _feature_columns().
UAE_FEATURE_COLUMNS = [
    "uae_is_weekend",
    "uae_is_ramadan",
    "uae_ramadan_day",
    "uae_days_to_ramadan",
    "uae_days_from_ramadan",
    "uae_pre_ramadan_14d",
    "uae_post_ramadan_14d",
    "uae_is_eid_fitr",
    "uae_is_eid_adha",
    "uae_pre_eid_7d",
    "uae_is_dsf",
    "uae_is_national_day",
    "uae_is_back_to_school",
    "uae_is_summer",
    "uae_event_active_count",
    "uae_lunar_date_approx",
]

# How far out (days) the days_to/days_from ramp features stay non-zero. Beyond
# this the feature is neutral 0 — a bounded, leak-free proximity signal.
_PROXIMITY_WINDOW = 60

# Which UAE_CALENDAR events are lunar/approximate (drives uae_lunar_date_approx).
_LUNAR_KEYS = {"ramadan", "eid_fitr", "eid_adha"}


def lunar_dates_are_approximate() -> bool:
    """True while any lunar event in UAE_CALENDAR is flagged approximate — it is,
    and it stays honest even if the calendar is later updated/confirmed."""
    return any(e.get("approx") for e in UAE_CALENDAR if e.get("key") in _LUNAR_KEYS)


def _events() -> dict:
    """key -> (start_ts, end_ts, approx) parsed once from UAE_CALENDAR."""
    out = {}
    for e in UAE_CALENDAR:
        out[e["key"]] = (
            pd.Timestamp(e["start"]).normalize(),
            pd.Timestamp(e["end"]).normalize(),
            bool(e.get("approx", False)),
        )
    return out


def uae_calendar_features(index: Iterable) -> pd.DataFrame:
    """Build the UAE calendar feature frame for a date index.

    index: anything pd.DatetimeIndex accepts (DatetimeIndex, list of dates/strings).
    Returns a DataFrame indexed by the ORIGINAL index with UAE_FEATURE_COLUMNS.
    Deterministic, network-free, leap-year safe (pure date arithmetic).
    """
    orig = pd.DatetimeIndex(pd.to_datetime(list(index) if not isinstance(index, pd.DatetimeIndex) else index))
    d = orig.normalize()
    n = len(orig)
    ev = _events()
    df = pd.DataFrame(index=orig)

    # UAE retail weekend = Friday/Saturday (distinct from the engine's Sat/Sun
    # `is_weekend`; the model can use whichever helps).
    dow = np.asarray(d.dayofweek)
    df["uae_is_weekend"] = ((dow == 4) | (dow == 5)).astype(int)

    def active_mask(key: str) -> np.ndarray:
        if key not in ev:
            return np.zeros(n, dtype=bool)
        s, e, _ = ev[key]
        return np.asarray((d >= s) & (d <= e))

    active = {key: active_mask(key) for key in ev}

    # --- Ramadan (proximity ramps + in-window day counter) -----------------
    if "ramadan" in ev:
        rs, re, _ = ev["ramadan"]
        in_r = active["ramadan"]
        ramadan_day = np.asarray((d - rs).days) + 1  # 1-based day within Ramadan
        days_to = np.asarray((rs - d).days)          # >0 before Ramadan starts
        days_from = np.asarray((d - re).days)         # >0 after Ramadan ends
        df["uae_is_ramadan"] = in_r.astype(int)
        df["uae_ramadan_day"] = np.where(in_r, ramadan_day, 0).astype(int)
        df["uae_days_to_ramadan"] = np.where((days_to > 0) & (days_to <= _PROXIMITY_WINDOW), days_to, 0).astype(int)
        df["uae_days_from_ramadan"] = np.where((days_from > 0) & (days_from <= _PROXIMITY_WINDOW), days_from, 0).astype(int)
        df["uae_pre_ramadan_14d"] = ((days_to > 0) & (days_to <= 14)).astype(int)
        df["uae_post_ramadan_14d"] = ((days_from > 0) & (days_from <= 14)).astype(int)
    else:  # no ramadan in calendar -> neutral
        for c in ("uae_is_ramadan", "uae_ramadan_day", "uae_days_to_ramadan",
                  "uae_days_from_ramadan", "uae_pre_ramadan_14d", "uae_post_ramadan_14d"):
            df[c] = 0

    # --- Eid --------------------------------------------------------------
    df["uae_is_eid_fitr"] = active["eid_fitr"].astype(int) if "eid_fitr" in ev else 0
    df["uae_is_eid_adha"] = active["eid_adha"].astype(int) if "eid_adha" in ev else 0
    pre_eid = np.zeros(n, dtype=bool)
    for k in ("eid_fitr", "eid_adha"):
        if k in ev:
            days_to = np.asarray((ev[k][0] - d).days)
            pre_eid = pre_eid | ((days_to > 0) & (days_to <= 7))
    df["uae_pre_eid_7d"] = pre_eid.astype(int)

    # --- Fixed-date seasons ------------------------------------------------
    df["uae_is_dsf"] = active["dsf"].astype(int) if "dsf" in ev else 0
    df["uae_is_national_day"] = active["national_day"].astype(int) if "national_day" in ev else 0
    df["uae_is_back_to_school"] = active["back_to_school"].astype(int) if "back_to_school" in ev else 0
    df["uae_is_summer"] = active["summer"].astype(int) if "summer" in ev else 0

    # --- Aggregates + honesty ---------------------------------------------
    count = np.zeros(n, dtype=int)
    for m in active.values():
        count = count + m.astype(int)
    df["uae_event_active_count"] = count

    lunar = np.zeros(n, dtype=bool)
    for key, (_s, _e, approx) in ev.items():
        if approx:
            lunar = lunar | active[key]
    df["uae_lunar_date_approx"] = lunar.astype(int)

    return df[UAE_FEATURE_COLUMNS]


def calendar_feature_summary(uses_weather: bool = False) -> dict:
    """Small, honest descriptor for the Forecast Lab payload."""
    return {
        "uses_uae_calendar": True,
        "uses_weather_features": bool(uses_weather),
        "lunar_dates_approximate": lunar_dates_are_approximate(),
    }
