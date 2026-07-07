"""
E5-1c — SCIM provisioning. Pure + fake-session; NO Docker/Postgres/Redis/IdP/
network/secrets. Covers token security, SCIM shaping, tenant-scoped auth, and the
user-lifecycle guardrails (analyst-only, deactivate-not-delete, last-admin guard).
"""
from types import SimpleNamespace

import pytest

from app.services import scim


def _settings(**over):
    base = dict(scim_enabled=True, scim_audit_enabled=False, scim_max_page_size=100,
                scim_default_role="analyst", scim_token_ttl_days=365,
                scim_deactivate_revokes_tokens=False, scim_allow_reactivation=True,
                scim_allow_admin_role_mapping=False, scim_group_mapping_enabled=False)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(scim, "get_settings", lambda: _settings())


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
def test_token_generate_and_prefix():
    raw, prefix = scim.generate_scim_token()
    assert raw.startswith("scim_") and prefix == raw[:12] and len(raw) > 20


def test_token_hash_and_constant_time_verify():
    raw, _ = scim.generate_scim_token()
    h = scim.hash_scim_token(raw)
    assert h != raw and len(h) == 64
    assert scim.verify_scim_token(raw, h) is True
    assert scim.verify_scim_token(raw + "x", h) is False
    assert scim.verify_scim_token("", h) is False


def test_parse_bearer():
    assert scim.parse_bearer("Bearer abc.def") == "abc.def"
    assert scim.parse_bearer("bearer xyz") == "xyz"
    assert scim.parse_bearer("Basic abc") is None
    assert scim.parse_bearer(None) is None
    assert scim.parse_bearer("Bearer ") is None


def test_active_status_mapping():
    assert scim.status_to_active("active") is True
    assert scim.status_to_active("inactive") is False
    assert scim.active_to_status(True) == "active"
    assert scim.active_to_status(False) == "inactive"


def test_username_filter():
    assert scim.parse_username_filter('userName eq "A@B.com"') == "a@b.com"
    assert scim.parse_username_filter('displayName eq "x"') is None
    assert scim.parse_username_filter(None) is None


# ---------------------------------------------------------------------------
# SCIM resource shaping
# ---------------------------------------------------------------------------
def test_user_resource_exposes_no_secrets():
    user = {"id": 42, "email": "u@x.com", "first_name": "U", "last_name": "X",
            "status": "active", "role": "super_admin", "password_hash": "SECRET"}
    r = scim.scim_user_resource(user, {"scim_user_name": "u@x.com", "external_id": "ext1"},
                                "https://api/api/scim/v2/acme")
    assert r["id"] == "42" and r["userName"] == "u@x.com" and r["active"] is True
    assert r["emails"][0]["value"] == "u@x.com" and r["externalId"] == "ext1"
    assert r["meta"]["resourceType"] == "User"
    blob = str(r)
    assert "password_hash" not in blob and "SECRET" not in blob and "super_admin" not in blob


def test_error_shape():
    e = scim.scim_error(404, "nope", "notFound")
    assert e["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    assert e["status"] == "404" and e["detail"] == "nope" and e["scimType"] == "notFound"


def test_list_response_shape():
    lr = scim.scim_list_response([{"id": "1"}], total=5, start_index=1, items_per_page=1)
    assert lr["totalResults"] == 5 and lr["startIndex"] == 1
    assert lr["itemsPerPage"] == 1 and lr["Resources"] == [{"id": "1"}]


def test_service_provider_config_and_schema_and_types():
    spc = scim.service_provider_config()
    assert spc["patch"]["supported"] is True and spc["changePassword"]["supported"] is False
    us = scim.user_schema()
    assert us["id"] == scim.SCIM_USER_SCHEMA
    rts = scim.resource_types("https://api/api/scim/v2/acme")
    assert any(rt["id"] == "User" for rt in rts)


def test_extract_user_fields_ignores_role():
    body = {"userName": "New@X.com", "role": "super_admin",
            "name": {"givenName": "New", "familyName": "Person"},
            "emails": [{"value": "New@X.com", "primary": True}], "active": True, "externalId": "e1"}
    f = scim.extract_user_fields(body)
    assert f["email"] == "new@x.com" and f["given_name"] == "New" and f["family_name"] == "Person"
    assert "role" not in f  # role is NEVER taken from the SCIM body


def test_apply_patch_active_and_name():
    cur = {"active": True, "given_name": "A", "family_name": "B"}
    off = scim.apply_patch_ops(cur, {"Operations": [{"op": "replace", "path": "active", "value": False}]})
    assert off["active"] is False
    named = scim.apply_patch_ops(cur, {"Operations": [
        {"op": "replace", "value": {"name": {"givenName": "New"}}}]})
    assert named["given_name"] == "New"
    on = scim.apply_patch_ops({"active": False}, {"Operations": [
        {"op": "replace", "path": "active", "value": "true"}]})
    assert on["active"] is True


def test_role_mapping_is_safe():
    assert scim.role_mapping_is_safe("analyst") is True
    assert scim.role_mapping_is_safe("store_manager") is True
    assert scim.role_mapping_is_safe("super_admin") is False  # blocked by default


# ---------------------------------------------------------------------------
# Fake session
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# SCIM bearer authentication (tenant-scoped, constant-time)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auth_disabled_returns_401(monkeypatch):
    monkeypatch.setattr(scim, "get_settings", lambda: _settings(scim_enabled=False))
    with pytest.raises(scim.SCIMError) as e:
        await scim.authenticate_scim(_S(lambda s, p: _R()), "acme", "Bearer x")
    assert e.value.status == 401


@pytest.mark.asyncio
async def test_auth_missing_bearer_401():
    with pytest.raises(scim.SCIMError) as e:
        await scim.authenticate_scim(_S(lambda s, p: _R()), "acme", None)
    assert e.value.status == 401


@pytest.mark.asyncio
async def test_auth_invalid_token_401():
    def responder(sql, p):
        if "FROM tenants WHERE slug" in sql:
            return _R([{"id": 1}])
        if "FROM tenant_scim_tokens" in sql:
            return _R([{"id": 9, "token_hash": scim.hash_scim_token("the-real-one")}])
        return _R()
    with pytest.raises(scim.SCIMError) as e:
        await scim.authenticate_scim(_S(responder), "acme", "Bearer wrong-token")
    assert e.value.status == 401


@pytest.mark.asyncio
async def test_auth_valid_token_ok():
    raw = "scim_valid_token_value"
    def responder(sql, p):
        if "FROM tenants WHERE slug" in sql:
            return _R([{"id": 3}])
        if "FROM tenant_scim_tokens" in sql:
            return _R([{"id": 9, "token_hash": scim.hash_scim_token(raw)}])
        return _R()
    tid, token = await scim.authenticate_scim(_S(responder), "acme", f"Bearer {raw}")
    assert tid == 3 and token["id"] == 9


@pytest.mark.asyncio
async def test_auth_cross_tenant_token_rejected():
    # tenant resolves, but the tenant's active tokens do NOT include this token
    raw = "scim_token_for_other_tenant"
    def responder(sql, p):
        if "FROM tenants WHERE slug" in sql:
            return _R([{"id": 1}])
        if "FROM tenant_scim_tokens" in sql:
            return _R([])  # tenant 1 has no token matching -> reject
        return _R()
    with pytest.raises(scim.SCIMError) as e:
        await scim.authenticate_scim(_S(responder), "acme", f"Bearer {raw}")
    assert e.value.status == 401


@pytest.mark.asyncio
async def test_auth_unknown_tenant_does_not_leak():
    # tenant slug not found -> still 401 (no "tenant not found" distinction)
    with pytest.raises(scim.SCIMError) as e:
        await scim.authenticate_scim(_S(lambda s, p: _R()), "ghost", "Bearer whatever")
    assert e.value.status == 401


# ---------------------------------------------------------------------------
# User lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_user_is_analyst_never_admin(monkeypatch):
    # even if the default role is misconfigured to super_admin, it clamps to analyst
    monkeypatch.setattr(scim, "get_settings", lambda: _settings(scim_default_role="super_admin"))
    captured = {}

    def responder(sql, p):
        if "FROM scim_external_users WHERE tenant_id" in sql:
            return _R([])
        if "FROM users WHERE tenant_id" in sql:
            return _R([])
        if "INSERT INTO users" in sql:
            captured["role"] = p.get("role")
            return _R([{"id": 500}])
        if "INSERT INTO scim_external_users" in sql:
            return _R()
        # get_user_resource load
        if "SELECT id, email, first_name" in sql:
            return _R([{"id": 500, "email": "new@x.com", "first_name": "New",
                        "last_name": "User", "role": "analyst", "status": "active"}])
        if "FROM scim_external_users WHERE tenant_id = :tid AND user_id" in sql:
            return _R([{"scim_user_name": "new@x.com", "external_id": None}])
        return _R()
    body = {"userName": "new@x.com", "emails": [{"value": "new@x.com", "primary": True}],
            "name": {"givenName": "New", "familyName": "User"}, "active": True}
    resource, status = await scim.create_user(_S(responder), 7, body, "https://api/api/scim/v2/acme")
    assert status == 201
    assert captured["role"] == "analyst"  # clamped — never super_admin
    assert resource["userName"] == "new@x.com"


@pytest.mark.asyncio
async def test_create_user_duplicate_conflict():
    def responder(sql, p):
        if "FROM scim_external_users WHERE tenant_id" in sql:
            return _R([{"user_id": 1}])  # already exists
        return _R()
    with pytest.raises(scim.SCIMError) as e:
        await scim.create_user(_S(responder), 7, {"userName": "dup@x.com"}, "https://api")
    assert e.value.status == 409


@pytest.mark.asyncio
async def test_delete_user_deactivates_not_deletes():
    calls = []

    def responder(sql, p):
        calls.append(sql)
        if "SELECT id, email, first_name" in sql:
            return _R([{"id": 5, "email": "u@x.com", "first_name": "U", "last_name": "X",
                        "role": "analyst", "status": "active"}])
        return _R()
    await scim.delete_user(_S(responder), 7, 5)
    joined = " ".join(calls)
    assert "UPDATE users SET status = CAST(:st AS user_status)" in joined
    assert "DELETE FROM users" not in joined  # never hard-deletes


@pytest.mark.asyncio
async def test_deactivate_last_admin_blocked():
    def responder(sql, p):
        if "SELECT id, email, first_name" in sql:
            return _R([{"id": 5, "email": "boss@x.com", "first_name": "B", "last_name": "O",
                        "role": "super_admin", "status": "active"}])
        if "COUNT(*) AS n FROM users WHERE tenant_id" in sql:
            return _R([{"n": 1}])  # only one active admin
        return _R()
    with pytest.raises(scim.SCIMError) as e:
        await scim.delete_user(_S(responder), 7, 5)
    assert e.value.status == 400 and "last active administrator" in e.value.detail.lower()


@pytest.mark.asyncio
async def test_get_user_cross_tenant_404():
    # user not found for this tenant -> 404 (no leak)
    with pytest.raises(scim.SCIMError) as e:
        await scim.get_user_resource(_S(lambda s, p: _R([])), 7, 999, "https://api")
    assert e.value.status == 404
