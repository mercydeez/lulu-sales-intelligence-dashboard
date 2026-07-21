"""Operations Copilot — route-wiring tests (no DB).

Asserts the thin route layer does its job: the operator gate blocks non-operators,
request bodies are validated (version + idempotency key), and ApprovalError codes
map to the right HTTP status. The services are stubbed — their logic is tested in
their own suites — so these tests isolate the wiring.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_deps import get_current_user
from app.services.database import get_db
import app.routes.operations as ops
from app.services.operations.execution import Conflict, Forbidden, NotFound


def make_client(user):
    app = FastAPI()
    app.include_router(ops.router, prefix="/api/operations")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: None      # services are stubbed
    return TestClient(app, raise_server_exceptions=False)


OPERATOR = {"id": 1, "email": "m@test", "role": "regional_manager", "tenant_id": 1,
            "permissions": {"accessible_stores": [1]}}
VIEWER = {"id": 2, "email": "a@test", "role": "analyst", "tenant_id": 1,
          "permissions": {"accessible_stores": []}}


@pytest.fixture(autouse=True)
def _no_publish(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(ops, "publish_operations_event", _noop)


class TestOperatorGate:
    def test_analyst_is_blocked_from_approve(self, monkeypatch):
        client = make_client(VIEWER)
        r = client.post("/api/operations/proposals/1/approve",
                        json={"version": 1, "idempotency_key": "abcdefgh"})
        assert r.status_code == 403
        assert "Operator" in r.json()["detail"]

    def test_operator_passes_the_gate(self, monkeypatch):
        async def fake_approve(*a, **k):
            return {"proposal_id": 1, "status": "executed"}
        monkeypatch.setattr(ops.execution_svc, "approve_proposal", fake_approve)
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/approve",
                        json={"version": 1, "idempotency_key": "abcdefgh"})
        assert r.status_code == 200
        assert r.json()["status"] == "executed"

    def test_permission_operator_passes(self, monkeypatch):
        async def fake_cancel(*a, **k):
            return {"proposal_id": 1, "status": "cancelled"}
        monkeypatch.setattr(ops.execution_svc, "cancel_proposal", fake_cancel)
        user = {"id": 3, "email": "p@test", "role": "buyer", "tenant_id": 1,
                "permissions": {"can_manage_inventory": True}}
        client = make_client(user)
        r = client.post("/api/operations/proposals/1/cancel", json={"version": 1})
        assert r.status_code == 200


class TestValidation:
    def test_approve_requires_idempotency_key(self):
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/approve", json={"version": 1})
        assert r.status_code == 422

    def test_short_idempotency_key_is_rejected(self):
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/approve",
                        json={"version": 1, "idempotency_key": "short"})
        assert r.status_code == 422

    def test_reject_requires_a_reason(self):
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/reject",
                        json={"version": 1, "idempotency_key": "abcdefgh"})
        assert r.status_code == 422

    def test_version_must_be_positive(self):
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/approve",
                        json={"version": 0, "idempotency_key": "abcdefgh"})
        assert r.status_code == 422


class TestErrorMapping:
    @pytest.mark.parametrize("exc,code", [
        (NotFound(), 404), (Conflict(), 409), (Forbidden(), 403)])
    def test_approval_errors_map_to_status(self, monkeypatch, exc, code):
        async def raiser(*a, **k):
            raise exc
        monkeypatch.setattr(ops.execution_svc, "approve_proposal", raiser)
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/approve",
                        json={"version": 1, "idempotency_key": "abcdefgh"})
        assert r.status_code == code

    def test_reject_conflict_maps_to_409(self, monkeypatch):
        async def raiser(*a, **k):
            raise Conflict("stale")
        monkeypatch.setattr(ops.execution_svc, "reject_proposal", raiser)
        client = make_client(OPERATOR)
        r = client.post("/api/operations/proposals/1/reject",
                        json={"version": 1, "idempotency_key": "abcdefgh", "reason": "no"})
        assert r.status_code == 409


class TestRecommendWiring:
    def test_recommend_delegates_and_returns(self, monkeypatch):
        async def fake_reco(db, *, user, finding_id):
            return {"run_id": 5, "status": "awaiting_approval", "proposal_id": 8}
        monkeypatch.setattr(ops, "recommend_for_finding", fake_reco)
        client = make_client(OPERATOR)
        r = client.post("/api/operations/findings/42/recommend")
        assert r.status_code == 201
        assert r.json()["run_id"] == 5
