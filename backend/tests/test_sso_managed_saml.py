"""
E5-1b — managed SAML bridge (SAML->OIDC) + native SAML fail-closed. Pure +
fake-session; no network/IdP/secrets. Managed bridge reuses the OIDC flow; native
SAML is never login-usable and does not bypass OIDC security checks.
"""
from types import SimpleNamespace

import pytest

from app.services import sso


def _settings(bridge=False, env="testing"):
    return SimpleNamespace(sso_managed_saml_bridge_enabled=bridge, environment=env,
                           sso_enabled=True, sso_oidc_enabled=True)


# ---------------------------------------------------------------------------
# Type classification
# ---------------------------------------------------------------------------
def test_oidc_compatible_types_depends_on_bridge_flag():
    assert sso.oidc_compatible_types(_settings(bridge=False)) == ["oidc"]
    assert set(sso.oidc_compatible_types(_settings(bridge=True))) == {"oidc", "workos_saml"}
    # native saml is NEVER login-usable
    assert "saml" not in sso.oidc_compatible_types(_settings(bridge=True))


def test_classify_login_provider():
    assert sso.classify_login_provider("oidc", _settings()) == "oidc_ok"
    assert sso.classify_login_provider("workos_saml", _settings(bridge=True)) == "bridge_ok"
    assert sso.classify_login_provider("workos_saml", _settings(bridge=False)) == "bridge_disabled"
    assert sso.classify_login_provider("saml", _settings(bridge=True)) == "native_saml"
    assert sso.classify_login_provider("ldap", _settings()) == "unsupported"


def test_login_type_label_is_honest():
    assert sso.login_type_label("oidc") == "oidc"
    assert sso.login_type_label("workos_saml") == "managed_saml_bridge"
    assert sso.login_type_label("saml") == "native_saml_unsupported"  # never claims native SAML works
    assert sso.is_managed_bridge("workos_saml") is True
    assert sso.is_managed_bridge("oidc") is False


# ---------------------------------------------------------------------------
# Provider lookup honours the bridge flag (fake session captures the type list)
# ---------------------------------------------------------------------------
class _R:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _S:
    def __init__(self):
        self.captured_types = None

    async def execute(self, stmt, params=None):
        if params and "types" in params:
            self.captured_types = params["types"]
        return _R([])

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_get_oidc_provider_includes_bridge_when_enabled(monkeypatch):
    monkeypatch.setattr(sso, "get_settings", lambda: _settings(bridge=True))
    s = _S()
    await sso.get_oidc_provider(s, tenant_id=1)
    assert "workos_saml" in s.captured_types and "oidc" in s.captured_types


@pytest.mark.asyncio
async def test_get_oidc_provider_excludes_bridge_when_disabled(monkeypatch):
    monkeypatch.setattr(sso, "get_settings", lambda: _settings(bridge=False))
    s = _S()
    await sso.get_oidc_provider(s, tenant_id=1)
    assert s.captured_types == ["oidc"]  # bridge + native saml excluded


# ---------------------------------------------------------------------------
# Managed bridge reuses OIDC security (no branch on provider_type)
# ---------------------------------------------------------------------------
BRIDGE = {"provider_type": "workos_saml", "name": "WorkOS", "client_id": "cid",
          "issuer": "https://api.workos.com", "authorization_endpoint": "https://api.workos.com/authorize",
          "scopes": "openid email profile", "trust_idp_mfa": False,
          "allowed_domains": ["contoso.com"]}


def test_bridge_authorization_url_has_state_and_nonce():
    url = sso.build_authorization_url(BRIDGE, "https://app/cb", "ST", "NO")
    assert "state=ST" in url and "nonce=NO" in url and "response_type=code" in url


def test_bridge_does_not_bypass_allowed_domains():
    assert sso.email_domain_allowed("a@evil.com", BRIDGE["allowed_domains"]) is False
    assert sso.email_domain_allowed("a@contoso.com", BRIDGE["allowed_domains"]) is True


def test_bridge_does_not_bypass_email_verification():
    claims = {"iss": BRIDGE["issuer"], "aud": "cid", "sub": "s", "email": "a@contoso.com",
              "email_verified": False, "nonce": "N"}
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(claims, BRIDGE, "N", True)
    assert e.value.code == "email_not_verified"


def test_bridge_does_not_bypass_admin_mfa():
    # an admin via the bridge without local TOTP is still blocked (fail-closed)
    user = {"role": "super_admin", "two_factor_enabled": False}
    assert sso.admin_mfa_block_reason(user, BRIDGE, {"amr": ["mfa"]}, True) == "admin_mfa_required"
