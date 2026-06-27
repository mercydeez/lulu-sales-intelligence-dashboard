"""
Token Hygiene Tests (Phase 1.5) — refresh rotation, remember_me lifetimes,
jti uniqueness, and blacklist behaviour.

These tests run without live Postgres/Redis: DB and Redis interactions are
mocked at the service boundary.
"""
import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response
from jose import jwt

from app.services.auth_service import (
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
    AuthService,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    is_token_blacklisted,
)


def _payload(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


TOKEN_DATA = {"user_id": 1, "email": "atharva@retaildemo.app", "role": "super_admin"}


# =============================================================================
# 1. Token claims
# =============================================================================

class TestTokenClaims:

    def test_access_token_has_type_and_jti(self):
        payload = _payload(create_access_token(TOKEN_DATA))
        assert payload["type"] == "access"
        assert len(payload["jti"]) == 16

    def test_refresh_token_has_type_and_jti(self):
        payload = _payload(create_refresh_token(TOKEN_DATA))
        assert payload["type"] == "refresh"
        assert len(payload["jti"]) == 16

    def test_jti_makes_tokens_unique(self):
        assert create_access_token(TOKEN_DATA) != create_access_token(TOKEN_DATA)
        assert create_refresh_token(TOKEN_DATA) != create_refresh_token(TOKEN_DATA)

    def test_exp_is_utc_aware(self):
        data = decode_token(create_access_token(TOKEN_DATA))
        assert data.exp.tzinfo is not None
        assert data.exp > datetime.now(timezone.utc)


# =============================================================================
# 2. remember_me lifetimes
# =============================================================================

class TestRememberMe:

    def _expiry_days(self, token: str) -> float:
        exp = datetime.fromtimestamp(_payload(token)["exp"], tz=timezone.utc)
        return (exp - datetime.now(timezone.utc)).total_seconds() / 86400

    def test_default_refresh_lifetime(self):
        days = self._expiry_days(create_refresh_token(TOKEN_DATA))
        assert abs(days - REFRESH_TOKEN_EXPIRE_DAYS) < 0.1

    def test_remember_me_extends_refresh_lifetime(self):
        days = self._expiry_days(create_refresh_token(TOKEN_DATA, remember_me=True))
        assert abs(days - REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS) < 0.1

    def test_remember_me_claim_recorded(self):
        assert _payload(create_refresh_token(TOKEN_DATA, remember_me=True))["remember_me"] is True
        assert _payload(create_refresh_token(TOKEN_DATA))["remember_me"] is False

    @pytest.mark.asyncio
    async def test_remember_me_does_not_extend_access_token(self):
        tokens = await AuthService.create_tokens(
            {"id": 1, "email": "a@b.c", "role": "analyst"}, remember_me=True
        )
        days = self._expiry_days(tokens.access_token)
        assert days < 0.05  # still ~30 minutes


# =============================================================================
# 3. Blacklist helpers (mocked Redis)
# =============================================================================

class TestBlacklist:

    @pytest.mark.asyncio
    async def test_blacklist_roundtrip(self):
        store = {}
        fake = AsyncMock()
        fake.set = AsyncMock(side_effect=lambda k, v, ex=None: store.__setitem__(k, v))
        fake.get = AsyncMock(side_effect=lambda k: store.get(k))
        with patch("app.services.redis_client.redis_client", fake):
            token = create_refresh_token(TOKEN_DATA)
            assert await is_token_blacklisted(token) is False
            await blacklist_token(token, 60)
            assert await is_token_blacklisted(token) is True

    @pytest.mark.asyncio
    async def test_fails_closed_when_redis_down(self):
        # Secure default: if the blacklist can't be consulted, treat the token as
        # revoked (return True) so a logged-out / rotated token isn't honored.
        broken = AsyncMock()
        broken.get = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("app.services.redis_client.redis_client", broken):
            assert await is_token_blacklisted("any-token") is True


# =============================================================================
# 4. Refresh rotation
# =============================================================================

@pytest.mark.asyncio
class TestRefreshRotation:

    def _fake_redis(self, store: dict) -> AsyncMock:
        fake = AsyncMock()
        fake.set = AsyncMock(side_effect=lambda k, v, ex=None: store.__setitem__(k, v))
        fake.get = AsyncMock(side_effect=lambda k: store.get(k))
        return fake

    def _patch_db(self):
        """Patch the user lookup + permissions so no live Postgres is needed."""
        user_row = AsyncMock()
        row = type("Row", (), {})()
        row._mapping = {
            "id": 1, "email": "a@b.c", "first_name": "A", "last_name": "B",
            "role": "analyst", "status": "active", "job_title": None, "department": None,
        }
        user_row.fetchone = lambda: row

        session = AsyncMock()
        session.execute = AsyncMock(return_value=user_row)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        return (
            patch("app.services.auth_service.async_session", return_value=session),
            patch.object(AuthService, "_get_user_permissions", AsyncMock(return_value={})),
        )

    async def test_rotation_blacklists_used_token_and_rejects_replay(self):
        store = {}
        db_patch, perm_patch = self._patch_db()
        with patch("app.services.redis_client.redis_client", self._fake_redis(store)), \
             db_patch, perm_patch:
            old_refresh = create_refresh_token(TOKEN_DATA)

            first = await AuthService.refresh_access_token(old_refresh)
            assert first is not None
            assert first.refresh_token != old_refresh

            # Replaying the rotated token must be rejected
            replay = await AuthService.refresh_access_token(old_refresh)
            assert replay is None

    async def test_rotation_preserves_remember_me(self):
        store = {}
        db_patch, perm_patch = self._patch_db()
        with patch("app.services.redis_client.redis_client", self._fake_redis(store)), \
             db_patch, perm_patch:
            long_refresh = create_refresh_token(TOKEN_DATA, remember_me=True)
            tokens = await AuthService.refresh_access_token(long_refresh)
            assert _payload(tokens.refresh_token)["remember_me"] is True

    async def test_access_token_rejected_as_refresh(self):
        access = create_access_token(TOKEN_DATA)
        assert await AuthService.refresh_access_token(access) is None


# =============================================================================
# 5. Token-type confusion (P0 fix) — decode_token pins the `type` claim so a
#    long-lived refresh token cannot be replayed as a Bearer access token.
# =============================================================================

class TestTokenTypeConfusion:

    def test_access_token_accepted_on_access_path(self):
        # Default expected_type="access" accepts a real access token.
        assert decode_token(create_access_token(TOKEN_DATA)) is not None

    def test_refresh_token_rejected_on_access_path(self):
        # The core fix: a refresh token must NOT validate as an access token.
        assert decode_token(create_refresh_token(TOKEN_DATA)) is None

    def test_refresh_token_accepted_when_expected(self):
        assert decode_token(
            create_refresh_token(TOKEN_DATA), expected_type="refresh"
        ) is not None

    def test_type_check_can_be_skipped(self):
        # expected_type=None preserves the legacy "any valid JWT" behaviour.
        assert decode_token(create_refresh_token(TOKEN_DATA), expected_type=None) is not None


# =============================================================================
# 6. httpOnly cookie auth (P1.3) — the cookie helpers set/clear secure auth
#    cookies. Tokens are returned in the body (Bearer) AND set as httpOnly
#    cookies so the browser need not keep them in XSS-exfiltratable localStorage.
# =============================================================================

def _set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


class TestCookieAuth:

    def _tokens(self):
        return SimpleNamespace(
            access_token="acc.jwt.value",
            refresh_token="ref.jwt.value",
            expires_in=1800,
        )

    def test_set_auth_cookies_sets_both_httponly(self):
        from app.routes.auth import set_auth_cookies, ACCESS_COOKIE, REFRESH_COOKIE
        resp = Response()
        set_auth_cookies(resp, self._tokens())
        headers = _set_cookie_headers(resp)
        joined = "\n".join(headers)
        assert f"{ACCESS_COOKIE}=acc.jwt.value" in joined
        assert f"{REFRESH_COOKIE}=ref.jwt.value" in joined
        # Both cookies must be httpOnly + scoped to the whole site.
        assert all("HttpOnly" in h for h in headers)
        assert all("Path=/" in h for h in headers)

    def test_dev_cookies_not_secure(self):
        # Testing/dev env: allow http on localhost (no Secure flag).
        from app.routes.auth import set_auth_cookies
        resp = Response()
        set_auth_cookies(resp, self._tokens())
        assert all("Secure" not in h for h in _set_cookie_headers(resp))

    def test_prod_cookies_are_secure(self, production_settings):
        from app.routes import auth as auth_routes
        resp = Response()
        with patch.object(auth_routes, "get_settings", return_value=production_settings):
            auth_routes.set_auth_cookies(resp, self._tokens())
        assert all("Secure" in h for h in _set_cookie_headers(resp))

    def test_clear_auth_cookies_expires_both(self):
        from app.routes.auth import clear_auth_cookies, ACCESS_COOKIE, REFRESH_COOKIE
        resp = Response()
        clear_auth_cookies(resp)
        joined = "\n".join(_set_cookie_headers(resp))
        # delete_cookie emits an expiry in the past for each cookie.
        assert ACCESS_COOKIE in joined and REFRESH_COOKIE in joined
        assert "Max-Age=0" in joined or "01 Jan 1970" in joined
