"""
Pytest configuration and shared fixtures for the Lulu Intelligence Dashboard test suite.
"""
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Force test environment BEFORE any app imports
os.environ["ENVIRONMENT"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-minimum-32-chars-long-for-testing"
os.environ["SECRET_KEY"] = "test-app-secret-key-minimum-32-chars-for-testing"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
    """Return a Settings instance simulating production."""
    from app.config import Settings
    return Settings(
        environment="production",
        debug=False,
        jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
        secret_key="another-strong-production-secret-key-for-the-app-layer",
        database_url="postgresql+asyncpg://produser:str0ng_Pr0d_P@ss!@db.prod:5432/proddb",
        redis_url="redis://redis.prod:6379/0",
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
