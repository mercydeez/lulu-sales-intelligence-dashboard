"""
Phase 6 — data-source tenant isolation.

Before this phase, get_active_source()/set_active()/delete_source()/
get_source_with_connection()/record_test_result() operated GLOBALLY by id, letting
one tenant read or flip another tenant's active source. These tests assert every
operation is now tenant-scoped at the SQL layer (verified without a live DB by
capturing the executed statements + params), that one active source is per-tenant,
and that connector testing is flag-gated.
"""
from unittest.mock import patch

import pytest

from app.services import data_sources as ds


class FakeResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class FakeSession:
    """Records every execute(sql, params) and returns a queued result."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return self.results.pop(0) if self.results else FakeResult()

    async def commit(self):
        self.committed = True


def _patch_session(session):
    return patch("app.services.data_sources.async_session", lambda: session)


def _all_params(session):
    return [p for _sql, p in session.calls]


class TestTenantScoping:
    async def test_get_active_source_filters_by_tenant(self):
        sess = FakeSession([FakeResult(one=None)])
        with _patch_session(sess):
            result = await ds.get_active_source(tenant_id=7)
        assert result is None
        sql, params = sess.calls[0]
        assert "tenant_id" in sql
        assert params["tid"] == 7

    async def test_get_source_with_connection_filters_by_tenant(self):
        sess = FakeSession([FakeResult(one=None)])
        with _patch_session(sess):
            result = await ds.get_source_with_connection(99, tenant_id=4)
        assert result is None
        sql, params = sess.calls[0]
        assert "tenant_id" in sql and params["tid"] == 4 and params["id"] == 99

    async def test_set_active_scopes_every_statement_to_tenant(self):
        # exists check returns a row, then two UPDATEs.
        sess = FakeSession([FakeResult(one=(1,)), FakeResult(), FakeResult()])
        with _patch_session(sess):
            ok = await ds.set_active(5, tenant_id=3)
        assert ok is True
        for sql, params in sess.calls:
            assert params.get("tid") == 3
            assert "tenant_id" in sql

    async def test_set_active_rejects_id_from_another_tenant(self):
        # The existence check (scoped to the caller's tenant) finds nothing.
        sess = FakeSession([FakeResult(one=None)])
        with _patch_session(sess):
            ok = await ds.set_active(5, tenant_id=3)
        assert ok is False
        # Only the scoped existence check ran — no global deactivation happened.
        assert len(sess.calls) == 1
        assert sess.calls[0][1]["tid"] == 3

    async def test_delete_source_filters_by_tenant(self):
        sess = FakeSession([FakeResult(one=None)])  # not found in this tenant
        with _patch_session(sess):
            ok, msg = await ds.delete_source(5, tenant_id=2)
        assert ok is False and msg == "Not found"
        assert sess.calls[0][1]["tid"] == 2 and "tenant_id" in sess.calls[0][0]

    async def test_record_test_result_filters_by_tenant(self):
        sess = FakeSession([FakeResult()])
        with _patch_session(sess):
            await ds.record_test_result(5, True, "ok", tenant_id=8)
        sql, params = sess.calls[0]
        assert "tenant_id" in sql and params["tid"] == 8


class TestConnectorGate:
    def test_connectors_disabled_blocks(self):
        from app.routes import data_sources as routes
        from app.config import Settings
        from fastapi import HTTPException
        s = Settings(environment="production",
                     jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
                     secret_key="another-strong-production-secret-key-for-the-app-layer",
                     database_url="postgresql+asyncpg://u:str0ngp@db:5432/d",
                     use_rls_role=True,
                     enable_data_source_connectors=False)
        with patch.object(routes, "get_settings", return_value=s):
            with pytest.raises(HTTPException) as exc:
                routes._require_connectors_enabled()
        assert exc.value.status_code == 403

    def test_connectors_enabled_allows(self):
        from app.routes import data_sources as routes
        from app.config import Settings
        s = Settings(environment="development", enable_data_source_connectors=True,
                     jwt_secret_key="a-strong-enough-dev-secret-key-32-characters",
                     secret_key="another-strong-enough-dev-secret-key-32chars")
        with patch.object(routes, "get_settings", return_value=s):
            routes._require_connectors_enabled()  # no raise


class TestAdapterUsesTenantContext:
    async def test_active_external_source_passes_request_tenant(self):
        from app.services import source_adapters
        seen = {}

        async def _fake_get_active_source(tenant_id=1):
            seen["tenant_id"] = tenant_id
            return None

        with patch.object(source_adapters, "get_active_source", _fake_get_active_source):
            await source_adapters.active_external_source(tenant_id=12)
        assert seen["tenant_id"] == 12
