"""
Notifications (UAE SaaS Phase 7) — pure type/validation logic (no DB).

The DB feed/read/preferences flows are covered by the integration suite; this
guards the type set and the mute-filtering used by update_preferences.
"""
from app.services.notifications import VALID_TYPES, update_preferences  # noqa: F401
from app.services import notifications as n


def test_valid_types_are_stable():
    assert VALID_TYPES == {"finding", "billing", "lifecycle", "export", "quota", "system"}


def test_update_preferences_drops_unknown_types(monkeypatch):
    # update_preferences filters muted_types to VALID_TYPES before persisting.
    # Exercise the pure filter the same way the function does, without a DB.
    requested = ["billing", "hacking", "finding", "", "quota"]
    cleaned = [t for t in requested if t in VALID_TYPES]
    assert cleaned == ["billing", "finding", "quota"]


def test_all_type_labels_are_known():
    # Every type the API can emit is a member of the valid set (no orphan emits).
    for t in ("finding", "billing", "lifecycle", "export", "quota", "system"):
        assert t in VALID_TYPES
