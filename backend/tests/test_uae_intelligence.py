"""
UAE retail intelligence — pure calendar logic (no DB).

Emirate/transfer/dead-stock queries are integration-tested; this guards the calendar
window logic and that lunar events are honestly flagged approximate.
"""
from datetime import date

from app.services.uae_intelligence import UAE_CALENDAR, upcoming_events


def test_calendar_has_core_uae_seasons():
    keys = {e["key"] for e in UAE_CALENDAR}
    assert {"ramadan", "eid_fitr", "dsf", "back_to_school"} <= keys


def test_lunar_events_flagged_approximate():
    for e in UAE_CALENDAR:
        if e["key"] in ("ramadan", "eid_fitr", "eid_adha"):
            assert e["approx"] is True


def test_active_event_detected():
    # Mid-Ramadan 2026 (approx 2026-02-18 .. 03-19)
    up = upcoming_events(date(2026, 3, 1))
    ramadan = next((e for e in up if e["key"] == "ramadan"), None)
    assert ramadan and ramadan["active"] is True


def test_upcoming_within_horizon():
    # ~40 days before Ramadan start → should appear as upcoming, not active.
    up = upcoming_events(date(2026, 1, 12), horizon_days=60)
    ramadan = next((e for e in up if e["key"] == "ramadan"), None)
    assert ramadan and ramadan["active"] is False and ramadan["days_until"] > 0


def test_past_events_excluded():
    up = upcoming_events(date(2026, 11, 1))
    assert all(e["key"] not in ("ramadan", "eid_fitr", "eid_adha") for e in up)


def test_active_sorted_before_upcoming():
    up = upcoming_events(date(2026, 8, 20))  # back_to_school active, others upcoming
    if len(up) >= 2:
        assert up[0].get("active") is True
