"""
Part III-E — procure-to-pay system of record.

Unit-covers the PO lifecycle state machine and approval-threshold guard (the
correctness-critical logic) against a mocked session, and confirms the routes
are registered with the right auth posture. The forecast→PO generation and
persistence are exercised by the live integration check.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services import procurement_service as proc


def _session_with_po(status: str, total: float):
    session = MagicMock()
    row = MagicMock(status=status, total_amount=total)
    result = MagicMock()
    result.fetchone.return_value = row
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def test_status_machine_allows_forward_transitions():
    assert "approved" in proc.STATUS_TRANSITIONS["draft"]
    assert "sent" in proc.STATUS_TRANSITIONS["approved"]
    assert "received" in proc.STATUS_TRANSITIONS["sent"]
    # Terminal states go nowhere.
    assert proc.STATUS_TRANSITIONS["received"] == set()
    assert proc.STATUS_TRANSITIONS["cancelled"] == set()


@pytest.mark.asyncio
async def test_transition_rejects_illegal_jump():
    session = _session_with_po("draft", 1000.0)
    with pytest.raises(ValueError, match="Cannot move PO"):
        await proc.transition_status(session, tenant_id=1, po_id=1, new_status="received")


@pytest.mark.asyncio
async def test_transition_enforces_approval_threshold():
    session = _session_with_po("draft", 5000.0)
    with pytest.raises(ValueError, match="exceeds approval threshold"):
        await proc.transition_status(session, tenant_id=1, po_id=1,
                                     new_status="approved", approval_threshold=1000.0)


@pytest.mark.asyncio
async def test_transition_approve_under_threshold_succeeds():
    session = _session_with_po("draft", 500.0)
    out = await proc.transition_status(session, tenant_id=1, po_id=1,
                                       new_status="approved", approval_threshold=1000.0)
    assert out["status"] == "approved"


@pytest.mark.asyncio
async def test_transition_missing_po_raises():
    session = MagicMock()
    result = MagicMock(); result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(ValueError, match="not found"):
        await proc.transition_status(session, tenant_id=1, po_id=999, new_status="approved")


def test_receiving_states_in_machine():
    assert "partially_received" in proc.STATUS_TRANSITIONS["sent"]
    assert "received" in proc.STATUS_TRANSITIONS["partially_received"]
    assert proc.RECEIVABLE_STATUSES == ("approved", "sent", "partially_received")


@pytest.mark.asyncio
async def test_receive_rejects_non_receivable_status():
    session = _session_with_po("draft", 100.0)  # draft can't be received
    with pytest.raises(ValueError, match="Cannot receive"):
        await proc.receive_po(session, tenant_id=1, po_id=1)


@pytest.mark.asyncio
async def test_receive_missing_po_raises():
    session = MagicMock()
    result = MagicMock(); result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(ValueError, match="not found"):
        await proc.receive_po(session, tenant_id=1, po_id=999)


@pytest.mark.asyncio
async def test_record_invoice_missing_po_raises():
    session = MagicMock()
    result = MagicMock(); result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(ValueError, match="not found"):
        await proc.record_invoice(session, tenant_id=1, po_id=999,
                                  invoice_number="INV-1",
                                  lines=[{"item_id": 1, "quantity": 1, "unit_cost": 10.0}])


@pytest.mark.asyncio
async def test_three_way_match_missing_invoice_raises():
    session = MagicMock()
    result = MagicMock(); result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(ValueError, match="Invoice not found"):
        await proc.three_way_match(session, tenant_id=1, invoice_id=999)


def test_procurement_routes_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/procurement/suppliers" in paths
    assert "/api/procurement/purchase-orders/generate" in paths
    assert "/api/procurement/purchase-orders" in paths
    assert "/api/procurement/purchase-orders/{po_id}/status" in paths
    assert "/api/procurement/purchase-orders/{po_id}/receive" in paths
    assert "/api/procurement/purchase-orders/{po_id}/invoices" in paths
    assert "/api/procurement/invoices/{invoice_id}/match" in paths


def test_procurement_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    assert client.get("/api/procurement/suppliers").status_code == 401
    assert client.get("/api/procurement/purchase-orders").status_code == 401
