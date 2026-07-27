"""D1 — DB role passwords must sync from the environment at migrate time.

The deploy blocker: migrations 020/023/029/035 hardcode DEV passwords on
app_rw / sage_ro / worker_rw, while the production compose hands the API/worker
operator-chosen secrets (RLS_DATABASE_URL, WORKER_DATABASE_URL built from
WORKER_DB_PASSWORD, SAGE_DATABASE_URL). services/role_password_sync closes the
gap after every migration pass. These tests pin the parsing, the secret-hygiene
structure, the wiring, and the behavior against a fake connection.
"""
import ast
import inspect
import logging
import textwrap

import pytest

import app.commands.migrate as migrate_cmd
from app.services import migration_runner
from app.services import role_password_sync as rps

_ALL_SOURCE_VARS = (
    "WORKER_DB_PASSWORD", "WORKER_DATABASE_URL", "RLS_DATABASE_URL", "SAGE_DATABASE_URL",
)


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def _module_source() -> str:
    return inspect.getsource(rps)


def _clear_sources(monkeypatch):
    for var in _ALL_SOURCE_VARS:
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------
# Parsing: passwords come out of the URLs the services themselves consume.
# --------------------------------------------------------------------------

def test_percent_encoded_password_in_url_is_decoded():
    url = "postgresql+asyncpg://app_rw:p%40ss%3Aw%25rd@postgres:5432/salesdb"
    assert rps._password_from_url(url) == "p@ss:w%rd"


def test_password_with_hash_question_slash_is_not_truncated():
    # urlsplit alone truncates at '#'/'?'/'/' — the sync must parse with the
    # SAME semantics as the engine that will consume the URL (make_url).
    url = "postgresql+asyncpg://app_rw:p#ss?w/rd@postgres:5432/salesdb"
    assert rps._password_from_url(url) == "p#ss?w/rd"


def test_url_without_a_password_yields_none():
    assert rps._password_from_url("postgresql+asyncpg://app_rw@postgres:5432/salesdb") is None
    assert rps._password_from_url("") is None
    assert rps._password_from_url(None) is None


def test_absent_or_empty_env_skips_every_pair(monkeypatch):
    _clear_sources(monkeypatch)
    assert rps._desired_pairs() == []

    for var in _ALL_SOURCE_VARS:
        monkeypatch.setenv(var, "")
    assert rps._desired_pairs() == []


def test_pairs_carry_the_exact_env_values(monkeypatch):
    _clear_sources(monkeypatch)
    monkeypatch.setenv("WORKER_DB_PASSWORD", "W0rker!secret")
    monkeypatch.setenv(
        "RLS_DATABASE_URL",
        "postgresql+asyncpg://app_rw:App%40Secret@postgres:5432/salesdb",
    )
    monkeypatch.setenv(
        "SAGE_DATABASE_URL",
        "postgresql+asyncpg://sage_ro:Sage%23Secret@postgres:5432/salesdb",
    )
    assert rps._desired_pairs() == [
        ("worker_rw", "W0rker!secret"),
        ("app_rw", "App@Secret"),
        ("sage_ro", "Sage#Secret"),
    ]


def test_worker_password_falls_back_to_worker_database_url(monkeypatch):
    _clear_sources(monkeypatch)
    monkeypatch.setenv(
        "WORKER_DATABASE_URL",
        "postgresql://worker_rw:FromUrl%21@postgres:5432/salesdb",
    )
    assert rps._desired_pairs() == [("worker_rw", "FromUrl!")]


# --------------------------------------------------------------------------
# Structure: the secret must be unleakable by construction.
# --------------------------------------------------------------------------

_SECRET_NAMES = {
    "password", "pw", "secret", "secrets", "alter_sql",
    "worker_pw", "app_pw", "sage_pw", "parsed", "fallback", "value", "variant",
}


def test_no_logger_call_references_a_secret_bearing_variable():
    tree = ast.parse(_module_source())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "logger":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in _SECRET_NAMES:
                    offenders.append((node.lineno, sub.id))
    assert offenders == [], f"logger calls reference secret variables: {offenders}"


def test_no_fstring_embeds_a_secret_bearing_variable():
    tree = ast.parse(_module_source())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in _SECRET_NAMES:
                    offenders.append((node.lineno, sub.id))
    assert offenders == [], f"f-strings embed secret variables: {offenders}"


def test_the_alter_is_built_server_side_with_postgres_quoting():
    src = _module_source()
    assert "format('ALTER ROLE %I PASSWORD %L'" in src
    # and never composed by Python string interpolation of the secret:
    assert 'f"ALTER ROLE' not in src and "f'ALTER ROLE" not in src


def test_the_role_existence_guard_is_present():
    src = _module_source()
    assert "pg_roles" in src
    assert "rolname = :r" in src


def test_postgres_statement_logging_is_suppressed():
    src = _module_source()
    assert "SET LOCAL log_statement = 'none'" in src
    assert "SET LOCAL log_min_duration_statement = -1" in src


def test_url_parsing_matches_the_engine_with_an_unquote_fallback():
    src = _code(rps._password_from_url)
    assert "make_url" in src
    assert "unquote" in src


def test_all_three_dev_password_roles_are_covered():
    src = _module_source()
    for role in ("worker_rw", "app_rw", "sage_ro"):
        assert f'"{role}"' in src


# --------------------------------------------------------------------------
# Wiring: the sync runs AFTER the migration loop, on every migrate path.
# --------------------------------------------------------------------------

def test_run_migrations_calls_the_sync_after_the_migration_loop():
    src = _code(migration_runner.run_migrations)
    assert "sync_role_passwords" in src
    loop_at = src.index("for filename in migration_files")
    sync_at = src.index("sync_role_passwords")
    assert loop_at < sync_at, "sync must run after migrations apply, not before"


def test_the_migrate_command_reaches_the_sync_via_run_migrations():
    # The one-shot prod job (python -m app.commands.migrate) and the
    # RUN_MIGRATIONS_ON_STARTUP lifespan path both funnel through
    # run_migrations, which ends with the sync (asserted above).
    src = _code(migrate_cmd._main)
    assert "run_migrations()" in src


# --------------------------------------------------------------------------
# Behavior against a fake connection recording every statement.
# --------------------------------------------------------------------------

class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeConn:
    """Records executed SQL. The format() SELECT returns a SENTINEL string, so
    a correctly-built module must execute exactly that sentinel as the ALTER —
    proving the statement text came from Postgres-side format(), never from
    Python interpolation of the raw secret."""

    def __init__(self, roles=(), refuse_set_local=False, fail_alter=None):
        self.roles = set(roles)
        self.refuse_set_local = refuse_set_local
        self.fail_alter = fail_alter
        self.executed = []          # (sql, params) via execute()
        self.driver_executed = []   # raw strings via exec_driver_sql()

    async def execute(self, clause, params=None):
        sql = str(clause)
        self.executed.append((sql, params))
        if "SET LOCAL" in sql:
            if self.refuse_set_local:
                raise RuntimeError("permission denied to set parameter")
            return _Result(None)
        if "pg_roles" in sql:
            return _Result(1 if params["r"] in self.roles else None)
        if "format(" in sql:
            return _Result(f"SENTINEL-ALTER::{params['role']}")
        return _Result(None)

    async def exec_driver_sql(self, sql):
        if self.fail_alter is not None:
            raise self.fail_alter
        self.driver_executed.append(sql)
        return _Result(None)


class FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _set_two_envs(monkeypatch, worker_pw="W0rker!secret", app_pw_encoded="App%40Secret"):
    _clear_sources(monkeypatch)
    monkeypatch.setenv("WORKER_DB_PASSWORD", worker_pw)
    monkeypatch.setenv(
        "RLS_DATABASE_URL",
        f"postgresql+asyncpg://app_rw:{app_pw_encoded}@postgres:5432/salesdb",
    )


async def test_no_env_is_a_silent_noop_without_touching_the_engine(monkeypatch):
    _clear_sources(monkeypatch)
    # engine=None: if the no-op path resolved the engine this would import and
    # use the real one — returning 0 first proves dev boots stay untouched.
    assert await rps.sync_role_passwords() == 0


async def test_missing_role_executes_no_alter(monkeypatch):
    _set_two_envs(monkeypatch)
    conn = FakeConn(roles=())  # neither role exists
    assert await rps.sync_role_passwords(engine=FakeEngine(conn)) == 0
    assert conn.driver_executed == []


async def test_both_roles_synced_through_the_server_side_format_path(monkeypatch):
    _set_two_envs(monkeypatch)
    conn = FakeConn(roles={"worker_rw", "app_rw"})
    assert await rps.sync_role_passwords(engine=FakeEngine(conn)) == 2

    # The executed ALTER is exactly the sentinel the format() SELECT returned.
    assert conn.driver_executed == [
        "SENTINEL-ALTER::worker_rw",
        "SENTINEL-ALTER::app_rw",
    ]

    # The secret reached Postgres only as a bind parameter of the format()
    # SELECT — decoded (%40 -> @) and never embedded in any statement text.
    format_params = [p for (s, p) in conn.executed if "format(" in s]
    assert [p["pw"] for p in format_params] == ["W0rker!secret", "App@Secret"]
    for sql, _params in conn.executed:
        assert "W0rker!secret" not in sql
        assert "App@Secret" not in sql


async def test_set_local_refusal_retries_without_suppression(monkeypatch):
    _clear_sources(monkeypatch)
    monkeypatch.setenv("WORKER_DB_PASSWORD", "W0rker!secret")
    conn = FakeConn(roles={"worker_rw"}, refuse_set_local=True)
    assert await rps.sync_role_passwords(engine=FakeEngine(conn)) == 1
    assert conn.driver_executed == ["SENTINEL-ALTER::worker_rw"]


async def test_failure_is_loud_but_never_raises_and_never_leaks(monkeypatch, caplog):
    # A password containing a single quote: %L doubles it inside the statement,
    # so the scrubber must catch BOTH the raw and the quote-doubled variant.
    _set_two_envs(monkeypatch, worker_pw="W0rk'er!secret")
    boom = RuntimeError("connection lost while running: W0rk''er!secret and W0rk'er!secret")
    conn = FakeConn(roles={"worker_rw", "app_rw"}, fail_alter=boom)
    with caplog.at_level(logging.ERROR, logger="app.services.role_password_sync"):
        assert await rps.sync_role_passwords(engine=FakeEngine(conn)) == 0
    assert "FAILED to sync" in caplog.text
    assert "W0rk'er!secret" not in caplog.text
    assert "W0rk''er!secret" not in caplog.text
    assert "***" in caplog.text


async def test_production_with_no_sources_warns_instead_of_silent_noop(monkeypatch, caplog):
    _clear_sources(monkeypatch)
    from app import config as app_config
    settings = app_config.get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    with caplog.at_level(logging.WARNING, logger="app.services.role_password_sync"):
        assert await rps.sync_role_passwords() == 0
    assert "migration-default dev passwords" in caplog.text
