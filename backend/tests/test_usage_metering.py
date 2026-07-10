"""
Billing-period usage metering (UAE SaaS Phase 3) — pure logic (no DB).

Covers the period window math, the per-plan limit table, the event→dimension map,
and the enforcement flag. Live counting/enforcement against usage_events is covered
by the integration suite.
"""
import os
from datetime import datetime, timezone

from app.services.usage_metering import (
    USAGE_LIMITS, METERED_EVENTS, EVENT_TO_DIM, usage_limits_for_plan,
    current_period, _enforcement_on,
)


def test_every_plan_covers_all_metered_dimensions():
    for plan, limits in USAGE_LIMITS.items():
        assert set(limits) == set(METERED_EVENTS), plan


def test_enterprise_is_unlimited():
    for dim in METERED_EVENTS:
        assert USAGE_LIMITS["enterprise"][dim] is None


def test_unknown_plan_falls_back_to_free():
    assert usage_limits_for_plan("nope") == USAGE_LIMITS["free"]
    assert usage_limits_for_plan(None) == USAGE_LIMITS["free"]
    assert usage_limits_for_plan("FREE") == USAGE_LIMITS["free"]


def test_event_to_dim_targets_exist():
    for dim in EVENT_TO_DIM.values():
        assert dim in METERED_EVENTS


def test_current_period_is_calendar_month_dubai():
    # 2026-06-15 12:00 UTC -> 16:00 Asia/Dubai, still June.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    p = current_period(now)
    assert p["label"] == "month:2026-06"
    assert p["timezone"] == "Asia/Dubai"
    # The window brackets 'now'.
    assert p["start"] <= now < p["end"]
    # Dubai is +04:00, so the UTC start is 2026-05-31 20:00.
    assert p["start"] == datetime(2026, 5, 31, 20, 0, tzinfo=timezone.utc)
    assert p["end"] == datetime(2026, 6, 30, 20, 0, tzinfo=timezone.utc)


def test_current_period_december_rolls_to_january():
    now = datetime(2026, 12, 20, 0, 0, tzinfo=timezone.utc)
    p = current_period(now)
    assert p["label"] == "month:2026-12"
    # End is Jan 1 2027 00:00 Asia/Dubai == 2026-12-31 20:00 UTC (the +04:00 offset).
    assert p["end"] == datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert now < p["end"]


def _reload_settings(monkeypatch, value=None):
    """E8-3 moved the flag from a bare os.getenv into Settings, which is lru_cached
    — so an env change only lands after the cache is cleared. That is the whole
    reason it moved: a cached, typed flag is one an operator can trust, and a test
    that flips os.environ mid-process was only ever passing by accident."""
    from app.config import get_settings
    if value is None:
        monkeypatch.delenv("ENFORCE_USAGE_QUOTAS", raising=False)
    else:
        monkeypatch.setenv("ENFORCE_USAGE_QUOTAS", value)
    get_settings.cache_clear()
    return get_settings


def test_enforcement_off_by_default(monkeypatch):
    get_settings = _reload_settings(monkeypatch, None)
    try:
        assert _enforcement_on() is False
    finally:
        get_settings.cache_clear()


def test_enforcement_on_when_flag_set(monkeypatch):
    from app.config import get_settings
    try:
        for val in ("true", "1", "yes", "on", "TRUE"):
            _reload_settings(monkeypatch, val)
            assert _enforcement_on() is True, f"{val!r} should enable enforcement"
        _reload_settings(monkeypatch, "false")
        assert _enforcement_on() is False
    finally:
        # Never leave a cached Settings carrying a test's env behind for the
        # next test in the session.
        monkeypatch.delenv("ENFORCE_USAGE_QUOTAS", raising=False)
        get_settings.cache_clear()
