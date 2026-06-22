"""
Read-only, tenant-scoped executor for Sage's validated SQL (A2).

Runs the guard-approved SELECT as the least-privilege `sage_ro` role (migration
023): SELECT only on the tenant-filtered sage_* views, nothing else. Per query it
sets a statement timeout and the `app.tenant_id` GUC the views filter on, so the
result is scoped to the caller's tenant by the database itself — not by trusting
the generated SQL.
"""
from __future__ import annotations

import datetime
import decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_sage_engine: Optional[AsyncEngine] = None


class SageExecutionError(Exception):
    """Raised when Sage's SQL cannot be executed (bad SQL, timeout, no role)."""


def _derive_sage_url() -> str:
    """sage_ro connection string: explicit setting, else database_url with sage_ro creds."""
    settings = get_settings()
    if settings.sage_database_url:
        return settings.sage_database_url
    url = settings.database_url
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        _creds, host = rest.split("@", 1)
        return f"{scheme}://sage_ro:sage_ro_dev_pass@{host}"
    return url


def get_sage_engine() -> AsyncEngine:
    """Lazily build the sage_ro engine. NullPool: low-volume, short-lived
    connections so session-scoped SETs never leak between queries."""
    global _sage_engine
    if _sage_engine is None:
        _sage_engine = create_async_engine(
            _derive_sage_url(), poolclass=NullPool, pool_pre_ping=True, echo=False
        )
    return _sage_engine


def _coerce(value: Any) -> Any:
    """JSON-friendly cell values for narration/serialization."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


async def execute_sage_sql(sql: str, tenant_id: int) -> list[dict]:
    """Execute guard-approved SQL as sage_ro, scoped to `tenant_id`. Returns rows
    as dicts. Raises SageExecutionError on any failure (so the caller falls back)."""
    engine = get_sage_engine()
    try:
        async with engine.connect() as conn:
            # Per-connection (NullPool => per-query) settings. set_config takes bind
            # params safely, unlike a bare SET.
            await conn.execute(
                text("SELECT set_config('statement_timeout', :t, false)"),
                {"t": str(int(get_settings().sage_query_timeout_ms))},
            )
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, false)"),
                {"tid": str(int(tenant_id))},
            )
            result = await conn.execute(text(sql))
            rows = [{k: _coerce(v) for k, v in m.items()} for m in result.mappings().all()]
            # SELECT-only; nothing to commit. Let the context manager close/rollback.
            return rows
    except Exception as e:  # asyncpg errors, timeouts, permission denied
        raise SageExecutionError(str(e)) from e


async def dispose_sage_engine() -> None:
    global _sage_engine
    if _sage_engine is not None:
        await _sage_engine.dispose()
        _sage_engine = None
