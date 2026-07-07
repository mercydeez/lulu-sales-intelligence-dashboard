"""
E5-1b — SSO provider operations: validation + tenant-admin provider management.
Pure + fake-session; no DB/network/IdP/secrets.
"""
from types import SimpleNamespace

import pytest

from app.services import sso
from app.routes import sso as sso_routes


def _settings(**over):
    base = dict(environment="testing", sso_managed_saml_bridge_enabled=False,
                sso_enabled=True, sso_oidc_enabled=True, sso_live_provider_validation_enabled=False,
                sso_admin_config_enabled=True)
    base.update(over)
    return SimpleNamespace(**base)


VALID_OIDC = {
    "provider_type": "oidc", "name": "Azure AD",
    "issuer": "https://login.microsoftonline.com/tid/v2.0",
    "authorization_endpoint": "https://login.microsoftonline.com/tid/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/tid/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/tid/discovery/v2.0/keys",
    "client_id": "abc", "client_secret_env": "SSO_AZURE_CLIENT_SECRET",
    "scopes": "openid email profile", "allowed_domains": ["contoso.com"],
    "jit_provisioning_enabled": True, "default_role": "analyst", "trust_idp_mfa": False,
}


# ---------------------------------------------------------------------------
# Env-var-name / secret heuristics
# ---------------------------------------------------------------------------
def test_env_var_name_and_secret_detection():
    assert sso.is_env_var_name("SSO_AZURE_CLIENT_SECRET") is True
    assert sso.is_env_var_name("not an env name") is False
    assert sso.looks_like_secret_value("https://evil/secret") is True         # URL
    assert sso.looks_like_secret_value("eyJhbGc.eyJzdWI.sig12345") is True    # JWT-ish
    assert sso.looks_like_secret_value("A1b2C3d4E5f6G7h8I9j0K1L2m3n4") is True  # long token
    assert sso.looks_like_secret_value("SSO_AZURE_CLIENT_SECRET") is False    # env name


# ---------------------------------------------------------------------------
# validate_provider_configuration
# ---------------------------------------------------------------------------
def test_valid_oidc_passes():
    d = sso.validate_provider_configuration(VALID_OIDC, _settings())
    assert d["ok"] is True and d["errors"] == []


@pytest.mark.parametrize("field", ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri", "client_id", "name"])
def test_missing_required_field_fails(field):
    p = {**VALID_OIDC, field: None}
    d = sso.validate_provider_configuration(p, _settings())
    assert d["ok"] is False and any(field in e for e in d["errors"])


def test_invalid_allowed_domains_fails():
    d = sso.validate_provider_configuration({**VALID_OIDC, "allowed_domains": "contoso.com"}, _settings())
    assert "allowed_domains_not_list" in d["errors"]


def test_scopes_missing_openid_fails():
    d = sso.validate_provider_configuration({**VALID_OIDC, "scopes": "email profile"}, _settings())
    assert "scopes_missing_openid" in d["errors"]


def test_http_issuer_rejected_in_production():
    p = {**VALID_OIDC, "issuer": "http://login.example/tid"}
    d = sso.validate_provider_configuration(p, _settings(environment="production"))
    assert any("insecure_url:issuer" == e for e in d["errors"])


def test_localhost_http_allowed_in_dev_as_warning():
    p = {**VALID_OIDC, "issuer": "http://localhost:9000/tid",
         "authorization_endpoint": "http://localhost:9000/auth",
         "token_endpoint": "http://localhost:9000/token", "jwks_uri": "http://localhost:9000/jwks"}
    d = sso.validate_provider_configuration(p, _settings(environment="development"))
    assert not any(e.startswith("insecure_url") for e in d["errors"])


def test_secret_value_in_client_secret_env_rejected():
    d = sso.validate_provider_configuration({**VALID_OIDC, "client_secret_env": "https://a/very-real-secret-value"}, _settings())
    assert "client_secret_env_must_be_env_name" in d["errors"]


def test_privileged_default_role_rejected():
    d = sso.validate_provider_configuration({**VALID_OIDC, "default_role": "super_admin"}, _settings())
    assert "privileged_default_role" in d["errors"]


def test_jit_requires_domains():
    d = sso.validate_provider_configuration({**VALID_OIDC, "allowed_domains": []}, _settings())
    assert "jit_requires_allowed_domains" in d["errors"]


def test_native_saml_validation_fails_closed():
    d = sso.validate_provider_configuration({**VALID_OIDC, "provider_type": "saml"}, _settings())
    assert "native_saml_not_implemented" in d["errors"] and d["ok"] is False


def test_diagnostics_have_no_secret_values():
    d = sso.validate_provider_configuration(VALID_OIDC, _settings())
    blob = str(d)
    # the env var NAME may appear in checks, but never a secret VALUE
    assert "BEGIN PRIVATE KEY" not in blob and "://a/" not in blob


def test_live_missing_secret_env(monkeypatch):
    monkeypatch.delenv("SSO_AZURE_CLIENT_SECRET", raising=False)
    d = sso.validate_provider_configuration(VALID_OIDC, _settings(), live=True)
    assert "secret_env_missing" in d["errors"]


# ---------------------------------------------------------------------------
# Fake session + admin service
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


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(sso, "get_settings", lambda: _settings())


def _created_row(**over):
    row = {"id": 10, "tenant_id": 3, "provider_type": "oidc", "name": "Azure AD", "enabled": False,
           "issuer": VALID_OIDC["issuer"], "client_id": "abc", "scopes": "openid email profile",
           "allowed_domains": ["contoso.com"], "jit_provisioning_enabled": True,
           "default_role": "analyst", "trust_idp_mfa": False,
           "client_secret_env": "SSO_AZURE_CLIENT_SECRET", "metadata": {"status": "draft"}}
    row.update(over)
    return row


@pytest.mark.asyncio
async def test_admin_create_oidc_draft_disabled():
    captured = {}

    def responder(sql, p):
        if "SELECT id FROM tenant_sso_providers WHERE tenant_id" in sql:
            return _R([])  # no dup
        if "INSERT INTO tenant_sso_providers" in sql:
            captured.update(p)
            return _R([{"id": 10}])
        if "SELECT * FROM tenant_sso_providers WHERE id" in sql:
            return _R([_created_row()])
        return _R()
    view = await sso.admin_create_provider(_S(responder), 3, {**VALID_OIDC}, created_by=9)
    assert view["enabled"] is False and view["status"] == "draft"
    assert view["client_secret_env_configured"] is True
    assert "client_secret_env" not in view  # value/name never returned


@pytest.mark.asyncio
async def test_admin_create_native_saml_rejected():
    with pytest.raises(sso.SsoError) as e:
        await sso.admin_create_provider(_S(lambda s, p: _R()), 3, {**VALID_OIDC, "provider_type": "saml"}, 9)
    assert e.value.status == 400 and "saml" in e.value.code.lower()


@pytest.mark.asyncio
async def test_admin_create_duplicate_name_conflict():
    def responder(sql, p):
        if "SELECT id FROM tenant_sso_providers WHERE tenant_id" in sql:
            return _R([{"id": 1}])
        return _R()
    with pytest.raises(sso.SsoError) as e:
        await sso.admin_create_provider(_S(responder), 3, {**VALID_OIDC}, 9)
    assert e.value.status == 409


@pytest.mark.asyncio
async def test_admin_create_privileged_role_rejected():
    def responder(sql, p):
        if "SELECT id FROM tenant_sso_providers WHERE tenant_id" in sql:
            return _R([])
        return _R()
    with pytest.raises(sso.SsoError) as e:
        await sso.admin_create_provider(_S(responder), 3, {**VALID_OIDC, "default_role": "super_admin"}, 9)
    assert e.value.status == 400


@pytest.mark.asyncio
async def test_admin_create_invalid_config_rejected():
    def responder(sql, p):
        if "SELECT id FROM tenant_sso_providers WHERE tenant_id" in sql:
            return _R([])
        return _R()
    with pytest.raises(sso.SsoError) as e:
        await sso.admin_create_provider(_S(responder), 3, {**VALID_OIDC, "issuer": None}, 9)
    assert e.value.status == 400


@pytest.mark.asyncio
async def test_admin_enable_invalid_provider_blocked():
    # provider exists but config is invalid (no client_id) -> cannot enable
    def responder(sql, p):
        if "SELECT * FROM tenant_sso_providers WHERE id" in sql:
            return _R([_created_row(client_id=None)])
        return _R()
    with pytest.raises(sso.SsoError) as e:
        await sso.admin_enable_provider(_S(responder), 3, 10)
    assert e.value.status == 400


@pytest.mark.asyncio
async def test_admin_get_cross_tenant_returns_none():
    got = await sso.admin_get_provider(_S(lambda s, p: _R([])), 3, 999)
    assert got is None


def test_admin_provider_view_hides_secret_env():
    v = sso.admin_provider_view(_created_row())
    assert "client_secret_env" not in v and v["client_secret_env_configured"] is True
    assert v["status"] == "draft" and v["login_type"] == "oidc"


def test_admin_routes_are_role_guarded():
    admin_routes = [r for r in sso_routes.router.routes
                    if getattr(r, "path", "").startswith("/admin/providers")]
    assert admin_routes
    for route in admin_routes:
        deps = getattr(route.dependant, "dependencies", [])
        assert any("require_role" in getattr(d.call, "__qualname__", "") for d in deps), route.path
