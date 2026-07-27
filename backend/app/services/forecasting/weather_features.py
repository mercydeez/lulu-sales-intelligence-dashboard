"""
Optional weather features for Forecasting v2 (E7-1) — FOUNDATION ONLY.

Default behaviour is a NEUTRAL no-op: every row gets zeros and `weather_available
= 0`, so nothing changes for tenants/stores without weather data and tests never
touch the network. Observations can be dependency-injected (a dict or DataFrame
keyed by date) for tests or for a future real ingestion path.

This is deliberately small: it establishes stable feature columns and a safe
degradation contract, not a full weather pipeline. A real free-provider hook can
later be added behind `provider=` — it MUST stay disabled by default,
timeout-bound, key-free, and optional; no test may depend on it.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Protocol

import numpy as np
import pandas as pd

WEATHER_FEATURE_COLUMNS = [
    "weather_temp_c",
    "weather_rain_mm",
    "weather_humidity_pct",
    "weather_available",
]

# Neutral defaults when weather is unavailable (documented, not magic):
_NEUTRAL = {"weather_temp_c": 0.0, "weather_rain_mm": 0.0, "weather_humidity_pct": 0.0}


class WeatherProvider(Protocol):
    """A source of daily observations. Real providers are optional and must be
    injected explicitly — the default path never constructs one."""
    def observations(self, index: pd.DatetimeIndex) -> Mapping:  # pragma: no cover - interface
        ...


def _neutral_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=index)
    df["weather_temp_c"] = _NEUTRAL["weather_temp_c"]
    df["weather_rain_mm"] = _NEUTRAL["weather_rain_mm"]
    df["weather_humidity_pct"] = _NEUTRAL["weather_humidity_pct"]
    df["weather_available"] = 0
    return df[WEATHER_FEATURE_COLUMNS]


def weather_features(
    index: Iterable,
    observations: Optional[Mapping] = None,
    provider: Optional[WeatherProvider] = None,
    store_coords: Optional[tuple] = None,
) -> pd.DataFrame:
    """Build the weather feature frame for a date index.

    * No observations and no provider (the DEFAULT) -> neutral zeros, available=0.
    * `observations`: a mapping {date -> {temp_c, rain_mm, humidity_pct}} (dates as
      strings or Timestamps). Injected/stubbed — deterministic, no network.
    * `provider`: an optional injected WeatherProvider; only used if given. Real
      providers are never constructed here by default.
    * `store_coords`: if a real provider needs coordinates and they are missing,
      we degrade to neutral rather than guessing.

    Dates without an observation degrade to neutral for that row (available=0),
    so a partial history is safe.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(list(index) if not isinstance(index, pd.DatetimeIndex) else index))

    obs: Mapping = {}
    if observations is not None:
        obs = observations
    elif provider is not None and store_coords is not None:
        try:
            obs = provider.observations(idx) or {}
        except Exception:
            obs = {}
    # No observations available at all -> fully neutral frame.
    if not obs:
        return _neutral_frame(idx)

    # Normalise observation keys to date strings for lookup.
    def _key(ts) -> str:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")

    norm = {_key(k): v for k, v in obs.items()}

    temp = np.full(len(idx), _NEUTRAL["weather_temp_c"], dtype=float)
    rain = np.full(len(idx), _NEUTRAL["weather_rain_mm"], dtype=float)
    hum = np.full(len(idx), _NEUTRAL["weather_humidity_pct"], dtype=float)
    avail = np.zeros(len(idx), dtype=int)

    for i, ts in enumerate(idx):
        row = norm.get(_key(ts))
        if not row:
            continue  # missing date -> neutral for this row
        temp[i] = float(row.get("temp_c", _NEUTRAL["weather_temp_c"]))
        rain[i] = float(row.get("rain_mm", _NEUTRAL["weather_rain_mm"]))
        hum[i] = float(row.get("humidity_pct", _NEUTRAL["weather_humidity_pct"]))
        avail[i] = 1

    df = pd.DataFrame(index=idx)
    df["weather_temp_c"] = temp
    df["weather_rain_mm"] = rain
    df["weather_humidity_pct"] = hum
    df["weather_available"] = avail
    return df[WEATHER_FEATURE_COLUMNS]
