from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from typing import AsyncGenerator
from contextvars import ContextVar
import asyncio
import logging
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
        pool_size=20,        # Base number of connections
        max_overflow=30,     # Additional connections when pool is exhausted
        pool_recycle=1800,   # Recycle connections after 30 minutes
        pool_timeout=30,     # Wait up to 30 seconds for connection
    )

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
    """Close database connection"""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped DB session. Uses the non-owner app_rw engine when RLS
    enforcement is enabled (settings.use_rls_role), so Postgres FORCE RLS scopes
    every query to the caller's tenant; otherwise the (superuser) owner engine."""
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
