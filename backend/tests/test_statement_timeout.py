"""E6-4: every app DB connection carries a default statement_timeout, so no
endpoint can hold a connection on one runaway query; known long operations opt
out per-transaction with SET LOCAL (which cannot leak back into the pool).

The live cancel behaviour (pg_sleep(11) → QueryCanceled at ~10s) is exercised
against the docker stack; these are DB-free structural guards.
"""
import inspect

from app.config import Settings


def _fresh_settings(**over):
    base = dict(
        environment="testing",
        jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
        secret_key="test-app-secret-key-minimum-32-chars-for-testing",
    )
    base.update(over)
    return Settings(**base)


def test_default_timeout_is_ten_seconds():
    s = _fresh_settings()
    assert s.db_statement_timeout_ms == 10000


def test_engine_kwargs_carry_the_timeout():
    """The connect-time server_settings is the only mechanism that covers BOTH
    get_db and the routes that use async_session() directly."""
    import app.services.database as db

    ca = db._engine_kwargs.get("connect_args", {})
    ss = ca.get("server_settings", {})
    # conftest forces ENVIRONMENT=testing but the timeout applies in every env.
    assert ss.get("statement_timeout") == str(db.settings.db_statement_timeout_ms)


def test_exemption_helper_uses_set_local_only():
    """SET LOCAL is transaction-scoped — a plain SET (session-scoped) would leak
    the exemption back into the pool when the connection is returned."""
    from app.services.database import exempt_statement_timeout

    src = inspect.getsource(exempt_statement_timeout)
    assert "SET LOCAL statement_timeout" in src
    assert "SET statement_timeout" not in src.replace("SET LOCAL statement_timeout", "")


def test_long_paths_are_exempted():
    """Each known long operation opts out inside its own transaction."""
    import app.services.db_seeder as seeder
    import app.services.demo_reset as demo_reset
    import app.services.forecast_trainer as trainer
    import app.services.migration_runner as runner
    from app.services.ingest import bulk

    for mod in (runner, seeder, trainer, bulk, demo_reset):
        src = inspect.getsource(mod)
        assert "exempt_statement_timeout" in src, f"{mod.__name__} lost its E6-4 exemption"


def test_request_path_is_not_exempted():
    """get_db must NOT lift the timeout — request handlers are exactly what the
    cap exists to bound."""
    import app.services.database as db

    src = inspect.getsource(db.get_db)
    assert "exempt_statement_timeout" not in src
