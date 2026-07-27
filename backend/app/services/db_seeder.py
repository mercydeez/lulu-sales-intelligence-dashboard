"""
Database seeder.

Portable replacement for the Postgres docker-entrypoint init. Managed Postgres
(e.g. Render) cannot run database/init.sql, and a server-side
`COPY FROM '/data/train.csv'` needs the file on the DB host. So the application
owns seeding in every environment:

  1. exec database/init.sql            -> base schema + stores/items/regions/users (idempotent)
  2. if sales_historical is empty      -> bulk-load data/train.csv via asyncpg COPY (client-side, streamed)
  3. date-shift the history            -> latest day becomes yesterday

Runs once at startup, before migrations. Idempotent and safe on every boot:
already-seeded databases skip the CSV load.
"""
import asyncio
import os
import logging

from sqlalchemy import text

from app.services.database import engine

logger = logging.getLogger(__name__)

# init.sql is idempotent but still DDL: CREATE OR REPLACE VIEW / ALTER TABLE take
# AccessExclusiveLock. The worker and singletons poll the same tables and hold
# AccessShareLock, so restarting ONLY the backend while they run deadlocks the
# seeder and kills startup ("Application startup failed. Exiting."). The advisory
# startup_lock in main.py serialises backend instances but says nothing to those
# other containers. Deadlock is transient — Postgres shoots one victim — so fail
# fast on the lock and retry instead of dying.
_SCHEMA_LOCK_TIMEOUT = "15s"
_SCHEMA_MAX_ATTEMPTS = 5
_SCHEMA_RETRY_BASE_SECONDS = 2

# Retrying alone does not save us: the worker polls continuously, so the shared
# lock is effectively always held and the DDL never gets its window. The real fix
# is not to run the DDL at all on an already-provisioned database — it is pure
# overhead there, since schema CHANGES ship as numbered migrations applied
# separately by migration_runner. init.sql is only needed to build a fresh DB.
_MISSING_CORE_TABLES_SQL = """
SELECT count(*) FROM (VALUES ('stores'),('items'),('users'),('sales_historical')) AS t(n)
WHERE to_regclass('public.' || n) IS NULL
"""


def _is_lock_contention(exc: BaseException) -> bool:
    """True for deadlock / lock-timeout failures, without importing the driver."""
    if type(exc).__name__ in {"DeadlockDetectedError", "LockNotAvailableError"}:
        return True
    msg = str(exc).lower()
    return "deadlock detected" in msg or "lock timeout" in msg or "canceling statement due to lock timeout" in msg

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# backend/app/services/db_seeder.py -> repo paths
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR))))

_INIT_SQL_CANDIDATES = [
    "/app/database/init.sql",
    os.path.join(os.getcwd(), "database", "init.sql"),
    os.path.join(_REPO_ROOT, "database", "init.sql"),
]
_CSV_CANDIDATES = [
    os.environ.get("SEED_CSV_PATH", ""),
    "/app/data/train.csv",
    os.path.join(os.getcwd(), "data", "train.csv"),
    os.path.join(_REPO_ROOT, "data", "train.csv"),
]

_DATE_SHIFT_SQL = """
DO $$
DECLARE
    max_hist_date DATE;
    shift_days INTEGER;
BEGIN
    SELECT MAX(date) INTO max_hist_date FROM sales_historical;
    IF max_hist_date IS NOT NULL THEN
        shift_days := (CURRENT_DATE - 1) - max_hist_date;
        IF shift_days <> 0 THEN
            UPDATE sales_historical SET date = date + shift_days;
        END IF;
    END IF;
END $$;
"""


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


async def run_seed():
    """Ensure base schema + historical data exist. Idempotent."""
    # 1. Base schema (idempotent DDL + reference-data seeds).
    init_sql = _first_existing(_INIT_SQL_CANDIDATES)
    if not init_sql:
        logger.warning(
            "init.sql not found in %s — assuming the database is already provisioned",
            _INIT_SQL_CANDIDATES,
        )
    else:
        force_schema = os.environ.get("SEED_FORCE_SCHEMA", "").strip().lower() in {"1", "true", "yes"}
        async with engine.begin() as conn:
            missing_core = (await conn.execute(text(_MISSING_CORE_TABLES_SQL))).scalar()

        if missing_core == 0 and not force_schema:
            logger.info(
                "Base schema already provisioned — skipping init.sql "
                "(set SEED_FORCE_SCHEMA=1 to force a re-run)"
            )
            return await _seed_history()

        with open(init_sql, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        for attempt in range(1, _SCHEMA_MAX_ATTEMPTS + 1):
            try:
                async with engine.begin() as conn:
                    from app.services.database import exempt_statement_timeout
                    await exempt_statement_timeout(conn)  # schema script runs long (E6-4)
                    raw = await conn.get_raw_connection()
                    # Bound the wait for each lock so contention surfaces as a
                    # retryable error instead of a deadlock that aborts startup.
                    await raw.driver_connection.execute(
                        f"SET LOCAL lock_timeout = '{_SCHEMA_LOCK_TIMEOUT}'"
                    )
                    # asyncpg runs the multi-statement script (DO blocks, views, seeds).
                    await raw.driver_connection.execute(schema_sql)
                break
            except Exception as exc:  # noqa: BLE001 — re-raised below unless retryable
                if not _is_lock_contention(exc) or attempt == _SCHEMA_MAX_ATTEMPTS:
                    raise
                delay = _SCHEMA_RETRY_BASE_SECONDS * attempt
                logger.warning(
                    "Base schema blocked by concurrent readers (attempt %s/%s: %s) — "
                    "retrying in %ss",
                    attempt, _SCHEMA_MAX_ATTEMPTS, type(exc).__name__, delay,
                )
                await asyncio.sleep(delay)

        logger.info("Base schema ensured (%s)", init_sql)

    # 2. Bulk-load history only if empty.
    await _seed_history()


async def _refresh_date_shift():
    """Re-anchor history so its latest day is yesterday. No-op when already fresh.

    _DATE_SHIFT_SQL is a no-op when shift_days = 0, so on a same-day restart this
    costs one MAX(date) scan. It only rewrites rows when the data has actually
    drifted, which is exactly when the demo would otherwise show a month-old cliff
    in every trend chart.
    """
    try:
        async with engine.begin() as conn:
            stale = (await conn.execute(text(
                "SELECT (CURRENT_DATE - 1) - MAX(date) FROM sales_historical"
            ))).scalar()
            if not stale:
                return
            from app.services.database import exempt_statement_timeout
            await exempt_statement_timeout(conn)  # ~900k-row UPDATE when drifted
            await conn.execute(text(_DATE_SHIFT_SQL))
        logger.info("History re-anchored: shifted %s day(s) so latest day is yesterday", stale)
    except Exception as exc:  # never block startup on a demo-freshness nicety
        logger.warning("Could not re-anchor history dates (%s): %s", type(exc).__name__, exc)


async def _seed_history():
    """Bulk-load train.csv into sales_historical when empty. Idempotent.

    Split out of run_seed so the already-provisioned fast path can still reach it
    without touching any DDL.
    """
    async with engine.begin() as conn:
        count = (await conn.execute(text("SELECT COUNT(*) FROM sales_historical"))).scalar()
    if count and count > 0:
        logger.info("sales_historical already populated (%s rows) — skipping CSV load", count)
        # The date shift used to run ONLY on the initial CSV load, so a database
        # seeded N days ago serves history that ends N days ago. Found at 36 days
        # stale: every "today"/"this week" KPI was computed from the thin live
        # generator stream alone, which is why sales_today and sales_week were
        # byte-identical. Re-assert it on every boot so the demo self-heals.
        await _refresh_date_shift()
        return

    csv_path = _first_existing(_CSV_CANDIDATES)
    if not csv_path:
        logger.warning(
            "train.csv not found in %s — sales_historical left empty (set SEED_CSV_PATH)",
            _CSV_CANDIDATES,
        )
        return

    logger.info("Bulk-loading historical sales from %s ...", csv_path)
    async with engine.begin() as conn:
        from app.services.database import exempt_statement_timeout
        await exempt_statement_timeout(conn)  # ~900k-row COPY + date shift (E6-4)
        raw = await conn.get_raw_connection()
        asyncpg_conn = raw.driver_connection
        # Client-side streamed COPY (works against managed Postgres). The CSV's
        # 4 columns (date,store,item,sales) map positionally to these columns.
        await asyncpg_conn.copy_to_table(
            "sales_historical",
            source=csv_path,
            columns=["date", "store_id", "item_id", "sales"],
            format="csv",
            header=True,
        )
        # Shift dates so the latest historical day is yesterday.
        await conn.execute(text(_DATE_SHIFT_SQL))
        new_count = (await conn.execute(text("SELECT COUNT(*) FROM sales_historical"))).scalar()
        rng = (await conn.execute(text("SELECT MIN(date), MAX(date) FROM sales_historical"))).fetchone()

    logger.info(
        "Seeded %s historical rows (date range %s .. %s)", new_count, rng[0], rng[1]
    )
