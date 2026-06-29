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
from typing import Any, List, Optional

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


def _store_ids_guc(allowed_stores: Optional[List[int]]) -> str:
    """Render allowed_stores as a Postgres int-array literal for the
    app.allowed_store_ids GUC. Empty/None => '' which the view helper reads as
    'no restriction' (super_admin / every store in the tenant)."""
    if not allowed_stores:
        return ""
    ids = ",".join(str(int(s)) for s in allowed_stores)
    return "{" + ids + "}"


async def execute_sage_sql(sql: str, tenant_id: int,
                           allowed_stores: Optional[List[int]] = None) -> list[dict]:
    """Execute guard-approved SQL as sage_ro, scoped to `tenant_id` AND the
    caller's `allowed_stores`. Returns rows as dicts. Raises SageExecutionError on
    any failure (so the caller falls back).

    Store scoping is DB-enforced: the app.allowed_store_ids GUC drives the store
    filter baked into sage_sales / sage_stores (migration 040). An empty/None
    allowed_stores means no store restriction (super_admin), matching the
    app-layer get_accessible_store_ids convention."""
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
            # Store-level RBAC GUC (migration 040). Always set it (to '' when
            # unrestricted) so a value can never leak across NullPool connections.
            await conn.execute(
                text("SELECT set_config('app.allowed_store_ids', :sids, false)"),
                {"sids": _store_ids_guc(allowed_stores)},
            )
            result = await conn.execute(text(sql))
            # Guard allows only SELECT/WITH, which return rows. Defensively, if a
            # statement yields no result set, degrade to zero rows instead of letting
            # SQLAlchemy's ResourceClosedError ("does not return rows") leak into the
            # trace — the caller then narrates "no data" rather than an internal error.
            if not result.returns_rows:
                return []
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
