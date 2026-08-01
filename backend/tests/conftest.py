"""
Pytest configuration and shared fixtures for the Retail IQ test suite.
"""
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Force test environment BEFORE any app imports
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-minimum-32-chars-long-for-testing"
os.environ["SECRET_KEY"] = "test-app-secret-key-minimum-32-chars-for-testing"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
# Docker compose injects these as empty strings, which Settings would read as ""
# instead of the documented None default — drop them for deterministic tests.
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("DEEPGRAM_API_KEY", None)


def registered_paths(app) -> set:
    """Every path the app actually serves, as a flat set of strings.

    FastAPI >=0.13x wraps `include_router()`'d routes in a lazy `_IncludedRouter`
    that has no `.path` of its own, so walking `app.routes` directly and reading
    `.path` breaks. The OpenAPI schema is the stable, public way to get the
    fully-resolved path set regardless of that internal representation.
    """
    return set(app.openapi()["paths"].keys())


class _FakeRedis:
    """A tiny in-memory async Redis stand-in — just enough for the app's usage
    (get/set with ex+nx, delete, keys). Lets tests exercise the Redis-backed
    conversation store / job state / warm-lease without a live Redis."""

    def __init__(self):
        self._d: dict = {}

    async def get(self, key):
        return self._d.get(key)

    async def set(self, key, value, ex=None, nx=False, **kw):
        if nx and key in self._d:
            return None
        self._d[key] = value
        return True

    async def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self._d:
                del self._d[k]
                n += 1
        return n

    async def keys(self, pattern="*"):
        import fnmatch
        return [k for k in self._d if fnmatch.fnmatch(k, pattern)]


@pytest.fixture
def fake_redis():
    """Install an in-memory fake as app.services.redis_client.redis_client for the
    duration of a test. Restores the prior value afterward."""
    from app.services import redis_client as rc
    prior = rc.redis_client
    rc.redis_client = _FakeRedis()
    try:
        yield rc.redis_client
    finally:
        rc.redis_client = prior


@pytest.fixture
def test_settings():
    """Return a Settings instance configured for testing."""
    from app.config import Settings
    return Settings(
        environment="testing",
        debug=False,
        jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
        secret_key="test-app-secret-key-minimum-32-chars-for-testing",
        database_url="postgresql+asyncpg://testuser:testpass@localhost:5432/testdb",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
def production_settings():
    """Return a Settings instance simulating a SECURE production config.

    Meets the tightened fail-closed bar: strong secrets, RLS role enabled with a
    strong app_rw URL, managed Redis (not self-hosted), no demo flags. This is the
    canonical 'good prod' config that validate_security() must accept.
    """
    from app.config import Settings
    return Settings(
        environment="production",
        debug=False,
        jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
        secret_key="another-strong-production-secret-key-for-the-app-layer",
        database_url="postgresql+asyncpg://produser:str0ng_Pr0d_P@ss!@db.prod:5432/proddb",
        redis_url="redis://redis.prod:6379/0",
        use_rls_role=True,
        rls_database_url="postgresql+asyncpg://app_rw:str0ng_App_RW_P@ss!@db.prod:5432/proddb",
    )


@pytest.fixture
def insecure_production_settings():
    """Return a production Settings instance with insecure defaults (should fail validation)."""
    from app.config import Settings
    return Settings(
        environment="production",
        debug=True,
        jwt_secret_key="super-secret-change-in-production-2026",  # default!
        secret_key="your-secret-key-change-in-production",        # default!
        database_url="postgresql+asyncpg://salesuser:salespass@localhost:5432/salesdb",
    )
