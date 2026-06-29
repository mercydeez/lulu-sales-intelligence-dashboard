"""Track 5 metering scaffolding — pure plan-limit / meter logic (no DB)."""
from app.services.plan_limits import PLAN_LIMITS, limits_for_plan, _meter


def test_known_plans_have_all_dimensions():
    for plan, limits in PLAN_LIMITS.items():
        assert set(limits) == {"api_requests", "api_keys", "users"}, plan


def test_unknown_plan_falls_back_to_free():
    assert limits_for_plan("does-not-exist") == PLAN_LIMITS["free"]
    assert limits_for_plan(None) == PLAN_LIMITS["free"]
    assert limits_for_plan("FREE") == PLAN_LIMITS["free"]  # case-insensitive


def test_enterprise_is_unlimited():
    for dim in ("api_requests", "api_keys", "users"):
        assert PLAN_LIMITS["enterprise"][dim] is None


def test_meter_under_limit():
    m = _meter(used=10, limit=100)
    assert m == {"used": 10, "limit": 100, "remaining": 90, "over_quota": False, "pct": 10.0}


def test_meter_over_limit_clamps_remaining_to_zero():
    m = _meter(used=150, limit=100)
    assert m["over_quota"] is True
    assert m["remaining"] == 0
    assert m["pct"] == 150.0


def test_meter_at_exact_limit_is_not_over():
    m = _meter(used=100, limit=100)
    assert m["over_quota"] is False
    assert m["remaining"] == 0


def test_meter_unlimited_never_over():
    m = _meter(used=10_000_000, limit=None)
    assert m == {"used": 10_000_000, "limit": None, "remaining": None,
                 "over_quota": False, "pct": 0.0}
