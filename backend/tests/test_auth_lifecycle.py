"""
Phase 5 — auth lifecycle hardening.

Single-use reset/verify/invite tokens, session-revocation epoch, and admin-MFA
enforcement. Service boundaries (DB/Redis) are mocked so these run without live
Postgres/Redis; the atomic single-use SQL itself is exercised by the in-container
integration suite.
"""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import AsyncClient, ASGITransport

from app.config import Settings


async def _client_post(path, json):
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(path, json=json)


def _settings(**kw):
    base = dict(environment="testing",
                jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                secret_key="test-app-secret-key-minimum-32-chars-for-testing")
    base.update(kw)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Admin MFA enforcement
# ---------------------------------------------------------------------------
class TestAdminMfaEnforcement:
    async def test_admin_without_2fa_blocked_when_required(self):
        admin = {"id": 1, "email": "a@x.io", "role": "super_admin", "two_factor_enabled": False}
        with patch("app.routes.auth.AuthService.authenticate_user",
                   new=AsyncMock(return_value=(admin, None))), \
             patch("app.routes.auth.get_settings", return_value=_settings(require_mfa_for_admins=True)), \
             patch("app.services.security_events.record_event", new=AsyncMock()):
            resp = await _client_post("/api/auth/login",
                                      {"email": "a@x.io", "password": "x", "remember_me": False})
        assert resp.status_code == 403
        assert "two-factor" in resp.json()["message"].lower()

    async def test_non_admin_not_blocked(self):
        user = {"id": 2, "email": "u@x.io", "role": "analyst", "two_factor_enabled": False,
                "tenant_id": 1}
        tokens = SimpleNamespace(access_token="a", refresh_token="r", token_type="bearer",
                                 expires_in=1800, user=user)
        with patch("app.routes.auth.AuthService.authenticate_user",
                   new=AsyncMock(return_value=(user, None))), \
             patch("app.routes.auth.AuthService.create_tokens", new=AsyncMock(return_value=tokens)), \
             patch("app.routes.auth.get_settings", return_value=_settings(require_mfa_for_admins=True)):
            resp = await _client_post("/api/auth/login",
                                      {"email": "u@x.io", "password": "x", "remember_me": False})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Single-use reset
# ---------------------------------------------------------------------------
class TestResetSingleUse:
    async def test_replayed_or_used_token_rejected(self):
        with patch("app.services.auth_service.decode_password_reset_token", return_value=7), \
             patch("app.services.token_store.consume_token", new=AsyncMock(return_value=None)):
            resp = await _client_post("/api/auth/reset-password",
                                      {"token": "t", "new_password": "Str0ngPass!9"})
        assert resp.status_code == 400
        assert "already been used" in resp.json()["message"].lower() or \
               "already been used" in resp.json()["message"]

    async def test_valid_reset_revokes_sessions(self):
        with patch("app.services.auth_service.decode_password_reset_token", return_value=7), \
             patch("app.services.token_store.consume_token",
                   new=AsyncMock(return_value={"user_id": 7})), \
             patch("app.routes.auth.AuthService.reset_password",
                   new=AsyncMock(return_value=(True, "Password updated"))), \
             patch("app.services.auth_service.revoke_user_sessions", new=AsyncMock()) as revoke, \
             patch("app.services.security_events.record_event", new=AsyncMock()):
            resp = await _client_post("/api/auth/reset-password",
                                      {"token": "t", "new_password": "Str0ngPass!9"})
        assert resp.status_code == 200
        revoke.assert_awaited_once_with(7)


# ---------------------------------------------------------------------------
# Single-use email verification
# ---------------------------------------------------------------------------
class TestVerifySingleUse:
    async def test_replayed_verify_rejected(self):
        with patch("app.services.auth_service.decode_email_verify_token", return_value=7), \
             patch("app.services.token_store.consume_token", new=AsyncMock(return_value=None)):
            resp = await _client_post("/api/auth/verify-email", {"token": "t"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Invite accept
# ---------------------------------------------------------------------------
class _FakeSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def execute(self, *a, **k): return MagicMock()
    async def commit(self): return None


class TestAcceptInvite:
    async def test_invalid_invite_rejected(self):
        with patch("app.services.token_store.consume_token", new=AsyncMock(return_value=None)):
            resp = await _client_post("/api/auth/accept-invite",
                                      {"token": "bad", "new_password": "Str0ngPass!9"})
        assert resp.status_code == 400

    async def test_valid_invite_accepted(self):
        with patch("app.services.token_store.consume_token",
                   new=AsyncMock(return_value={"user_id": 9, "tenant_id": 1, "email": "n@x.io"})), \
             patch("app.routes.auth.AuthService.reset_password",
                   new=AsyncMock(return_value=(True, "ok"))), \
             patch("app.services.database.async_session", new=lambda: _FakeSession()), \
             patch("app.services.security_events.record_event", new=AsyncMock()):
            resp = await _client_post("/api/auth/accept-invite",
                                      {"token": "good", "new_password": "Str0ngPass!9"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# No account enumeration
# ---------------------------------------------------------------------------
class TestNoEnumeration:
    async def test_forgot_password_same_message_both_ways(self):
        # Unknown email
        with patch("app.routes.auth.AuthService.get_user_id_by_email", new=AsyncMock(return_value=None)):
            r1 = await _client_post("/api/auth/forgot-password", {"email": "missing@x.io"})
        # Known email — issue + email mocked away
        with patch("app.routes.auth.AuthService.get_user_id_by_email", new=AsyncMock(return_value=7)), \
             patch("app.services.token_store.issue_token", new=AsyncMock()), \
             patch("app.services.security_notify.send_email", new=AsyncMock()), \
             patch("app.services.security_events.record_event", new=AsyncMock()):
            r2 = await _client_post("/api/auth/forgot-password", {"email": "real@x.io"})
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["message"] == r2.json()["message"]


# ---------------------------------------------------------------------------
# Session revocation epoch
# ---------------------------------------------------------------------------
class TestSessionEpoch:
    async def test_token_issued_before_cutoff_is_rejected(self):
        from app.routes.auth import get_current_user
        from app.services.auth_service import create_access_token
        token = create_access_token({"user_id": 7, "email": "a@x.io", "role": "analyst"})
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=5)  # after iat
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch("app.services.auth_service.tokens_revoked_before",
                   new=AsyncMock(return_value=cutoff)), \
             patch("app.services.security_events.record_event", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=MagicMock(cookies={}), credentials=creds)
        assert exc.value.status_code == 401
        assert "revoked" in exc.value.detail.lower()

    async def test_token_passes_when_no_cutoff(self):
        from app.routes.auth import get_current_user
        from app.services.auth_service import create_access_token
        token = create_access_token({"user_id": 7, "email": "a@x.io", "role": "analyst"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = {"id": 7, "email": "a@x.io", "role": "analyst", "status": "active", "tenant_id": None}
        with patch("app.services.auth_service.tokens_revoked_before", new=AsyncMock(return_value=None)), \
             patch("app.routes.auth.AuthService.get_user_by_id", new=AsyncMock(return_value=user)):
            result = await get_current_user(request=MagicMock(cookies={}), credentials=creds)
        assert result["id"] == 7
