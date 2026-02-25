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

def _make_request(path: str = "/test", method: str = "GET", content_length: int = 0):
    """Create a minimal mock Request object."""
    request = MagicMock()
    request.url.path = path
    request.method = method
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"content-length": str(content_length)}
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
