"""
Health & Startup Tests — Validates the /health endpoint and app factory.
Uses httpx.AsyncClient with the FastAPI test client (no real DB/Redis needed).
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db_and_redis():
    """Patch database and redis so the app can start without real services."""
    with patch("app.main.init_db", new_callable=AsyncMock) as mock_init_db, \
         patch("app.main.close_db", new_callable=AsyncMock), \
         patch("app.main.init_redis", new_callable=AsyncMock), \
         patch("app.main.close_redis", new_callable=AsyncMock), \
         patch("app.main.initialize_employee_system", new_callable=AsyncMock), \
         patch("app.main.DataGenerator") as mock_gen:

        # Make the generator's start() a coroutine that just sleeps
        instance = MagicMock()
        async def fake_start():
            import asyncio
            await asyncio.sleep(999999)
        instance.start = fake_start
        mock_gen.return_value = instance

        yield mock_init_db


# =============================================================================
# Tests
# =============================================================================

@pytest.mark.asyncio
async def test_health_endpoint_returns_200(mock_db_and_redis):
    """The /health endpoint should return 200 even when services are mocked."""
    from app.main import app

    # Patch the actual health-check internals
    with patch("app.services.database.engine") as mock_engine, \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as mock_get_redis:

        # Simulate healthy DB
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value = mock_conn

        # Simulate healthy Redis
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_get_redis.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_health_response_fields(mock_db_and_redis):
    """Ensure all expected fields are present in the health response."""
    from app.main import app

    with patch("app.services.database.engine") as mock_engine, \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as mock_get_redis:

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value = mock_conn

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_get_redis.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        data = response.json()
        expected_fields = {"status", "database", "redis", "timestamp", "version", "environment"}
        assert expected_fields.issubset(set(data.keys()))


# =============================================================================
# Phase 3 — liveness / readiness / deep probes
# =============================================================================

def _healthy_engine_mock():
    """An engine mock whose connect() yields a conn with a usable result."""
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.fetchone.return_value = (True, True)
    result.scalar.return_value = None
    mock_conn.execute = AsyncMock(return_value=result)
    engine = MagicMock()
    engine.connect.return_value = mock_conn
    return engine


async def _get(path):
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_live_is_independent_of_dependencies():
    """Liveness must not touch DB/Redis and always returns 200."""
    resp = await _get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_ready_200_when_all_healthy():
    with patch("app.services.database.engine", _healthy_engine_mock()), \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as gr, \
         patch("app.services.migration_runner.pending_migrations",
               new_callable=AsyncMock, return_value=[]):
        gr.return_value = AsyncMock(ping=AsyncMock(return_value=True))
        resp = await _get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"] == "current"


@pytest.mark.asyncio
async def test_ready_503_when_db_down():
    bad_engine = MagicMock()
    bad_engine.connect.side_effect = RuntimeError("db down")
    with patch("app.services.database.engine", bad_engine), \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as gr, \
         patch("app.services.migration_runner.pending_migrations",
               new_callable=AsyncMock, return_value=[]):
        gr.return_value = AsyncMock(ping=AsyncMock(return_value=True))
        resp = await _get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] == "error"


@pytest.mark.asyncio
async def test_ready_503_when_migrations_pending():
    with patch("app.services.database.engine", _healthy_engine_mock()), \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as gr, \
         patch("app.services.migration_runner.pending_migrations",
               new_callable=AsyncMock, return_value=["099_new.sql"]):
        gr.return_value = AsyncMock(ping=AsyncMock(return_value=True))
        resp = await _get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["migrations"] == "pending:1"


@pytest.mark.asyncio
async def test_deep_reports_mode_and_leaks_no_secrets():
    with patch("app.services.database.engine", _healthy_engine_mock()), \
         patch("app.services.redis_client.get_redis", new_callable=AsyncMock) as gr, \
         patch("app.services.migration_runner.pending_migrations",
               new_callable=AsyncMock, return_value=[]):
        gr.return_value = AsyncMock(ping=AsyncMock(return_value=True),
                                    keys=AsyncMock(return_value=[]))
        resp = await _get("/health/deep")
    assert resp.status_code == 200
    body = resp.json()
    assert "mode" in body and "demo_mode" in body["mode"]
    assert body["checks"]["database"] == "ok"
    # No secret material anywhere in the payload.
    blob = resp.text.lower()
    for needle in ("secret", "password", "jwt", "salespass"):
        assert needle not in blob
