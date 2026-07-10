"""
Middleware Tests — Validates security headers, rate limiting logic, and request ID generation.
Unit-tests middleware classes without starting the full application.
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.responses import JSONResponse

from app.middleware import (
    RequestIDMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    BodySizeLimitMiddleware,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_request(path: str = "/test", method: str = "GET", content_length: int = 0,
                  headers: dict = None, client_host: str = "127.0.0.1"):
    """Create a minimal mock Request object."""
    request = MagicMock()
    request.url.path = path
    request.method = method
    request.client = MagicMock()
    request.client.host = client_host
    request.headers = {"content-length": str(content_length), **(headers or {})}
    # A real dict, not an auto-MagicMock: cookies.get() on a MagicMock returns a
    # truthy mock, which would fake an authenticated user to the rate limiter.
    request.cookies = {}
    request.state = MagicMock()
    return request


async def _ok_handler(request):
    """Simple handler that always returns 200."""
    return JSONResponse({"ok": True})


# =============================================================================
# RequestIDMiddleware
# =============================================================================

class TestRequestIDMiddleware:

    @pytest.mark.asyncio
    async def test_adds_request_id_header(self):
        app = MagicMock()
        middleware = RequestIDMiddleware(app)
        request = _make_request()

        response = await middleware.dispatch(request, _ok_handler)

        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) == 8  # uuid[:8]

    @pytest.mark.asyncio
    async def test_adds_process_time_header(self):
        app = MagicMock()
        middleware = RequestIDMiddleware(app)
        request = _make_request()

        response = await middleware.dispatch(request, _ok_handler)

        assert "X-Process-Time" in response.headers
        process_time = float(response.headers["X-Process-Time"])
        assert process_time >= 0


# =============================================================================
# RateLimitMiddleware (in-memory fallback path)
# =============================================================================

class TestRateLimitMiddleware:

    @pytest.mark.asyncio
    async def test_allows_requests_within_limit(self):
        app = MagicMock()
        middleware = RateLimitMiddleware(app, requests_limit=10, window_seconds=60)
        request = _make_request()

        # Ensure Redis is unavailable so fallback is used
        with patch("app.middleware.RateLimitMiddleware._check_rate_limit_redis",
                    new_callable=AsyncMock, side_effect=Exception("no redis")):
            response = await middleware.dispatch(request, _ok_handler)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_blocks_after_limit_exceeded(self):
        app = MagicMock()
        middleware = RateLimitMiddleware(app, requests_limit=2, window_seconds=60)
        request = _make_request()

        with patch.object(middleware, "_check_rate_limit_redis",
                          new_callable=AsyncMock, side_effect=Exception("no redis")):
            # Fire 3 requests — third should be blocked
            await middleware.dispatch(request, _ok_handler)
            await middleware.dispatch(request, _ok_handler)
            response = await middleware.dispatch(request, _ok_handler)

        assert response.status_code == 429


# =============================================================================
# RateLimitMiddleware — per-identity scoping (E0-7)
# =============================================================================

def _user_token(user_id: int) -> str:
    """A real signed access token (conftest provides HS256 test secrets)."""
    from app.services.auth_service import create_access_token
    return create_access_token({"user_id": user_id, "tenant_id": 1, "role": "analyst"})


def _no_redis(middleware):
    return patch.object(middleware, "_check_rate_limit_redis",
                        new_callable=AsyncMock, side_effect=Exception("no redis"))


class TestRateLimitIdentityScoping:

    @pytest.mark.asyncio
    async def test_users_get_independent_buckets_behind_one_ip(self):
        """Two authenticated users on the same IP (office NAT) must not share a
        budget — and neither drains the anonymous IP bucket."""
        middleware = RateLimitMiddleware(MagicMock(), requests_limit=2,
                                         window_seconds=60, user_requests_limit=2)
        alice = {"authorization": f"Bearer {_user_token(101)}"}
        bob = {"authorization": f"Bearer {_user_token(202)}"}

        with _no_redis(middleware):
            # Alice exhausts HER bucket (limit 2) — 3rd request 429s.
            await middleware.dispatch(_make_request(headers=alice), _ok_handler)
            await middleware.dispatch(_make_request(headers=alice), _ok_handler)
            alice_third = await middleware.dispatch(_make_request(headers=alice), _ok_handler)
            # Bob, same IP, is untouched.
            bob_first = await middleware.dispatch(_make_request(headers=bob), _ok_handler)
            # Anonymous same-IP is untouched too.
            anon = await middleware.dispatch(_make_request(), _ok_handler)

        assert alice_third.status_code == 429
        assert alice_third.headers["X-RateLimit-Scope"] == "user"
        assert bob_first.status_code == 200
        assert anon.status_code == 200

    @pytest.mark.asyncio
    async def test_ip_rotation_does_not_reset_a_users_budget(self):
        """The old per-IP-only limiter was evadable by IP rotation; the per-user
        bucket follows the verified user_id claim across IPs."""
        middleware = RateLimitMiddleware(MagicMock(), requests_limit=100,
                                         window_seconds=60, user_requests_limit=2)
        hdrs = {"authorization": f"Bearer {_user_token(303)}"}

        with _no_redis(middleware):
            await middleware.dispatch(_make_request(headers=hdrs, client_host="10.0.0.1"), _ok_handler)
            await middleware.dispatch(_make_request(headers=hdrs, client_host="10.0.0.2"), _ok_handler)
            third = await middleware.dispatch(_make_request(headers=hdrs, client_host="10.0.0.3"), _ok_handler)

        assert third.status_code == 429

    @pytest.mark.asyncio
    async def test_api_key_bucket_shared_across_both_transports(self):
        """The same lsk_ key via X-API-Key and via Bearer shares ONE bucket."""
        middleware = RateLimitMiddleware(MagicMock(), requests_limit=100,
                                         window_seconds=60, api_key_requests_limit=2)
        key = "lsk_abc123_secretsecret"

        with _no_redis(middleware):
            await middleware.dispatch(_make_request(headers={"x-api-key": key}), _ok_handler)
            await middleware.dispatch(
                _make_request(headers={"authorization": f"Bearer {key}"}), _ok_handler)
            third = await middleware.dispatch(_make_request(headers={"x-api-key": key}), _ok_handler)

        assert third.status_code == 429
        assert third.headers["X-RateLimit-Scope"] == "key"

    @pytest.mark.asyncio
    async def test_forged_token_cannot_mint_its_own_bucket(self):
        """An unverifiable JWT must NOT become a user identity (that would let an
        attacker forge user_ids for unlimited buckets) — it falls back to the
        anonymous IP bucket."""
        middleware = RateLimitMiddleware(MagicMock(), requests_limit=2,
                                         window_seconds=60, user_requests_limit=100)
        forged = {"authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjo5OTl9.forged"}

        with _no_redis(middleware):
            r1 = await middleware.dispatch(_make_request(headers=forged), _ok_handler)
            await middleware.dispatch(_make_request(headers=forged), _ok_handler)
            third = await middleware.dispatch(_make_request(headers=forged), _ok_handler)

        assert r1.headers["X-RateLimit-Scope"] == "ip"
        assert third.status_code == 429  # the strict anonymous limit applied

    @pytest.mark.asyncio
    async def test_429_reports_the_scopes_own_limit(self):
        middleware = RateLimitMiddleware(MagicMock(), requests_limit=50,
                                         window_seconds=60, user_requests_limit=1)
        hdrs = {"authorization": f"Bearer {_user_token(404)}"}

        with _no_redis(middleware):
            await middleware.dispatch(_make_request(headers=hdrs), _ok_handler)
            blocked = await middleware.dispatch(_make_request(headers=hdrs), _ok_handler)

        assert blocked.status_code == 429
        assert blocked.headers["X-RateLimit-Limit"] == "1"  # the user limit, not the IP one
        assert "Retry-After" in blocked.headers


# =============================================================================
# SecurityHeadersMiddleware
# =============================================================================

class TestSecurityHeadersMiddleware:

    @pytest.mark.asyncio
    async def test_adds_security_headers(self):
        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)
        request = _make_request()

        response = await middleware.dispatch(request, _ok_handler)

        # At minimum these headers should be present
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
