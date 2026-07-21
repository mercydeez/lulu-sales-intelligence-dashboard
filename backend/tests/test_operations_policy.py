"""Operations Copilot — policy and approval-engine tests.

Invariants that must hold no matter how a tenant configures the policy: a user
can never approve outside their own tenant or store scope, an action with no
declared scope is refused rather than waved through, nothing can be configured
into submitting an external order, and a malformed policy refuses the run rather
than silently substituting a more permissive ruleset.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operations.contracts import ActionType, RiskLevel
from app.services.operations.policy import (
    AVAILABLE_CONNECTORS,
    DEFAULT_POLICY,
    MalformedPolicyError,
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


def approve(u, action_type, risk_level, target_store_ids, policy=DEFAULT_POLICY,
            proposal_tenant_id=1):
    return can_approve(u, policy, action_type=action_type, risk_level=risk_level,
                       target_store_ids=target_store_ids,
                       proposal_tenant_id=proposal_tenant_id)


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


class TestCanApprove:
    def test_regional_manager_approves_a_transfer_inside_scope(self):
        ok, why = approve(user(), ActionType.STOCK_TRANSFER_DRAFT, RiskLevel.MEDIUM, [1, 2])
        assert ok, why

    def test_store_manager_cannot_approve_a_transfer(self):
        ok, why = approve(user(role="store_manager", stores=(1,)),
                          ActionType.STOCK_TRANSFER_DRAFT, RiskLevel.MEDIUM, [1])
        assert not ok and "regional_manager" in why

    def test_store_manager_approves_an_investigation_in_scope(self):
        ok, why = approve(user(role="store_manager", stores=(4,)),
                          ActionType.INVESTIGATION_TASK, RiskLevel.MEDIUM, [4])
        assert ok, why

    def test_out_of_scope_store_is_refused_even_with_the_right_role(self):
        ok, why = approve(user(stores=(1, 2)), ActionType.STOCK_TRANSFER_DRAFT,
                          RiskLevel.MEDIUM, [2, 99])
        assert not ok and "99" in why

    def test_transfer_needs_both_stores_in_scope(self):
        ok, _ = approve(user(stores=(1,)), ActionType.STOCK_TRANSFER_DRAFT,
                        RiskLevel.MEDIUM, [1, 2])
        assert not ok

    def test_analyst_can_never_approve(self):
        for action in ActionType:
            ok, _ = approve(user(role="analyst"), action, RiskLevel.LOW, [1])
            assert not ok

    # --- the holes the review found -------------------------------------------

    def test_empty_target_list_is_refused_not_waved_through(self):
        """A store-scoped action with no declared scope must not pass the scope
        check by having nothing to check."""
        ok, why = approve(user(role="store_manager", stores=()),
                          ActionType.INVESTIGATION_TASK, RiskLevel.LOW, [])
        assert not ok and "no target store" in why

    def test_cross_tenant_proposal_is_refused(self):
        ok, why = approve(user(tenant_id=1), ActionType.INVESTIGATION_TASK,
                          RiskLevel.LOW, [1], proposal_tenant_id=2)
        assert not ok and "different tenant" in why

    def test_missing_user_tenant_is_refused(self):
        u = user(); u.pop("tenant_id")
        ok, _ = approve(u, ActionType.INVESTIGATION_TASK, RiskLevel.LOW, [1])
        assert not ok

    def test_super_admin_with_all_stores_is_not_store_scoped(self):
        ok, why = can_approve(
            {"role": "super_admin", "tenant_id": 1, "permissions": {"accessible_stores": []}},
            DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
            risk_level=RiskLevel.HIGH, target_store_ids=[42], proposal_tenant_id=1)
        assert ok, why

    def test_super_admin_with_narrowed_scope_is_still_held_to_it(self):
        """A super_admin deliberately restricted to store 1 must not approve 99."""
        ok, why = can_approve(
            {"role": "super_admin", "tenant_id": 1, "permissions": {"accessible_stores": [1]}},
            DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
            risk_level=RiskLevel.HIGH, target_store_ids=[99], proposal_tenant_id=1)
        assert not ok and "99" in why

    def test_super_admin_still_bound_to_its_own_tenant(self):
        ok, _ = can_approve(
            {"role": "super_admin", "tenant_id": 1, "permissions": {}},
            DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
            risk_level=RiskLevel.HIGH, target_store_ids=[5], proposal_tenant_id=99)
        assert not ok

    def test_empty_scope_blocks_a_non_admin(self):
        ok, _ = can_approve(
            {"role": "regional_manager", "tenant_id": 1, "permissions": {}},
            DEFAULT_POLICY, action_type=ActionType.REPLENISHMENT_DRAFT,
            risk_level=RiskLevel.MEDIUM, target_store_ids=[1], proposal_tenant_id=1)
        assert not ok

    def test_disabled_action_type_is_refused_for_everyone(self):
        policy = OperationsPolicy(allowed_action_types=[ActionType.INVESTIGATION_TASK])
        ok, why = approve(user(role="super_admin"), ActionType.STOCK_TRANSFER_DRAFT,
                          RiskLevel.LOW, [1], policy=policy)
        assert not ok and "not enabled" in why

    def test_unknown_role_string_is_refused(self):
        ok, _ = approve(user(role="wizard"), ActionType.INVESTIGATION_TASK,
                        RiskLevel.LOW, [1])
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

    def test_no_connectors_are_wired_yet(self):
        assert AVAILABLE_CONNECTORS == frozenset()

    def test_clearing_draft_only_without_a_connector_still_forces_draft(self):
        """A tenant cannot configure its way to an external order — the connector
        must exist in CODE, which no JSON flag can achieve."""
        policy = OperationsPolicy(
            draft_only={ActionType.REPLENISHMENT_DRAFT.value: False,
                        ActionType.STOCK_TRANSFER_DRAFT.value: False},
            integrations_enabled={"procurement": True, "stock_transfer": True})
        assert is_draft_only(policy, ActionType.REPLENISHMENT_DRAFT)
        assert is_draft_only(policy, ActionType.STOCK_TRANSFER_DRAFT)

    def test_investigation_is_draft_only_via_the_explicit_flag(self):
        assert is_draft_only(OperationsPolicy(), ActionType.INVESTIGATION_TASK)


class TestFreshnessAndExpiry:
    def test_default_proposal_lifetime_is_fourteen_days(self):
        assert proposal_expiry(DEFAULT_POLICY, NOW) - NOW == timedelta(days=14)

    def test_expired_proposal_is_detected(self):
        assert is_expired(DEFAULT_POLICY, NOW - timedelta(days=15), now=NOW)
        assert not is_expired(DEFAULT_POLICY, NOW - timedelta(days=1), now=NOW)

    def test_future_dated_proposal_is_treated_as_expired(self):
        """Bad data must not buy an approval extra life."""
        assert is_expired(DEFAULT_POLICY, NOW + timedelta(days=1), now=NOW)

    def test_naive_timestamps_are_handled(self):
        created = (NOW - timedelta(days=20)).replace(tzinfo=None)
        assert is_expired(DEFAULT_POLICY, created, now=NOW)

    def test_stale_evidence_is_rejected(self):
        assert evidence_is_fresh(DEFAULT_POLICY, NOW - timedelta(hours=1), now=NOW)
        assert not evidence_is_fresh(DEFAULT_POLICY, NOW - timedelta(days=10), now=NOW)

    def test_future_dated_evidence_is_not_fresh(self):
        """An LLM cannot mint permanently-fresh evidence by dating it ahead."""
        assert not evidence_is_fresh(DEFAULT_POLICY, NOW + timedelta(days=1), now=NOW)

    def test_freshness_window_is_configurable_within_ceiling(self):
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

    def test_nan_or_none_reading_aborts(self):
        """The function whose job is to abort must fail toward aborting."""
        assert materially_changed(DEFAULT_POLICY, 100.0, float("nan"))
        assert materially_changed(DEFAULT_POLICY, float("inf"), 100.0)
        assert materially_changed(DEFAULT_POLICY, 100.0, None)

    def test_tolerance_is_configurable(self):
        strict = OperationsPolicy(revalidation_tolerance=0.01)
        assert materially_changed(strict, 100, 105)


class TestPolicyIsTamperResistant:
    def test_safety_ceilings_cannot_be_configured_away(self):
        """A tenant cannot widen freshness/expiry/tolerance into a no-op."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OperationsPolicy(max_evidence_age_hours=9000)     # > 336h ceiling
        with pytest.raises(ValidationError):
            OperationsPolicy(max_proposal_age_hours=9000)     # > 720h ceiling
        with pytest.raises(ValidationError):
            OperationsPolicy(revalidation_tolerance=0.9)      # > 0.5 ceiling

    def test_policy_is_frozen(self):
        from pydantic import ValidationError
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            DEFAULT_POLICY.min_confidence = 0.0

    def test_safety_rules_protect_the_source_store(self):
        assert DEFAULT_POLICY.transfer.source_min_days_cover >= 1
        assert 0 < DEFAULT_POLICY.transfer.max_share_of_source <= 1.0

    def test_confidence_and_evidence_gates_exist(self):
        assert 0 < DEFAULT_POLICY.min_confidence <= 1
        assert DEFAULT_POLICY.min_evidence_items >= 1


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


class _BrokenDB:
    async def execute(self, *a, **kw):
        raise RuntimeError("relation does not exist")


@pytest.mark.asyncio
async def test_get_policy_uses_defaults_only_when_no_row_exists():
    from app.services.operations.policy import get_policy
    assert await get_policy(_DB(None), 1) is DEFAULT_POLICY


@pytest.mark.asyncio
async def test_get_policy_refuses_on_a_malformed_row():
    """A stored-but-invalid policy must NOT silently swap in a different ruleset
    under a money gate — it refuses so the caller escalates."""
    from app.services.operations.policy import get_policy
    with pytest.raises(MalformedPolicyError):
        await get_policy(_DB({"min_confidence": "not-a-number"}), 1)


@pytest.mark.asyncio
async def test_get_policy_refuses_on_a_database_error():
    from app.services.operations.policy import get_policy
    with pytest.raises(MalformedPolicyError):
        await get_policy(_BrokenDB(), 1)


@pytest.mark.asyncio
async def test_get_policy_accepts_a_valid_override():
    from app.services.operations.policy import get_policy
    custom = await get_policy(_DB({"measurement_window_days": 21}), 1)
    assert custom.measurement_window_days == 21
    assert custom.transfer.source_min_days_cover == DEFAULT_POLICY.transfer.source_min_days_cover
