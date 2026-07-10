from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from typing import AsyncGenerator, Optional
from contextvars import ContextVar
import asyncio
import logging
from fastapi import Request, Depends
from app.config import get_settings
from app.models.sales import Base

# Per-request active tenant (B2). Set by get_current_user when a JWT is decoded;
# applied to the request's DB connection as the `app.tenant_id` GUC so the
# Postgres RLS policies (migration 012) bind to the right tenant. This is the
# defense-in-depth backstop UNDER the primary app-layer tenant scoping.
tenant_context: ContextVar[int] = ContextVar("tenant_id", default=1)


async def apply_tenant_guc(session: AsyncSession) -> None:
    """Bind the active tenant to this connection for RLS. Best-effort: never
    fail a request if the GUC can't be set (e.g. the function isn't installed
    yet on an un-migrated DB)."""
    try:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"),
            {"tid": str(tenant_context.get())},
        )
    except Exception:
        pass

settings = get_settings()
logger = logging.getLogger(__name__)


async def exempt_statement_timeout(conn_or_session) -> None:
    """Lift the engine-default statement_timeout (E6-4) for the CURRENT
    transaction only. SET LOCAL resets on commit/rollback, so the exemption can
    never leak back into the connection pool. Only for known long operations —
    migrations, CSV seed, bulk ingest, forecast fetch, demo reset — never a
    request handler."""
    await conn_or_session.execute(text("SET LOCAL statement_timeout = 0"))

# Optimized connection pooling for production.
# NullPool (testing) rejects pool sizing kwargs, so only pass them when pooling.
_engine_kwargs = {
    "pool_pre_ping": True,  # Test connections before use
    "echo": False,          # Disable SQL logging in production for speed
}
if settings.environment == "testing":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        poolclass=AsyncAdaptedQueuePool,
        # Sized DOWN from 20/30 because the pool is per-process: with
        # `gunicorn --workers N` the old defaults meant N×50 connections, blowing
        # past Postgres max_connections. Config-driven so ops tunes it with the
        # worker count (see config.web_concurrency / db_pool_size / db_max_overflow).
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,   # Recycle connections after 30 minutes
        pool_timeout=30,     # Wait up to 30 seconds for connection
    )

# E6-4: every connection carries a default statement_timeout, so no endpoint can
# hold a connection on one runaway query — routes reach the DB via get_db OR via
# async_session() directly (analytics/reports/promotions/...), and only a
# connect-time default covers both. asyncpg applies server_settings at connect,
# so pooled connections inherit it and SET LOCAL exemptions (transaction-scoped)
# can never leak back into the pool. Known long operations (migration_runner,
# db_seeder COPY, ingest/bulk, forecast_trainer fetch, demo_reset) opt out with
# SET LOCAL statement_timeout = 0 inside their own transactions.
if settings.db_statement_timeout_ms > 0:
    _engine_kwargs["connect_args"] = {
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "application_name": "retail_intelligence_api",
        }
    }

engine = create_async_engine(settings.database_url, **_engine_kwargs)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


def _derive_rls_url() -> str:
    """The app_rw (non-owner) connection string. Use the explicit setting if
    given, else swap the superuser creds in database_url for app_rw's."""
    if settings.rls_database_url:
        return settings.rls_database_url
    url = settings.database_url
    # postgresql+asyncpg://<user>:<pass>@host... -> app_rw creds
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        _creds, host = rest.split("@", 1)
        return f"{scheme}://app_rw:app_rw_dev_pass@{host}"
    return url


# Optional non-owner engine used by the REQUEST path when RLS enforcement is on.
# Owner-path code (startup, migrations, generator, background warmers) keeps
# using `async_session` so it can do cross-tenant work (the superuser bypasses
# RLS by design). When the flag is off, request_session IS async_session.
if settings.use_rls_role:
    rls_engine = create_async_engine(_derive_rls_url(), **_engine_kwargs)
    rls_session = async_sessionmaker(
        rls_engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )
    logger.info("🔒 RLS enforcement ON — request path connects as non-owner role app_rw")
else:
    rls_engine = None
    rls_session = async_session


async def init_db(max_retries: int = 30, retry_delay: float = 3.0):
    """Initialize database connection with retry logic"""
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                # Test the connection
                await conn.execute(text("SELECT 1"))
                logger.info("Database connection established successfully")
                return
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts")
                raise


async def close_db():
    """Close database connections — owner engine, the RLS engine and the read
    replica engine, each if it exists."""
    await engine.dispose()
    if rls_engine is not None:
        await rls_engine.dispose()
    # Defined below; guarded because close_db can run before it is bound if
    # startup failed early.
    if globals().get("replica_engine") is not None:
        await replica_engine.dispose()


async def resolve_request_tenant(request: Request) -> int:
    """Bind the request's tenant to `tenant_context` BEFORE get_db opens its
    session, so the RLS GUC (apply_tenant_guc) is correct regardless of the order
    in which FastAPI resolves a route's dependencies (routes commonly declare
    `db=Depends(get_db)` before `current_user`, which would otherwise apply the
    GUC with the default tenant).

    This does NOT authenticate — the route's own get_current_user / get_api_context
    dependency still enforces auth and returns 401 on a bad token/key. It only
    resolves the tenant for connection scoping, failing safe to tenant 1.

    Resolution order: JWT `tenant_id` claim (no DB hit) → API key (looked up on the
    OWNER session so the cross-tenant key→tenant lookup isn't itself RLS-filtered)
    → SSE stream ticket. Lazy imports avoid a circular import with auth_service.
    """
    tenant_id = 1
    try:
        from app.services.auth_service import decode_token
        from app.services import api_key_service

        auth = request.headers.get("authorization", "")
        bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else None
        api_key = request.headers.get("x-api-key") or (
            bearer if bearer and bearer.startswith(f"{api_key_service.KEY_LABEL}_") else None
        )

        if api_key:
            async with async_session() as s:  # owner session: not RLS-filtered
                resolved = await api_key_service.tenant_for_key(s, api_key)
                if resolved:
                    tenant_id = resolved
        elif bearer:
            td = decode_token(bearer)  # access-typed; returns None otherwise
            if td and td.tenant_id:
                tenant_id = td.tenant_id
        else:
            ticket = request.query_params.get("ticket")
            if ticket:
                td = decode_token(ticket)
                if td and td.tenant_id:
                    tenant_id = td.tenant_id
    except Exception:
        pass  # fail safe to tenant 1; auth dependency still guards the route

    tenant_context.set(tenant_id)
    return tenant_id


async def get_db(
    _tenant: int = Depends(resolve_request_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped DB session. Uses the non-owner app_rw engine when RLS
    enforcement is enabled (settings.use_rls_role), so Postgres FORCE RLS scopes
    every query to the caller's tenant; otherwise the (superuser) owner engine.

    Depends on resolve_request_tenant so `tenant_context` (and thus the RLS GUC
    applied below) reflects the authenticated tenant before any query runs."""
    async with rls_session() as session:
        try:
            await apply_tenant_guc(session)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# E10-7 — read-replica routing.
#
# A replica is BEHIND the primary. That is not a detail, it is the contract: any
# endpoint that reads what the same request (or the user's last click) just wrote
# can return stale data from a replica, and the user sees their own write vanish.
#
# So `get_read_db` is opt-in per route, and only for reads that tolerate lag:
# analytics, reports, history — aggregates over days of data, where a few hundred
# milliseconds of replication delay is invisible. Never for a read-after-write,
# never for auth, never for anything a mutation returns.
#
# With DATABASE_REPLICA_URL unset, `read_session` IS `rls_session`, so the
# dependency is a no-op and every route behaves exactly as before. Nothing here
# is dormant: the routing is live, it simply has one node to route to.
# ---------------------------------------------------------------------------

def _derive_replica_url(raw: str) -> str:
    """Accept a plain postgres:// URL and force the asyncpg driver, as with the
    primary. A replica misconfigured onto psycopg2 would fail at first query."""
    if raw.startswith("postgresql+asyncpg://") or raw.startswith("postgres+asyncpg://"):
        return raw
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+asyncpg://" + raw[len(prefix):]
    return raw


if settings.database_replica_url:
    replica_engine = create_async_engine(
        _derive_replica_url(settings.database_replica_url), **_engine_kwargs
    )
    read_session = async_sessionmaker(
        replica_engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )
    logger.info("📖 Read replica configured — lag-tolerant reads routed to DATABASE_REPLICA_URL")
else:
    replica_engine = None
    read_session = rls_session


def replica_configured() -> bool:
    return replica_engine is not None


async def get_read_db(
    _tenant: int = Depends(resolve_request_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    """A session for reads that tolerate replication lag.

    Never commits: a replica is read-only, and a route that writes through this
    dependency is a bug we would rather surface as an error than silently apply
    to the primary. Rolls back on exit so no transaction is left open.
    """
    async with read_session() as session:
        try:
            await apply_tenant_guc(session)
            yield session
        finally:
            # Read-only: discard the (empty) transaction rather than commit it.
            await session.rollback()
            await session.close()
