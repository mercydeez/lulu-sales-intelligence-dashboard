"""
E5-1c — SCIM admin token management. Pure + fake-session; no DB/network/secrets.
Covers create-returns-raw-once, hash-stored-not-raw, list-metadata-only, rotate,
revoke, cross-tenant safety, and that the admin routes are role-guarded.
"""
from types import SimpleNamespace

import pytest

from app.services import scim
from app.routes import scim as scim_routes


def _settings(**over):
    base = dict(scim_enabled=True, scim_audit_enabled=False, scim_token_ttl_days=365)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(scim, "get_settings", lambda: _settings())


class _R:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _S:
    def __init__(self, responder):
        self.responder = responder
        self.executed = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params or {}))
        return self.responder(sql, params or {})

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_create_token_returns_raw_once_and_stores_hash():
    captured = {}

    def responder(sql, p):
        if "INSERT INTO tenant_scim_tokens" in sql:
            captured.update(p)
            return _R([{"id": 1, "name": p["name"], "token_prefix": p["prefix"],
                        "scopes": p["scopes"], "created_at": "now", "expires_at": None}])
        return _R()
    out = await scim.create_scim_token(_S(responder), tenant_id=3, name="Okta", created_by=9)
    raw = out["raw_token"]
    assert raw.startswith("scim_")
    # what's persisted is the HASH, never the raw token
    assert captured["hash"] == scim.hash_scim_token(raw)
    assert captured["hash"] != raw
    assert out["row"]["token_prefix"] == raw[:12]


def test_list_query_never_selects_token_hash():
    # Static guarantee: the list query does not SELECT the hash column (ignore comments).
    import inspect
    code = "\n".join(l for l in inspect.getsource(scim.list_scim_tokens).splitlines()
                     if not l.lstrip().startswith("#"))
    assert "token_hash" not in code, "list_scim_tokens must not select/return token_hash"


@pytest.mark.asyncio
async def test_list_tokens_returns_metadata_only():
    def responder(sql, p):
        return _R([{"id": 1, "name": "t", "token_prefix": "scim_abc123", "scopes": "scim:read",
                    "created_by_user_id": 9, "last_used_at": None, "expires_at": None,
                    "revoked_at": None, "created_at": "now"}])
    rows = await scim.list_scim_tokens(_S(responder), 3)
    assert rows and "token_hash" not in rows[0] and "token" not in rows[0]


@pytest.mark.asyncio
async def test_rotate_revokes_old_and_issues_new():
    events = []

    def responder(sql, p):
        events.append(sql)
        if "SELECT * FROM tenant_scim_tokens WHERE id" in sql:
            return _R([{"id": 5, "name": "old", "scopes": "scim:read scim:write"}])
        if "INSERT INTO tenant_scim_tokens" in sql:
            return _R([{"id": 6, "name": p["name"], "token_prefix": p["prefix"],
                        "scopes": p["scopes"], "created_at": "now", "expires_at": None}])
        return _R()
    out = await scim.rotate_scim_token(_S(responder), tenant_id=3, token_id=5, rotated_by=9)
    joined = " ".join(events)
    assert "UPDATE tenant_scim_tokens SET revoked_at" in joined  # old revoked
    assert out["row"]["id"] == 6 and out["raw_token"].startswith("scim_")  # new issued once


@pytest.mark.asyncio
async def test_revoke_token():
    def responder(sql, p):
        if "SELECT * FROM tenant_scim_tokens WHERE id" in sql:
            return _R([{"id": 5, "name": "t"}])
        return _R()
    out = await scim.revoke_scim_token(_S(responder), tenant_id=3, token_id=5, revoked_by=9)
    assert out["revoked"] is True


@pytest.mark.asyncio
async def test_cross_tenant_token_access_404():
    # token id belongs to another tenant -> _get_token returns None -> 404
    with pytest.raises(scim.SCIMError) as e:
        await scim.revoke_scim_token(_S(lambda s, p: _R([])), tenant_id=3, token_id=999, revoked_by=9)
    assert e.value.status == 404


def test_admin_routes_are_role_guarded():
    """Every /admin/tokens route must depend on require_role (admin-only)."""
    admin_paths = [r for r in scim_routes.router.routes
                   if getattr(r, "path", "").startswith("/admin/tokens")]
    assert admin_paths, "no admin token routes found"
    for route in admin_paths:
        deps = getattr(route.dependant, "dependencies", [])
        guarded = any("require_role" in getattr(d.call, "__qualname__", "") for d in deps)
        assert guarded, f"{route.path} [{route.methods}] is not role-guarded"
