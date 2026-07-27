"""Horizon 4 pure-logic unit tests — the parts that don't need a live DB.

Shelf-life urgency and coalition attribution weighting are deterministic
functions; they get fast, exhaustive unit coverage here. The DB-bound behaviour
(seasonality lookup, attribution persistence, the outcome-pricing gate) is proven
in the live integration suite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.flywheel import shelf_life, coalition


# ---------------------------------------------------------------------------
# Shelf-life urgency + markdown
# ---------------------------------------------------------------------------

def test_urgency_is_zero_far_from_expiry():
    assert shelf_life.urgency_for(shelf_life.URGENT_HORIZON_DAYS) == 0.0
    assert shelf_life.urgency_for(shelf_life.URGENT_HORIZON_DAYS + 5) == 0.0


def test_urgency_is_one_at_or_past_expiry():
    assert shelf_life.urgency_for(0) == 1.0
    assert shelf_life.urgency_for(-3) == 1.0


def test_urgency_rises_monotonically_toward_expiry():
    prev = -1.0
    for days in range(shelf_life.URGENT_HORIZON_DAYS, -1, -1):
        u = shelf_life.urgency_for(days)
        assert u >= prev, f"urgency should not fall as expiry nears (day {days})"
        prev = u


def test_markdown_scales_with_urgency_and_is_capped():
    assert shelf_life.recommended_markdown_pct(0.0) == Decimal("0.00")
    # urgency 1.0 -> the 50% cap, never more.
    assert shelf_life.recommended_markdown_pct(1.0) == Decimal("50.00")
    # a mid urgency lands between.
    mid = shelf_life.recommended_markdown_pct(0.5)
    assert Decimal("0") < mid < Decimal("50")


# ---------------------------------------------------------------------------
# Coalition attribution weighting
# ---------------------------------------------------------------------------

def _touch(partner_id, days_ago, as_of):
    from datetime import timedelta
    when = as_of - timedelta(days=days_ago)
    # (partner_id, first_at, last_at, n)
    return (partner_id, when, when, 1)


def test_linear_weights_are_equal_and_sum_to_one():
    as_of = datetime(2026, 7, 20, tzinfo=timezone.utc)
    touches = [_touch(1, 5, as_of), _touch(2, 2, as_of), _touch(3, 1, as_of)]
    w = coalition._weights(touches, "linear", as_of)
    assert set(w.values()) == {1.0}
    # after normalisation these are 1/3 each; the raw weights are equal.
    total = sum(w.values())
    normalised = {k: v / total for k, v in w.items()}
    assert abs(sum(normalised.values()) - 1.0) < 1e-9
    assert all(abs(v - 1 / 3) < 1e-9 for v in normalised.values())


def test_time_decay_weights_recent_touches_more():
    as_of = datetime(2026, 7, 20, tzinfo=timezone.utc)
    touches = [_touch(1, 60, as_of), _touch(2, 1, as_of)]
    w = coalition._weights(touches, "time_decay", as_of)
    assert w[2] > w[1], "a touch 1 day ago must weigh more than one 60 days ago"


def test_position_weights_first_and_last_most():
    as_of = datetime(2026, 7, 20, tzinfo=timezone.utc)
    touches = [_touch(1, 10, as_of), _touch(2, 5, as_of), _touch(3, 1, as_of)]
    w = coalition._weights(touches, "position", as_of)
    # first (1) and last (3) each get 0.4; the middle (2) gets the remainder.
    assert w[1] == pytest.approx(0.4)
    assert w[3] == pytest.approx(0.4)
    assert w[2] < w[1]


def test_single_touch_gets_all_the_weight():
    as_of = datetime(2026, 7, 20, tzinfo=timezone.utc)
    for model in ("linear", "time_decay", "position"):
        w = coalition._weights([_touch(7, 3, as_of)], model, as_of)
        total = sum(w.values())
        assert abs((w[7] / total) - 1.0) < 1e-9, f"{model}: sole partner should get 100%"
