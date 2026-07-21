"""Operations Copilot — policy and approval-engine tests.

Two things must hold no matter how a tenant configures the policy: a user can
never approve outside their own store scope, and nothing can be configured into
submitting an order to an outside party.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operations.contracts import ActionType, RiskLevel
from app.services.operations.policy import (
    DEFAULT_POLICY,
    OperationsPolicy,
    ROLE_RANK,
    can_approve,
    evidence_is_fresh,
    is_draft_only,
    is_expired,
    materially_changed,
    proposal_expiry,
    required_role,
)

NOW = datetime.now(timezone.utc)


def user(role="regional_manager", stores=(1, 2, 3), tenant_id=1):
    return {
        "id": 7, "email": "u@example.test", "role": role, "tenant_id": tenant_id,
        "permissions": {"accessible_stores": list(stores)},
    }


class TestRequiredRole:
    def test_defaults_follow_the_documented_ladder(self):
        assert required_role(DEFAULT_POLICY, ActionType.INVESTIGATION_TASK) == "store_manager"
        assert required_role(DEFAULT_POLICY, ActionType.REPLENISHMENT_DRAFT) == "regional_manager"
        assert required_role(DEFAULT_POLICY, ActionType.STOCK_TRANSFER_DRAFT) == "regional_manager"

    def test_high_risk_escalates_one_rung(self):
        assert required_role(DEFAULT_POLICY, ActionType.INVESTIGATION_TASK,
                             RiskLevel.HIGH) == "regional_manager"
        assert required_role(DEFAULT_POLICY, ActionType.REPLENISHMENT_DRAFT,
                             RiskLevel.HIGH) == "super_admin"

    def test_escalation_caps_at_super_admin(self):
        policy = OperationsPolicy(approval_roles={
            ActionType.STOCK_TRANSFER_DRAFT.value: "super_admin"})
        assert required_role(policy, ActionType.STOCK_TRANSFER_DRAFT,
                             RiskLevel.HIGH) == "super_admin"

    def test_unknown_action_defaults_to_the_most_senior_role(self):
        policy = OperationsPolicy(approval_roles={})
        assert required_role(policy, ActionType.REPLENISHMENT_DRAFT) == "super_admin"

    def test_tenant_can_lower_the_bar_for_its_own_stores(self):
        policy = OperationsPolicy(approval_roles={
            ActionType.REPLENISHMENT_DRAFT.value: "store_manager"})
        assert required_role(policy, ActionType.REPLENISHMENT_DRAFT) == "store_manager"


class TestCanApprove:
    def test_regional_manager_approves_a_transfer_inside_scope(self):
        ok, why = can_approve(user(), DEFAULT_POLICY,
                              action_type=ActionType.STOCK_TRANSFER_DRAFT,
                              risk_level=RiskLevel.MEDIUM, target_store_ids=[1, 2])
        assert ok, why

    def test_store_manager_cannot_approve_a_transfer(self):
        ok, why = can_approve(user(role="store_manager", stores=(1,)), DEFAULT_POLICY,
                              action_type=ActionType.STOCK_TRANSFER_DRAFT,
                              risk_level=RiskLevel.MEDIUM, target_store_ids=[1])
        assert not ok and "regional_manager" in why

    def test_store_manager_approves_an_investigation_in_scope(self):
        ok, why = can_approve(user(role="store_manager", stores=(4,)), DEFAULT_POLICY,
                              action_type=ActionType.INVESTIGATION_TASK,
                              risk_level=RiskLevel.MEDIUM, target_store_ids=[4])
        assert ok, why

    def test_out_of_scope_store_is_refused_even_with_the_right_role(self):
        ok, why = can_approve(user(stores=(1, 2)), DEFAULT_POLICY,
                              action_type=ActionType.STOCK_TRANSFER_DRAFT,
                              risk_level=RiskLevel.MEDIUM, target_store_ids=[2, 99])
        assert not ok and "99" in why

    def test_transfer_needs_both_stores_in_scope(self):
        ok, _ = can_approve(user(stores=(1,)), DEFAULT_POLICY,
                            action_type=ActionType.STOCK_TRANSFER_DRAFT,
                            risk_level=RiskLevel.MEDIUM, target_store_ids=[1, 2])
        assert not ok

    def test_analyst_can_never_approve(self):
        for action in ActionType:
            ok, _ = can_approve(user(role="analyst"), DEFAULT_POLICY,
                                action_type=action, risk_level=RiskLevel.LOW,
                                target_store_ids=[1])
            assert not ok

    def test_super_admin_is_not_store_scoped_within_its_tenant(self):
        # An empty accessible_stores list means "all stores" for super_admin only.
        ok, why = can_approve({"role": "super_admin", "permissions": {"accessible_stores": []}},
                              DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
                              risk_level=RiskLevel.HIGH, target_store_ids=[42])
        assert ok, why

    def test_empty_scope_blocks_a_non_admin(self):
        ok, _ = can_approve({"role": "regional_manager", "permissions": {}},
                            DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
                            risk_level=RiskLevel.MEDIUM, target_store_ids=[1])
        assert not ok

    def test_disabled_action_type_is_refused_for_everyone(self):
        policy = OperationsPolicy(allowed_action_types=[ActionType.INVESTIGATION_TASK])
        ok, why = can_approve(user(role="super_admin"), policy,
                              action_type=ActionType.STOCK_TRANSFER_DRAFT,
                              risk_level=RiskLevel.LOW, target_store_ids=[])
        assert not ok and "not enabled" in why

    def test_unknown_role_string_is_refused(self):
        ok, _ = can_approve(user(role="wizard"), DEFAULT_POLICY,
                            action_type=ActionType.INVESTIGATION_TASK,
                            risk_level=RiskLevel.LOW, target_store_ids=[1])
        assert not ok

    def test_role_ladder_is_ordered(self):
        assert (ROLE_RANK["analyst"] < ROLE_RANK["store_manager"]
                < ROLE_RANK["regional_manager"] < ROLE_RANK["super_admin"])


class TestDraftOnly:
    def test_every_action_is_draft_only_by_default(self):
        for action in ActionType:
            assert is_draft_only(DEFAULT_POLICY, action)

    def test_no_integration_is_enabled_by_default(self):
        assert not any(DEFAULT_POLICY.integrations_enabled.values())

    def test_clearing_draft_only_without_a_connector_still_forces_draft(self):
        """The safety net: a tenant cannot configure its way to an external order."""
        policy = OperationsPolicy(draft_only={
            ActionType.REPLENISHMENT_DRAFT.value: False,
            ActionType.STOCK_TRANSFER_DRAFT.value: False,
        })
        assert is_draft_only(policy, ActionType.REPLENISHMENT_DRAFT)
        assert is_draft_only(policy, ActionType.STOCK_TRANSFER_DRAFT)

    def test_draft_only_lifts_only_when_the_connector_is_enabled(self):
        policy = OperationsPolicy(
            draft_only={ActionType.REPLENISHMENT_DRAFT.value: False},
            integrations_enabled={"procurement": True},
        )
        assert not is_draft_only(policy, ActionType.REPLENISHMENT_DRAFT)


class TestFreshnessAndExpiry:
    def test_default_proposal_lifetime_is_fourteen_days(self):
        assert proposal_expiry(DEFAULT_POLICY, NOW) - NOW == timedelta(days=14)

    def test_expired_proposal_is_detected(self):
        created = NOW - timedelta(days=15)
        assert is_expired(DEFAULT_POLICY, created, now=NOW)
        assert not is_expired(DEFAULT_POLICY, NOW - timedelta(days=1), now=NOW)

    def test_naive_timestamps_are_handled(self):
        created = (NOW - timedelta(days=20)).replace(tzinfo=None)
        assert is_expired(DEFAULT_POLICY, created, now=NOW)

    def test_stale_evidence_is_rejected(self):
        assert evidence_is_fresh(DEFAULT_POLICY, NOW - timedelta(hours=1), now=NOW)
        assert not evidence_is_fresh(DEFAULT_POLICY, NOW - timedelta(days=10), now=NOW)

    def test_freshness_window_is_configurable(self):
        policy = OperationsPolicy(max_evidence_age_hours=1)
        assert not evidence_is_fresh(policy, NOW - timedelta(hours=2), now=NOW)


class TestRevalidationTolerance:
    def test_small_drift_is_not_material(self):
        assert not materially_changed(DEFAULT_POLICY, 100, 110)

    def test_large_drift_aborts_execution(self):
        assert materially_changed(DEFAULT_POLICY, 100, 200)
        assert materially_changed(DEFAULT_POLICY, 100, 40)

    def test_zero_to_nonzero_is_always_material(self):
        assert materially_changed(DEFAULT_POLICY, 0, 5)
        assert not materially_changed(DEFAULT_POLICY, 0, 0)

    def test_tolerance_is_configurable(self):
        strict = OperationsPolicy(revalidation_tolerance=0.01)
        assert materially_changed(strict, 100, 105)


class TestPolicyDefaultsAreTenantNeutral:
    def test_no_monetary_thresholds_exist(self):
        dumped = DEFAULT_POLICY.model_dump_json().lower()
        for token in ("aed", "usd", "currency", "amount_limit"):
            assert token not in dumped

    def test_safety_rules_protect_the_source_store(self):
        assert DEFAULT_POLICY.transfer.source_min_days_cover >= 1
        assert 0 < DEFAULT_POLICY.transfer.max_share_of_source <= 1.0

    def test_replenishment_settings_are_in_days_and_units(self):
        r = DEFAULT_POLICY.replenishment
        assert r.safety_stock_days >= 0 and r.default_lead_time_days >= 1
        assert r.min_order_quantity >= 1 and r.max_order_quantity > r.min_order_quantity

    def test_confidence_and_evidence_gates_exist(self):
        assert 0 < DEFAULT_POLICY.min_confidence <= 1
        assert DEFAULT_POLICY.min_evidence_items >= 1


@pytest.mark.asyncio
async def test_get_policy_falls_back_to_defaults_when_row_is_invalid():
    """A malformed stored policy must not take the copilot offline — and the
    fallback is the conservative default, not an empty permissive object."""
    from app.services.operations.policy import get_policy

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _DB:
        def __init__(self, value):
            self._value = value

        async def execute(self, *a, **kw):
            return _Result(self._value)

    assert await get_policy(_DB(None), 1) is DEFAULT_POLICY
    assert await get_policy(_DB({"min_confidence": "not-a-number"}), 1) is DEFAULT_POLICY

    custom = await get_policy(_DB({"measurement_window_days": 21}), 1)
    assert custom.measurement_window_days == 21
    assert custom.transfer.source_min_days_cover == DEFAULT_POLICY.transfer.source_min_days_cover


@pytest.mark.asyncio
async def test_get_policy_survives_a_database_error():
    from app.services.operations.policy import get_policy

    class _BrokenDB:
        async def execute(self, *a, **kw):
            raise RuntimeError("relation does not exist")

    assert await get_policy(_BrokenDB(), 1) is DEFAULT_POLICY
