"""
E5-1a — OIDC SSO foundation. Pure + fake-session tests; NO Docker/Postgres/Redis/
Azure/network/secrets. Covers the security-critical decisions (auth URL, state
single-use, ID-token claim validation, JIT/link rules, admin-MFA fail-closed).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import sso


PROVIDER = {
    "id": 7, "tenant_id": 3, "name": "Azure AD", "provider_type": "oidc", "enabled": True,
    "issuer": "https://login.microsoftonline.com/tid/v2.0",
    "authorization_endpoint": "https://login.microsoftonline.com/tid/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/tid/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/tid/discovery/v2.0/keys",
    "client_id": "client-abc", "client_secret_env": "SSO_AZURE_SECRET",
    "scopes": "openid email profile", "allowed_domains": ["contoso.com"],
    "jit_provisioning_enabled": True, "default_role": "analyst", "trust_idp_mfa": False,
}


# ---------------------------------------------------------------------------
# Authorization URL + return_to
# ---------------------------------------------------------------------------
def test_authorization_url_includes_state_nonce_no_secret():
    url = sso.build_authorization_url(PROVIDER, "https://app/cb", "STATE123", "NONCE456")
    assert url.startswith(PROVIDER["authorization_endpoint"] + "?")
    assert "state=STATE123" in url and "nonce=NONCE456" in url
    assert "response_type=code" in url and "client_id=client-abc" in url
    assert "scope=openid" in url
    # never leaks the secret env name or a secret
    assert "SSO_AZURE_SECRET" not in url and "client_secret" not in url


def test_return_to_validation():
    assert sso.validate_return_to("/dashboard", "", 500) is True          # same-origin path
    assert sso.validate_return_to(None, "", 500) is True                  # optional
    assert sso.validate_return_to("//evil.com", "", 500) is False         # protocol-relative
    assert sso.validate_return_to("https://evil.com/x", "app.example.com", 500) is False
    assert sso.validate_return_to("https://app.example.com/x", "app.example.com", 500) is True
    assert sso.validate_return_to("/" + "a" * 600, "", 500) is False      # too long


def test_pkce_pair_is_s256_shaped():
    v, c = sso.pkce_pair()
    assert v and c and v != c and "=" not in c  # base64url, no padding


# ---------------------------------------------------------------------------
# ID token claim validation
# ---------------------------------------------------------------------------
def _claims(**over):
    base = {
        "iss": PROVIDER["issuer"], "aud": PROVIDER["client_id"], "sub": "sub-1",
        "email": "u@contoso.com", "email_verified": True, "nonce": "N",
    }
    base.update(over)
    return base


def test_valid_claims_pass():
    sso.validate_id_claims(_claims(), PROVIDER, "N", True)  # no raise


def test_wrong_issuer_rejected():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(iss="https://evil/"), PROVIDER, "N", True)
    assert e.value.code == "invalid_issuer"


def test_wrong_audience_rejected():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(aud="someone-else"), PROVIDER, "N", True)
    assert e.value.code == "invalid_audience"


def test_missing_subject_rejected():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(sub=None), PROVIDER, "N", True)
    assert e.value.code == "missing_subject"


def test_missing_email_rejected():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(email=None), PROVIDER, "N", True)
    assert e.value.code == "missing_email"


def test_unverified_email_rejected_when_required():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(email_verified=False), PROVIDER, "N", True)
    assert e.value.code == "email_not_verified"
    # ...but accepted when not required
    sso.validate_id_claims(_claims(email_verified=False), PROVIDER, "N", False)


def test_nonce_mismatch_rejected():
    with pytest.raises(sso.SsoError) as e:
        sso.validate_id_claims(_claims(nonce="other"), PROVIDER, "N", True)
    assert e.value.code == "nonce_mismatch"


def test_audience_list_accepted():
    sso.validate_id_claims(_claims(aud=["x", PROVIDER["client_id"]]), PROVIDER, "N", True)


# ---------------------------------------------------------------------------
# JIT role clamp + domain + MFA signal
# ---------------------------------------------------------------------------
def test_jit_role_never_admin():
    for bad in ("super_admin", "admin", "owner", "SUPER_ADMIN", "root", None, "garbage"):
        assert sso.clamp_jit_role(bad) == "analyst"
    assert sso.clamp_jit_role("store_manager") == "store_manager"
    assert sso.clamp_jit_role("regional_manager") == "regional_manager"


def test_email_domain_allowed():
    assert sso.email_domain_allowed("a@contoso.com", ["contoso.com"]) is True
    assert sso.email_domain_allowed("a@evil.com", ["contoso.com"]) is False
    assert sso.email_domain_allowed("a@evil.com", []) is True  # no restriction
    assert sso.email_domain_allowed("bad-email", ["contoso.com"]) is False


def test_extract_mfa_signal():
    assert sso.extract_mfa_signal({"amr": ["pwd", "mfa"]}) is True
    assert sso.extract_mfa_signal({"amr": "otp"}) is True
    assert sso.extract_mfa_signal({"acr": "http://schemas.microsoft.com/claims/multipleauthn"}) is True
    assert sso.extract_mfa_signal({"amr": ["pwd"]}) is False
    assert sso.extract_mfa_signal({}) is False


# ---------------------------------------------------------------------------
# Admin MFA fail-closed policy (the core "SSO can't bypass admin MFA")
# ---------------------------------------------------------------------------
def test_admin_without_local_mfa_is_blocked():
    user = {"role": "super_admin", "two_factor_enabled": False}
    assert sso.admin_mfa_block_reason(user, PROVIDER, {}, True) == "admin_mfa_required"


def test_admin_with_local_mfa_allowed():
    user = {"role": "super_admin", "two_factor_enabled": True}
    assert sso.admin_mfa_block_reason(user, PROVIDER, {}, True) is None


def test_non_admin_never_requires_local_mfa():
    user = {"role": "analyst", "two_factor_enabled": False}
    assert sso.admin_mfa_block_reason(user, PROVIDER, {"amr": ["pwd"]}, True) is None


def test_idp_mfa_claim_does_not_bypass_unless_provider_trusts_it():
    user = {"role": "owner", "two_factor_enabled": False}
    claims = {"amr": ["mfa"]}
    # provider does NOT trust IdP MFA -> still blocked
    assert sso.admin_mfa_block_reason(user, PROVIDER, claims, True) == "admin_mfa_required"
    # provider trusts IdP MFA + strong signal -> allowed
    trusting = {**PROVIDER, "trust_idp_mfa": True}
    assert sso.admin_mfa_block_reason(user, trusting, claims, True) is None
    # trusts IdP MFA but NO strong signal -> still blocked
    assert sso.admin_mfa_block_reason(user, trusting, {"amr": ["pwd"]}, True) == "admin_mfa_required"


def test_mfa_policy_off_never_blocks():
    user = {"role": "super_admin", "two_factor_enabled": False}
    assert sso.admin_mfa_block_reason(user, PROVIDER, {}, False) is None


def test_public_provider_view_hides_secret_env():
    v = sso.public_provider_view(PROVIDER)
    assert "client_secret_env" not in v
    assert v["name"] == "Azure AD" and v["provider_type"] == "oidc"
    admin_v = sso.public_provider_view(PROVIDER, include_admin_fields=True)
    assert admin_v["client_secret_env"] == "SSO_AZURE_SECRET"


# ---------------------------------------------------------------------------
# State single-use / expiry (fake session)
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
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
async def test_state_unknown_rejected():
    sess = _FakeSession(lambda sql, p: _FakeResult(rows=[]))
    with pytest.raises(sso.SsoError) as e:
        await sso.consume_auth_state(sess, "nope")
    assert e.value.code == "state_unknown"


@pytest.mark.asyncio
async def test_state_expired_rejected():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    row = {"state_hash": "h", "nonce_hash": "n", "consumed_at": None, "expires_at": past,
           "provider_id": 7, "tenant_id": 3, "redirect_uri": "https://app/cb"}
    sess = _FakeSession(lambda sql, p: _FakeResult(rows=[row]))
    with pytest.raises(sso.SsoError) as e:
        await sso.consume_auth_state(sess, "x")
    assert e.value.code == "state_expired"


@pytest.mark.asyncio
async def test_state_replay_rejected():
    row = {"state_hash": "h", "nonce_hash": "n", "consumed_at": datetime.now(timezone.utc),
           "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
           "provider_id": 7, "tenant_id": 3, "redirect_uri": "https://app/cb"}
    sess = _FakeSession(lambda sql, p: _FakeResult(rows=[row]))
    with pytest.raises(sso.SsoError) as e:
        await sso.consume_auth_state(sess, "x")
    assert e.value.code == "state_replayed"


@pytest.mark.asyncio
async def test_state_single_use_success_then_marks_consumed():
    row = {"state_hash": "h", "nonce_hash": "n", "consumed_at": None,
           "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
           "provider_id": 7, "tenant_id": 3, "redirect_uri": "https://app/cb"}

    def responder(sql, p):
        if sql.strip().upper().startswith("UPDATE"):
            return _FakeResult(rowcount=1)  # first consume wins
        return _FakeResult(rows=[row])
    out = await sso.consume_auth_state(_FakeSession(responder), "x")
    assert out["provider_id"] == 7


# ---------------------------------------------------------------------------
# JIT / linking branch decisions (fake session + patched user loader)
# ---------------------------------------------------------------------------
@pytest.fixture
def patch_load_user(monkeypatch):
    async def fake_load(session, user_id):
        return {"id": user_id, "email": "u@contoso.com", "role": "analyst",
                "tenant_id": 3, "two_factor_enabled": False, "permissions": {}}
    monkeypatch.setattr(sso, "_load_user_data", fake_load)


@pytest.mark.asyncio
async def test_existing_identity_returns_existing(patch_load_user):
    def responder(sql, p):
        if "FROM external_identities WHERE provider_id" in sql:
            return _FakeResult(rows=[{"user_id": 99}])
        return _FakeResult(rows=[])
    ud, action = await sso.resolve_or_provision_user(_FakeSession(responder), PROVIDER,
                                                     _claims(sub="s", email="u@contoso.com"))
    assert action == "existing" and ud["id"] == 99


@pytest.mark.asyncio
async def test_links_existing_user_same_tenant(patch_load_user):
    def responder(sql, p):
        if "FROM external_identities WHERE provider_id" in sql:
            return _FakeResult(rows=[])
        if "FROM users WHERE tenant_id" in sql:
            return _FakeResult(rows=[{"id": 55}])
        return _FakeResult(rows=[])
    ud, action = await sso.resolve_or_provision_user(_FakeSession(responder), PROVIDER,
                                                     _claims(email="u@contoso.com"))
    assert action == "linked" and ud["id"] == 55


@pytest.mark.asyncio
async def test_jit_creates_analyst_only(patch_load_user):
    captured = {}

    def responder(sql, p):
        if "FROM external_identities WHERE provider_id" in sql:
            return _FakeResult(rows=[])
        if "FROM users WHERE tenant_id" in sql:
            return _FakeResult(rows=[])
        if "INSERT INTO users" in sql:
            captured["role"] = p.get("role")
            return _FakeResult(rows=[{"id": 123}])
        return _FakeResult(rows=[])
    # provider tries to default to super_admin -> must be clamped to analyst
    prov = {**PROVIDER, "default_role": "super_admin"}
    ud, action = await sso.resolve_or_provision_user(_FakeSession(responder), prov,
                                                     _claims(email="new@contoso.com"))
    assert action == "jit"
    assert captured["role"] == "analyst"  # never admin


@pytest.mark.asyncio
async def test_jit_disabled_rejects_unknown_user(patch_load_user):
    def responder(sql, p):
        return _FakeResult(rows=[])  # no identity, no user
    prov = {**PROVIDER, "jit_provisioning_enabled": False}
    with pytest.raises(sso.SsoError) as e:
        await sso.resolve_or_provision_user(_FakeSession(responder), prov,
                                            _claims(email="new@contoso.com"))
    assert e.value.code == "user_not_provisioned"


@pytest.mark.asyncio
async def test_domain_mismatch_rejected(patch_load_user):
    def responder(sql, p):
        return _FakeResult(rows=[])  # no identity
    with pytest.raises(sso.SsoError) as e:
        await sso.resolve_or_provision_user(_FakeSession(responder), PROVIDER,
                                            _claims(email="attacker@evil.com"))
    assert e.value.code == "domain_not_allowed"
