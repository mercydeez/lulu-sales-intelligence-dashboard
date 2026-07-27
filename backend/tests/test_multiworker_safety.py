"""E6-5 follow-up — the invariants that make `gunicorn --workers N` safe.

Three classes of thing had to become true:

  1. no CONTINUOUS singleton (generator, partition maintenance, …) starts in an
     API worker — they run in exactly one `singletons` container;
  2. concurrent BOOT is serialized so N processes don't race the same DDL;
  3. no request-handling state lives in one worker's heap (Sage history, bulk-job
     state, the metrics-warm dedup).

These are structural guards; the live behaviour is verified against real Postgres
in the commit (four concurrent migration runners, generator rate not multiplied,
Sage multi-turn across workers).
"""
import ast
import inspect
import textwrap

import pytest


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# 1. The API process starts NO continuous singleton.
# --------------------------------------------------------------------------

def test_api_lifespan_starts_only_the_import_scheduler():
    """Every _track()'d loop in the API lifespan is safe across processes. Today
    that is exactly one: import_scheduler (FOR UPDATE SKIP LOCKED). If a future
    edit re-adds the generator or partition maintenance to the API, N workers run
    N of them again — this catches it."""
    from app import main
    src = inspect.getsource(main.lifespan)

    for forbidden in ("DataGenerator(", "run_demo_reset_loop(", "run_cache_warmer(",
                      "run_forecast_trainer(", "partition_maintenance_loop("):
        assert forbidden not in src, (
            f"the API lifespan must not start {forbidden} — it belongs in the "
            f"singletons container, or N workers will run N of it"
        )
    # The one loop that IS safe here.
    assert "scheduler_loop(" in src


def test_api_does_not_even_import_the_singleton_services():
    """Belt and suspenders: the singleton services are not imported at API module
    load, so they cannot be started by accident."""
    from app import main
    module_src = inspect.getsource(main)
    # These imports were removed from main.py's top; they now live only in
    # app/commands/singletons.py.
    assert "from app.services.data_generator import DataGenerator" not in module_src
    assert "from app.services.cache_warmer import run_cache_warmer" not in module_src


def test_singletons_command_hosts_every_continuous_loop():
    """The mirror image: the singletons process runs all five, each still flag-gated."""
    from app.commands import singletons
    src = inspect.getsource(singletons)
    for loop in ("DataGenerator(", "run_demo_reset_loop(", "run_cache_warmer(",
                 "run_forecast_trainer(", "partition_maintenance_loop("):
        assert loop in src, f"singletons must host {loop}"
    # Same gating as the old lifespan — nothing new runs by default.
    assert "settings.demo_mode and settings.live_generator_enabled" in src
    assert "settings.partition_maintenance_enabled" in src


# --------------------------------------------------------------------------
# 2. Startup DDL is serialized by ONE session-level advisory lock.
# --------------------------------------------------------------------------

def _module_code_without_comments(module) -> str:
    """Module source with `#` comments and docstrings removed, so an assertion
    about the CODE doesn't trip on prose that names the forbidden thing (the
    leader_lock docstring explains why we avoid pg_advisory_xact_lock)."""
    tree = ast.parse(inspect.getsource(module))
    # Drop docstrings from module + every def/class.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:]
    return ast.unparse(tree)


def test_the_startup_lock_is_session_scoped_not_transaction_scoped():
    """Migration files embed literal COMMIT (001-004, 063); a *transaction*-scoped
    advisory lock releases on that inner COMMIT mid-run. Must be pg_advisory_lock,
    never pg_advisory_xact_lock."""
    from app.services import leader_lock
    code = _module_code_without_comments(leader_lock)
    assert "pg_advisory_lock(" in code
    assert "pg_advisory_xact_lock" not in code


def test_the_startup_lock_holds_a_non_reapable_dedicated_connection():
    """A pooled connection can be recycled underneath the lock; an idle reaper can
    drop it mid-backfill. The lock connection is dedicated and disables both."""
    from app.services import leader_lock
    src = inspect.getsource(leader_lock)  # whole module (asynccontextmanager wraps the fn)
    assert "asyncpg.connect" in src, "must hold its own connection, not a pooled one"
    assert "idle_session_timeout = 0" in src
    assert "idle_in_transaction_session_timeout = 0" in src


def test_the_lock_key_is_a_fixed_constant():
    """Every booting process must compute the identical key, so it cannot be
    derived at runtime."""
    from app.services import leader_lock
    assert isinstance(leader_lock.STARTUP_DDL_LOCK_KEY, int)
    # signed 64-bit range (Postgres advisory key)
    assert -(2**63) <= leader_lock.STARTUP_DDL_LOCK_KEY < 2**63


def test_startup_work_runs_inside_the_lock():
    """seed / migrate / employee / backfill are all under the one lock."""
    from app import main
    src = inspect.getsource(main.lifespan)
    assert "async with startup_lock():" in src
    lock_at = src.index("async with startup_lock():")
    tail = src[lock_at:]
    for guarded in ("run_seed()", "run_migrations()", "initialize_employee_system()",
                    "backfill_item_costs"):
        assert guarded in tail, f"{guarded} must be inside the startup lock"


def test_migration_tracker_insert_is_idempotent():
    """Defence-in-depth: a torn boot must never crash a later process on the PK."""
    from app.services import migration_runner
    src = inspect.getsource(migration_runner.run_migrations)
    assert "ON CONFLICT (version) DO NOTHING" in src


# --------------------------------------------------------------------------
# 3. No request-handling state in a worker's heap.
# --------------------------------------------------------------------------

def test_sage_conversation_state_is_in_redis_not_a_process_dict():
    from app.services import ai_assistant
    src = inspect.getsource(ai_assistant)
    # The old module-level dict is gone.
    assert "conversation_store: Dict" not in src
    assert "conversation_store = {}" not in src
    # Load/save go through the shared cache.
    assert "async def load_context" in src
    assert "async def save_context" in src


def test_the_sage_clarification_state_survives_serialization():
    """`pending` (Sage v3's parked clarification/readback) is load-bearing multi-turn
    state — if it isn't serialized, a follow-up on another worker is mishandled as a
    new query. It must be in both to_dict and from_dict."""
    from app.services.ai_assistant import ConversationContext
    ctx = ConversationContext()
    ctx.add_message("user", "hi")
    ctx.pending = {"mode": "readback", "original_query": "show sales"}
    ctx.detected_intents = ["sales"]

    restored = ConversationContext.from_dict(ctx.to_dict())
    assert restored.pending == {"mode": "readback", "original_query": "show sales"}
    assert restored.messages == ctx.messages
    assert restored.detected_intents == ["sales"]


def test_the_turn_persists_on_every_exit_path():
    """A `finally: await save_context(...)` wraps the turn so history persists even
    when the streaming generator is cancelled by a client disconnect."""
    from app.services import ai_assistant
    for fn in (ai_assistant.stream_chat_response, ai_assistant.get_chat_response):
        code = _code(fn)
        assert "await load_context(" in code
        assert "finally:" in code
        assert "await save_context(session_id, context)" in code


def test_bulk_job_state_is_in_redis_not_a_process_dict():
    from app.services.ingest import bulk
    src = inspect.getsource(bulk)
    assert "_active_jobs" not in src, "in-process job dict must be gone"
    assert "async def _set_job_state" in src
    assert "async def _get_job_state" in src


def test_metrics_warm_dedup_is_a_redis_lease_not_a_process_set():
    from app.routes import analytics
    src = inspect.getsource(analytics)
    assert "_inflight_metrics" not in src
    # SET NX lease across workers.
    claim = _code(analytics._try_claim_metrics_warm)
    assert "nx=True" in claim


# --------------------------------------------------------------------------
# Process model.
# --------------------------------------------------------------------------

def test_the_dockerfile_cmd_stays_single_worker():
    """Worker count is set PER SERVICE in compose, never in the base CMD, so prod
    (which has no command: override on some paths) can't silently inherit N."""
    import os
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(repo, "backend", "Dockerfile"), encoding="utf-8") as fh:
        dockerfile = fh.read()
    assert "gunicorn" not in dockerfile, "the Dockerfile CMD must not hardcode gunicorn/workers"
    assert '"uvicorn"' in dockerfile or "uvicorn app.main:app" in dockerfile


def test_compose_uses_gunicorn_with_a_worker_count_env():
    import os
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in ("docker-compose.yml", "docker-compose.production.yml"):
        with open(os.path.join(repo, rel), encoding="utf-8") as fh:
            text = fh.read()
        assert "gunicorn app.main:app" in text, f"{rel} should run gunicorn"
        assert "uvicorn.workers.UvicornWorker" in text
        assert "WEB_CONCURRENCY" in text, f"{rel} worker count should be env-driven"
