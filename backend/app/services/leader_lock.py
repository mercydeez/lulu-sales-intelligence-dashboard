"""One Postgres advisory lock that serializes concurrent process startup.

WHY THIS EXISTS.
The backend now runs `gunicorn --workers N`: N OS processes each execute the ASGI
lifespan at boot. Several pieces of startup work are check-then-act against shared
Postgres objects — `run_migrations()` reads `schema_migrations` then applies files,
`run_seed()` counts `sales_historical` then COPYs ~900k rows, the employee seeder
reseeds. With N processes racing, this was PROVEN to produce:
  * 3 of 4 workers dying on `duplicate key ... pg_type_typname_nsp_index` from
    concurrent `CREATE TABLE` (a boot flap), and
  * up to N× the history loaded (no unique key on sales_historical rejects it).

THE PRIMITIVE, AND WHY IT IS THIS ONE.
`pg_advisory_lock` (SESSION-scoped), not `pg_advisory_xact_lock`. Verified against
live Postgres:
  * migration files embed literal `BEGIN; … COMMIT;` (001–004, 063). That inner
    COMMIT releases a *transaction*-scoped advisory lock mid-run — a session lock
    survives it.
  * a second acquirer blocks until the holder releases (correct serialization).
  * if the holder is SIGKILLed, Postgres releases the lock when the connection
    drops — no stuck lock, no manual cleanup.

The lock is held on a DEDICATED raw asyncpg connection, outside the SQLAlchemy
pool, because a pooled connection can be recycled underneath us (`pool_recycle`)
and silently drop the lock. `idle_session_timeout = 0` on that connection stops a
server-side idle reaper doing the same during a long backfill.

This makes concurrent BOOT safe. It is NOT the mechanism that keeps continuous
singletons (the generator, partition maintenance) single — those run in one
dedicated `singletons` container (`replicas: 1`), so there is exactly one by
deployment, not by election. See app/commands/singletons.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg

from app.config import get_settings, logger

# A fixed 64-bit key. Arbitrary but RESERVED: never reuse this integer for any
# other advisory lock in this codebase, or two unrelated call sites would block
# each other. Hard-coded (not derived at runtime) so it can never drift between
# processes — every booting worker must compute the identical key.
STARTUP_DDL_LOCK_KEY: int = 7413920115006677

_ACQUIRE_TIMEOUT_SECONDS = 120.0


def _plain_dsn(url: str) -> str:
    """asyncpg wants a libpq URI, not SQLAlchemy's +asyncpg scheme."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgres://"
    )


@asynccontextmanager
async def startup_lock(key: int = STARTUP_DDL_LOCK_KEY) -> AsyncIterator[None]:
    """Hold a session-level advisory lock for the duration of the block.

    Every process that boots enters here; exactly one proceeds at a time, the
    rest block until it exits, then re-evaluate their own idempotent guards
    (empty-checks, IF NOT EXISTS, ON CONFLICT) and no-op.

    Fails OPEN on a connection error: if we cannot reach Postgres to take the
    lock, the startup work behind it will fail loudly on its own, and blocking
    boot entirely on the lock connection would be worse. A warning is logged so
    the degradation is visible.
    """
    settings = get_settings()
    conn: Optional[asyncpg.Connection] = None
    acquired = False
    try:
        conn = await asyncpg.connect(_plain_dsn(settings.database_url), timeout=15)
        # Stop any idle reaper from dropping the lock-holding connection during a
        # long migration/backfill. Session-scoped; harmless on this throwaway conn.
        await conn.execute("SET idle_session_timeout = 0")
        await conn.execute("SET idle_in_transaction_session_timeout = 0")
        await conn.execute("SET statement_timeout = 0")

        # pg_advisory_lock blocks; bound the wait so a genuinely stuck holder
        # surfaces as an error instead of hanging boot forever.
        await conn.execute(
            f"SET lock_timeout = '{int(_ACQUIRE_TIMEOUT_SECONDS)}s'"
        )
        await conn.execute("SELECT pg_advisory_lock($1)", key)
        acquired = True
        logger.info("startup_lock: acquired (advisory key %s) — running startup DDL", key)
        yield
    except Exception as exc:
        if not acquired:
            # Could not take the lock at all. Fail open — proceed unserialized and
            # let the DDL's own guards do their best — but say so.
            logger.warning(
                f"startup_lock: could NOT acquire the advisory lock ({type(exc).__name__}: {exc}). "
                f"Proceeding WITHOUT startup serialization — relying on per-statement "
                f"idempotency guards. Safe for a single process; a concurrent boot may race."
            )
            yield
            return
        raise
    finally:
        if conn is not None:
            try:
                if acquired:
                    await conn.execute("SELECT pg_advisory_unlock($1)", key)
                    logger.info("startup_lock: released (advisory key %s)", key)
            except Exception:
                pass  # closing the connection releases it regardless
            await conn.close()
