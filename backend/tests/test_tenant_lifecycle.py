"""
Tenant lifecycle state machine (UAE SaaS Phase 2).

Unit-covers the pure access-gating + transition rules that back both the API and
the get_current_user enforcement hook. DB transition + audit are exercised live by
the integration suite.
"""
from app.services.tenant_lifecycle import (
    STATES, ACTIVE_STATES, BLOCKED_STATES, is_access_allowed, validate_transition,
)


def test_blocked_states_denied_access():
    for s in ("suspended", "cancelled", "deleted"):
        assert is_access_allowed(s) is False


def test_active_states_allowed_access():
    for s in ("trial", "onboarding", "active", "payment_pending", "past_due"):
        assert is_access_allowed(s) is True


def test_unknown_or_none_status_fails_open():
    # Legacy rows / demo tenant are 'active'; never lock out on unknown/None.
    assert is_access_allowed(None) is True
    assert is_access_allowed("") is True
    assert is_access_allowed("legacy_value") is True


def test_state_sets_are_disjoint_and_cover():
    assert ACTIVE_STATES.isdisjoint(BLOCKED_STATES)
    # deletion_requested counts as active-access (data still theirs until erased).
    assert "deletion_requested" in ACTIVE_STATES
    assert ACTIVE_STATES | BLOCKED_STATES == STATES


def test_valid_transition_active_to_suspended():
    ok, err = validate_transition("active", "suspended")
    assert ok and err is None


def test_reactivate_suspended():
    ok, _ = validate_transition("suspended", "active")
    assert ok


def test_same_status_is_rejected():
    ok, err = validate_transition("active", "active")
    assert not ok and "already" in err


def test_illegal_transition_rejected():
    ok, err = validate_transition("active", "deleted")  # must pass through deletion_requested
    assert not ok and "Cannot move" in err


def test_deleted_is_terminal():
    for target in STATES:
        ok, _ = validate_transition("deleted", target)
        assert not ok


def test_unknown_target_rejected():
    ok, err = validate_transition("active", "frozen")
    assert not ok and "Unknown status" in err
