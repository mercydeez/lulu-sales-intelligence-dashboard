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


def test_enforcement_off_by_default(monkeypatch):
    monkeypatch.delenv("ENFORCE_USAGE_QUOTAS", raising=False)
    assert _enforcement_on() is False


def test_enforcement_on_when_flag_set(monkeypatch):
    for val in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("ENFORCE_USAGE_QUOTAS", val)
        assert _enforcement_on() is True
    monkeypatch.setenv("ENFORCE_USAGE_QUOTAS", "false")
    assert _enforcement_on() is False
