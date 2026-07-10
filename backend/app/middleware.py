"""
Middleware components for the Sales Dashboard API.
Security hardened with Redis-based rate limiting, CSRF protection,
body size limits, and comprehensive security headers.
"""
import time
import uuid
import secrets
import hashlib
from collections import defaultdict
from typing import Callable, Dict
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings, logger, request_id_ctx


settings = get_settings()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Lightweight middleware for request ID tracking.
    Optimized: Minimal logging to reduce latency.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Reuse an inbound request id (from an upstream proxy/service) for
        # end-to-end tracing, otherwise mint a new one.
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming and len(incoming) <= 64 else str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        # Publish to the contextvar so the logging filter stamps every log line
        # produced while handling this request with the same id.
        token = request_id_ctx.set(request_id)

        # Skip verbose logging for performance - only log errors
        start_time = time.time()
        try:
            from app.services.metrics import get_metrics
            get_metrics().start_request(request_id)
        except Exception:
            pass

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            process_time = time.time() - start_time

            # Add minimal headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.3f}"

            # Only log slow requests (>500ms) in production
            if process_time > 0.5:
                logger.warning(f"SLOW: {request.method} {request.url.path} - {process_time:.3f}s")

            return response

        except Exception as e:
            logger.error(f"ERROR: {request.method} {request.url.path} - {str(e)}")
            raise
        finally:
            try:
                from app.services.metrics import get_metrics
                get_metrics().end_request(request_id, request.method, request.url.path, status_code)
            except Exception:
                pass
            request_id_ctx.reset(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting for distributed deployments, with an in-memory
    fallback. Sliding window, ONE bucket per request, scoped by identity (E0-7):

        API key  >  authenticated user  >  anonymous IP

    Per-IP alone was evadable by IP rotation, and in the other direction one hot
    authenticated user exhausted the shared bucket for everyone NAT'd behind the
    same IP. Identity resolution never touches the DB:
      * API keys are identified by sha256 of the raw key (the same primitive
        api_key_service persists) — a fabricated key just burns its own bucket
        and still 401s at the route.
      * Users are identified by the signature-VERIFIED user_id claim. An
        unverified claim read would let an attacker mint unlimited buckets (and
        escape the IP bucket) by forging user_ids; a raw-token hash would let
        them reset the budget on every /auth/refresh. Tokens that don't verify
        fall back to the anonymous IP bucket.
    """

    def __init__(self, app, requests_limit: int = None, window_seconds: int = None,
                 user_requests_limit: int = None, api_key_requests_limit: int = None):
        super().__init__(app)
        self.requests_limit = requests_limit or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window
        self.user_requests_limit = user_requests_limit or settings.rate_limit_user_requests
        self.api_key_requests_limit = api_key_requests_limit or settings.rate_limit_api_key_requests
        # In-memory fallback
        self._fallback_requests: Dict[str, list] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP. X-Forwarded-For / X-Real-IP are honored ONLY when
        trust_proxy_headers is set — otherwise they're spoofable and a client
        could rotate them to evade per-IP rate limiting."""
        if settings.trust_proxy_headers:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip
        return request.client.host if request.client else "unknown"

    def _resolve_identity(self, request: Request) -> tuple[str, str, int]:
        """Resolve (scope, identity, limit) for this request. Cheap and DB-free;
        runs before route dependencies, so it reads raw headers/cookies itself."""
        auth = request.headers.get("authorization", "")
        bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else None

        # 1. API key — X-API-Key header, or an lsk_-prefixed bearer (public_api
        #    accepts both). Identity = sha256(raw key): no verification, no DB.
        api_key = request.headers.get("x-api-key") or (
            bearer if bearer and bearer.startswith("lsk_") else None
        )
        if api_key:
            digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return "key", digest, self.api_key_requests_limit

        # 2. Authenticated user — bearer JWT or the httpOnly access cookie.
        #    MUST be signature-verified (see class docstring); quiet on failure.
        token = bearer
        if not token:
            cookies = getattr(request, "cookies", None)
            if isinstance(cookies, dict):
                token = cookies.get("access_token")
        if token:
            try:
                from app.services.jwt_keys import get_key_provider
                claims = get_key_provider().verify(token)
                user_id = claims.get("user_id")
                if user_id is not None:
                    return "user", str(user_id), self.user_requests_limit
            except Exception:
                pass  # unverifiable token → anonymous bucket

        # 3. Anonymous — the strict per-IP bucket.
        return "ip", self._get_client_ip(request), self.requests_limit

    async def _check_rate_limit_redis(self, bucket: str, limit: int) -> tuple[bool, int, int]:
        """Check rate limit using Redis sliding window. Returns (allowed, remaining, retry_after)."""
        try:
            from app.services.redis_client import redis_client
            if not redis_client:
                raise Exception("Redis not available")

            key = f"ratelimit:{bucket}"
            current_time = time.time()
            window_start = current_time - self.window_seconds

            pipe = redis_client.pipeline()
            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {f"{current_time}:{uuid.uuid4().hex[:8]}": current_time})
            # Count requests in window
            pipe.zcard(key)
            # Set TTL on key
            pipe.expire(key, self.window_seconds + 1)

            results = await pipe.execute()
            request_count = results[2]

            remaining = max(0, limit - request_count)

            if request_count > limit:
                # Get oldest request to calculate retry-after
                oldest = await redis_client.zrange(key, 0, 0, withscores=True)
                if oldest:
                    retry_after = int(self.window_seconds - (current_time - oldest[0][1]))
                else:
                    retry_after = self.window_seconds
                return False, 0, max(1, retry_after)

            return True, remaining, 0

        except Exception:
            # Fallback to in-memory
            return self._check_rate_limit_memory(bucket, limit)

    def _check_rate_limit_memory(self, bucket: str, limit: int) -> tuple[bool, int, int]:
        """Fallback in-memory rate limiting."""
        current_time = time.time()
        cutoff = current_time - self.window_seconds
        self._fallback_requests[bucket] = [
            t for t in self._fallback_requests[bucket] if t > cutoff
        ]

        if len(self._fallback_requests[bucket]) >= limit:
            oldest = min(self._fallback_requests[bucket])
            retry_after = int(self.window_seconds - (current_time - oldest))
            return False, 0, max(1, retry_after)

        self._fallback_requests[bucket].append(current_time)
        remaining = limit - len(self._fallback_requests[bucket])
        return True, remaining, 0

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks and docs
        skip_paths = ["/health", "/docs", "/openapi.json", "/redoc"]
        if request.url.path in skip_paths:
            return await call_next(request)

        scope, identity, limit = self._resolve_identity(request)
        bucket = f"{scope}:{identity}"
        try:
            allowed, remaining, retry_after = await self._check_rate_limit_redis(bucket, limit)
        except Exception:
            # Redis path failed unexpectedly — fall back to in-memory limiting
            allowed, remaining, retry_after = self._check_rate_limit_memory(bucket, limit)

        if not allowed:
            request_id = getattr(request.state, 'request_id', 'unknown')
            logger.warning(f"[{request_id}] Rate limit exceeded for {scope}: {identity}")

            try:
                from app.services.security_events import record_event
                # identity is a user_id / key hash / IP — never a raw credential.
                await record_event("rate_limited", request=request,
                                   ip_address=self._get_client_ip(request),
                                   detail=f"Rate limit exceeded ({limit}/{self.window_seconds}s, scope={scope})",
                                   evidence={"limit": limit, "window_s": self.window_seconds,
                                             "scope": scope, "identity": identity})
            except Exception:
                pass

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "retry_after": retry_after
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Scope": scope,
                }
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self.window_seconds)
        response.headers["X-RateLimit-Scope"] = scope
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive security headers middleware.
    Adds CSP, HSTS, X-Content-Type-Options, X-Frame-Options, and more.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Core security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        
        # Content Security Policy. connect-src is environment-driven (see
        # settings.csp_connect_src) so production isn't pinned to localhost.
        # 'unsafe-inline' is retained for script/style because the bundled
        # Swagger UI and Next.js runtime require inline script/style; switching
        # to per-request nonces would be the next tightening step.
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "font-src 'self' data:",
            f"connect-src {settings.csp_connect_src}",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
        if settings.environment == "production":
            csp_directives.append("upgrade-insecure-requests")
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
        
        # HSTS - always set (browsers ignore it on HTTP anyway)
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        else:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce request body size limits.
    Prevents abuse from oversized payloads.
    """
    
    def __init__(self, app, max_size_mb: int = None):
        super().__init__(app)
        self.max_size_bytes = (max_size_mb or settings.max_body_size_mb) * 1024 * 1024
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check Content-Length header
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size_bytes:
            max_mb = self.max_size_bytes / (1024 * 1024)
            return JSONResponse(
                status_code=413,
                content={
                    "error": "Request Entity Too Large",
                    "message": f"Request body exceeds maximum size of {max_mb:.0f}MB",
                    "max_size_mb": max_mb
                }
            )
        
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection for state-changing endpoints.
    Uses double-submit cookie pattern.
    - Sets a CSRF token cookie on GET requests
    - Validates X-CSRF-Token header on POST/PUT/DELETE requests
    - Exempts API endpoints that use Bearer token auth (they're CSRF-safe)
    """
    
    EXEMPT_PATHS = {
        "/health", "/docs", "/openapi.json", "/redoc",
        "/api/auth/login", "/api/auth/refresh", "/api/auth/signup",
        "/api/auth/2fa/verify",  # pre-auth 2FA step (no bearer yet)
        "/api/auth/forgot-password", "/api/auth/reset-password",  # pre-auth
        "/api/auth/verify-email",  # pre-auth (link from email)
        "/api/auth/accept-invite",  # pre-auth (invite link from email)
        "/api/ai/chat/stream",  # Streaming endpoint
    }
    
    EXEMPT_PREFIXES = (
        "/stream/",        # SSE endpoints
        "/api/ai/",        # AI streaming
        "/api/public/",    # Public API — authenticated by per-tenant API key, not cookies
    )
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            response = await call_next(request)
            # Set CSRF cookie on GET requests
            if request.method == "GET" and request.url.path.startswith("/api/"):
                csrf_token = request.cookies.get("csrf_token")
                if not csrf_token:
                    csrf_token = secrets.token_urlsafe(32)
                    response.set_cookie(
                        key="csrf_token",
                        value=csrf_token,
                        httponly=False,  # JS needs to read this
                        samesite="strict",
                        secure=settings.environment == "production",
                        max_age=3600
                    )
            return response
        
        # Skip exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)
        
        # Skip exempt prefixes
        for prefix in self.EXEMPT_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)
        
        # If request has Bearer auth, it's safe from CSRF
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)
        
        # For cookie-based auth, validate CSRF token
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("x-csrf-token")
        
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            try:
                from app.services.security_events import record_event
                await record_event("csrf_failed", request=request,
                                   detail=f"CSRF validation failed on {request.method} {request.url.path}")
            except Exception:
                pass
            return JSONResponse(
                status_code=403,
                content={
                    "error": "CSRF Validation Failed",
                    "message": "Missing or invalid CSRF token"
                }
            )
        
        return await call_next(request)


class SessionInvalidationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check if a token has been invalidated (blacklisted) on logout.
    Uses Redis to store invalidated token hashes.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Pull the access token from the Bearer header OR the httpOnly cookie —
        # a logged-out cookie session must be rejected the same as a Bearer one.
        auth_header = request.headers.get("authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
        else:
            token = request.cookies.get("access_token")

        if token:
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            revoked = False
            reason = "logged-out / revoked token"
            try:
                from app.services.redis_client import redis_client
                if not redis_client:
                    raise RuntimeError("redis_client unavailable")
                revoked = bool(await redis_client.get(f"blacklisted_token:{token_hash}"))
            except Exception as e:
                # Can't consult the blacklist. Fail CLOSED by default so a revoked
                # token isn't silently honored during a Redis outage.
                if settings.auth_fail_open_on_redis_down:
                    revoked = False
                    logger.warning(f"Blacklist check failed ({e}); allowing (fail-open)")
                else:
                    revoked = True
                    reason = "session store unavailable (fail-closed)"
                    logger.error(f"Blacklist check failed ({e}); REJECTING (fail-closed)")

            if revoked:
                try:
                    from app.services.security_events import record_event
                    await record_event("token_blacklisted", request=request,
                                       detail=f"Rejected request — {reason}")
                except Exception:
                    pass
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Token Invalidated",
                        "message": "This session is no longer valid. Please login again."
                    }
                )

        return await call_next(request)
