"""Operations Copilot — approval/execution unit tests.

The full approve -> revalidate -> execute -> measure path is proven live in CI
smoke (it needs FOR UPDATE / rowcount / RETURNING semantics a fake cannot fake).
Here we unit-test the pieces that ARE pure or fake-able: expiry, the draft-type
mapping, error-code mapping, and — the safety-critical one — revalidation, which
must ABORT when the world moved past the tolerance since approval.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operations.contracts import ActionType
from app.services.operations.execution import (
    _ACTION_TO_DRAFT_TYPE,
    _revalidate,
    ApprovalError,
    Conflict,
    Forbidden,
    NotFound,
    is_expired_row,
)
from app.services.operations.policy import DEFAULT_POLICY, OperationsPolicy

NOW = datetime.now(timezone.utc)


class TestExpiry:
    def test_past_expiry_is_expired(self):
        assert is_expired_row(NOW - timedelta(hours=1), now=NOW)

    def test_future_expiry_is_not_expired(self):
        assert not is_expired_row(NOW + timedelta(hours=1), now=NOW)

    def test_naive_timestamp_handled(self):
        assert is_expired_row((NOW - timedelta(hours=1)).replace(tzinfo=None), now=NOW)


class TestErrorCodes:
    def test_error_codes_map_to_http(self):
        assert NotFound().code == 404
        assert Conflict().code == 409
        assert Forbidden().code == 403
        assert ApprovalError("x").code == 400


class TestDraftMapping:
    def test_every_action_type_maps_to_a_draft_type(self):
        for a in ActionType:
            assert a.value in _ACTION_TO_DRAFT_TYPE

    def test_replenishment_maps_to_purchase_order_draft(self):
        assert _ACTION_TO_DRAFT_TYPE[ActionType.REPLENISHMENT_DRAFT.value] == "purchase_order"

    def test_no_action_maps_to_an_external_type(self):
        # review_task and purchase_order are the only internal draft targets used
        assert set(_ACTION_TO_DRAFT_TYPE.values()) <= {"purchase_order", "review_task"}


# --- Revalidation with a fake db -------------------------------------------

class _Scalar:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return self._v


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeRevalDB:
    """Answers the finding-status query and the inventory query _revalidate makes."""

    def __init__(self, snapshots=None, finding_status="open"):
        self._snaps = snapshots or []
        self._status = finding_status

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        if "from findings" in sql:
            return _Scalar(self._status)
        if "metric_inventory_state" in sql:
            return _Mappings(self._snaps)
        return _Scalar(None)


def snap(store_id, stock, velocity, reorder=50):
    return {"store_id": store_id, "item_id": 5, "current_stock": stock,
            "reorder_point": reorder, "average_daily_sales": velocity,
            "is_out_of_stock": stock <= 0}


def replen_proposal(qty, store_id=7):
    return {"id": 1, "run_id": 1, "finding_id": 9,
            "action_type": ActionType.REPLENISHMENT_DRAFT.value,
            "calculated_parameters": {"quantity": qty},
            "target_item_ids": [5], "target_store_ids": [store_id]}


def transfer_proposal(qty, src=9, dst=7):
    return {"id": 1, "run_id": 1, "finding_id": 9,
            "action_type": ActionType.STOCK_TRANSFER_DRAFT.value,
            "calculated_parameters": {"quantity": qty, "source_store_id": src,
                                      "destination_store_id": dst},
            "target_item_ids": [5], "target_store_ids": [src, dst]}


@pytest.mark.asyncio
class TestRevalidation:
    async def test_replenishment_unchanged_passes(self):
        # live stock still 0/velocity 8 -> recompute ≈ the approved quantity
        db = FakeRevalDB([snap(7, 0, 8)])
        # compute the true quantity the calculator would produce, approve that
        from app.services.operations.calculations import calculate_replenishment
        q = calculate_replenishment(current_stock=0, daily_velocity=8,
                                    settings=DEFAULT_POLICY.replenishment).quantity
        ok, detail = await _revalidate(db, 1, replen_proposal(q), DEFAULT_POLICY)
        assert ok, detail

    async def test_replenishment_materially_changed_aborts(self):
        # approved 200 units, but the store is now fully stocked -> not justified
        db = FakeRevalDB([snap(7, 5000, 8)])
        ok, detail = await _revalidate(db, 1, replen_proposal(200), DEFAULT_POLICY)
        assert not ok
        assert "no longer justified" in detail or "moved" in detail

    async def test_replenishment_quantity_drift_aborts(self):
        # live velocity collapsed so the recomputed qty is far below approved 200
        db = FakeRevalDB([snap(7, 0, 1)])
        ok, detail = await _revalidate(db, 1, replen_proposal(200), DEFAULT_POLICY)
        assert not ok and "fresh approval required" in detail

    async def test_missing_snapshot_aborts(self):
        db = FakeRevalDB([])            # store vanished from inventory
        ok, detail = await _revalidate(db, 1, replen_proposal(100), DEFAULT_POLICY)
        assert not ok

    async def test_investigation_passes_when_finding_open(self):
        db = FakeRevalDB(finding_status="open")
        prop = {"action_type": ActionType.INVESTIGATION_TASK.value, "finding_id": 9,
                "calculated_parameters": {}}
        ok, _ = await _revalidate(db, 1, prop, DEFAULT_POLICY)
        assert ok

    async def test_investigation_aborts_if_finding_resolved(self):
        db = FakeRevalDB(finding_status="resolved")
        prop = {"action_type": ActionType.INVESTIGATION_TASK.value, "finding_id": 9,
                "calculated_parameters": {}}
        ok, detail = await _revalidate(db, 1, prop, DEFAULT_POLICY)
        assert not ok and "resolved" in detail

    async def test_transfer_unchanged_passes(self):
        from app.services.operations.calculations import calculate_transfer
        snaps = [snap(9, 500, 2), snap(7, 0, 20)]
        q = calculate_transfer(source_stock=500, source_velocity=2,
                               destination_stock=0, destination_velocity=20,
                               settings=DEFAULT_POLICY.transfer).quantity
        db = FakeRevalDB(snaps)
        ok, detail = await _revalidate(db, 1, transfer_proposal(q), DEFAULT_POLICY)
        assert ok, detail

    async def test_transfer_source_now_short_aborts(self):
        # the donor is now itself out of stock -> transfer no longer safe
        db = FakeRevalDB([snap(9, 0, 2), snap(7, 0, 20)])
        ok, detail = await _revalidate(db, 1, transfer_proposal(200), DEFAULT_POLICY)
        assert not ok


# --- Approval GATE tests (the safety-critical decision path) ----------------

from sqlalchemy.exc import IntegrityError
from app.services.operations.execution import (
    approve_proposal, reject_proposal, cancel_proposal)


class _CasResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeGateDB:
    """Enough of the async session to exercise approve/reject/cancel up to (not
    through) execution: it serves the proposal row, an empty policy (-> defaults),
    a configurable CAS rowcount, and swallows event/run writes. Set raise_on_cas
    to simulate the cross-proposal idempotency-key unique violation."""

    def __init__(self, proposal, cas_rowcount=1, raise_on_cas=False,
                 finding_status="open"):
        self._prop = proposal            # None => not found (e.g. cross-tenant)
        self._cas = cas_rowcount
        self._raise = raise_on_cas
        self._finding_status = finding_status
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        if "from operations_proposals" in sql:
            return _Mappings([self._prop] if self._prop else [])
        if "from tenant_operations_policies" in sql:
            return _Scalar(None)          # -> DEFAULT_POLICY
        if "from findings" in sql:
            return _Scalar(self._finding_status)
        if "update operations_proposals" in sql:
            if self._raise:
                raise IntegrityError("stmt", {}, Exception("dup key"))
            return _CasResult(self._cas)
        if sql.startswith("insert into operations_events") or \
                "update operations_runs" in sql:
            return _CasResult(1)
        return _CasResult(1)

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


def awaiting_proposal(version=3, key=None, status="awaiting_approval",
                      action="investigation_task", stores=(4,), expires=None,
                      tenant=1):
    return {"id": 1, "tenant_id": tenant, "run_id": 1, "finding_id": 9,
            "action_type": action, "status": status,
            "calculated_parameters": {}, "target_store_ids": list(stores),
            "target_item_ids": [], "risk_level": "low", "version": version,
            "idempotency_key": key, "expires_at": expires, "executed_ref": None}


def approver(role="store_manager", stores=(4,), tenant=1):
    return {"id": 1, "email": "m@test", "role": role, "tenant_id": tenant,
            "permissions": {"accessible_stores": list(stores)}}


@pytest.mark.asyncio
class TestApprovalGate:
    async def test_cross_tenant_proposal_is_not_found(self):
        # _load_proposal filters by the user's tenant; a foreign proposal => None
        db = FakeGateDB(proposal=None)
        with pytest.raises(NotFound):
            await approve_proposal(db, user=approver(), proposal_id=1,
                                   expected_version=3, idempotency_key="key12345")

    async def test_out_of_scope_approver_is_forbidden(self):
        db = FakeGateDB(awaiting_proposal(stores=(99,)))  # proposal targets store 99
        with pytest.raises(Forbidden):
            await approve_proposal(db, user=approver(stores=(4,)), proposal_id=1,
                                   expected_version=3, idempotency_key="key12345")

    async def test_wrong_role_is_forbidden(self):
        # analyst can never approve
        db = FakeGateDB(awaiting_proposal())
        with pytest.raises(Forbidden):
            await approve_proposal(db, user=approver(role="analyst"), proposal_id=1,
                                   expected_version=3, idempotency_key="key12345")

    async def test_stale_version_conflicts(self):
        db = FakeGateDB(awaiting_proposal(), cas_rowcount=0)  # CAS matches nothing
        with pytest.raises(Conflict):
            await approve_proposal(db, user=approver(), proposal_id=1,
                                   expected_version=2, idempotency_key="key12345")
        assert db.rolled_back >= 1

    async def test_cross_proposal_idempotency_key_is_409_not_500(self):
        db = FakeGateDB(awaiting_proposal(), raise_on_cas=True)
        with pytest.raises(Conflict):
            await approve_proposal(db, user=approver(), proposal_id=1,
                                   expected_version=3, idempotency_key="reusedkey")
        assert db.rolled_back >= 1

    async def test_expired_proposal_conflicts(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        db = FakeGateDB(awaiting_proposal(expires=past))
        with pytest.raises(Conflict):
            await approve_proposal(db, user=approver(), proposal_id=1,
                                   expected_version=3, idempotency_key="key12345")

    async def test_already_rejected_replay_is_idempotent(self):
        db = FakeGateDB(awaiting_proposal(status="rejected", key="samekey1"))
        out = await reject_proposal(db, user=approver(), proposal_id=1,
                                    expected_version=3, reason="no", idempotency_key="samekey1")
        assert out["idempotent"] is True and out["status"] == "rejected"

    async def test_reject_out_of_scope_is_forbidden(self):
        db = FakeGateDB(awaiting_proposal(stores=(99,)))
        with pytest.raises(Forbidden):
            await reject_proposal(db, user=approver(stores=(4,)), proposal_id=1,
                                  expected_version=3, reason="no", idempotency_key="key12345")

    async def test_cancel_stale_version_conflicts(self):
        db = FakeGateDB(awaiting_proposal(), cas_rowcount=0)
        with pytest.raises(Conflict):
            await cancel_proposal(db, user=approver(), proposal_id=1, expected_version=2)

    async def test_cannot_cancel_executed(self):
        db = FakeGateDB(awaiting_proposal(status="executed"))
        with pytest.raises(Conflict):
            await cancel_proposal(db, user=approver(), proposal_id=1, expected_version=3)

    async def test_approved_replay_drives_execution_not_stuck(self):
        # status='approved', matching key => must RESUME execution (invocation B).
        # An investigation whose finding is now resolved supersedes on revalidation,
        # proving execute_proposal ran rather than returning a stuck 'approved'.
        db = FakeGateDB(awaiting_proposal(status="approved", key="rk123456"),
                        finding_status="resolved")
        out = await approve_proposal(db, user=approver(), proposal_id=1,
                                     expected_version=3, idempotency_key="rk123456")
        assert out["status"] == "superseded"
