"""
Phase 12 — tenant data rights (export + delete-on-request).

DB-free coverage: routes are registered and admin-gated; exports omit credential
columns and coerce DB types to JSON-safe primitives; deletion is never executed
inline (the service only records a request).
"""
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.services import data_rights_service as dr
from tests.conftest import registered_paths


def test_data_rights_routes_registered():
    from app.main import app
    paths = registered_paths(app)
    assert "/api/data-rights/export" in paths
    assert "/api/data-rights/requests" in paths


def test_data_rights_requires_auth():
    from app.main import app
    client = TestClient(app)
    # No bearer token → blocked before any DB access.
    assert client.get("/api/data-rights/export").status_code in (401, 403)
    assert client.get("/api/data-rights/requests").status_code in (401, 403)
    assert client.post("/api/data-rights/requests", json={"kind": "export"}).status_code in (401, 403)


def test_sensitive_columns_are_excluded():
    # Credential material must never appear in an export.
    for col in ("password_hash", "key_hash", "totp_secret", "reset_token"):
        assert col in dr._SENSITIVE_COLUMNS


def test_jsonable_coerces_db_types():
    row = {"a": datetime(2026, 6, 28, 12, 0, 0), "b": Decimal("3.50"), "c": "x", "d": 7}
    out = dr._jsonable(row)
    assert out["a"] == "2026-06-28T12:00:00"
    assert out["b"] == 3.5 and isinstance(out["b"], float)
    assert out["c"] == "x" and out["d"] == 7


async def test_create_request_rejects_unknown_kind():
    import pytest
    # kind is validated before any DB access, so db=None is never touched.
    with pytest.raises(ValueError):
        await dr.create_request(db=None, tenant_id=1, kind="nuke")


def test_request_model_validates_kind():
    import pytest
    from pydantic import ValidationError
    from app.routes.data_rights import DataRequest
    assert DataRequest(kind="export").kind == "export"
    assert DataRequest(kind="delete").kind == "delete"
    with pytest.raises(ValidationError):
        DataRequest(kind="nuke")
