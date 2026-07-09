"""
Source registry for federated Sage. Resolves the set of sources a (role, tenant)
may query and builds their adapters.

* The internal app DB is always present (tenant-scoped, consumer-visible).
* Connected `data_sources` (status ok) are exposed to admins only — until those
  rows are tenant-scoped, a connected client DB is an admin-level source so a
  consumer can never reach another tenant's external data.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import text

from app.config import get_settings, logger
from app.services.database import async_session
from app.services.data_sources import decrypt
from . import policy
from .base import SourceAdapter, SourceDescriptor

INTERNAL = SourceDescriptor(
    id="internal",
    name=get_settings().product_name,
    engine="postgres",
    description="The platform's own live sales, inventory and forecast data for this tenant.",
    min_role="consumer",
    verified=True,
)

# Connected external sources are admin-visible (see module docstring).
_EXTERNAL_MIN_ROLE = "admin"


async def _fetch_source_row(source_id: int) -> Optional[dict]:
    async with async_session() as s:
        row = (await s.execute(text(
            "SELECT id, name, type, mapping, connection_enc, status "
            "FROM data_sources WHERE id = :id"
        ), {"id": source_id})).fetchone()
    if not row:
        return None
    return {
        "id": row.id, "name": row.name, "type": row.type,
        "mapping": row.mapping or {}, "connection_enc": row.connection_enc,
        "status": row.status,
    }


async def list_descriptors(role: str) -> List[SourceDescriptor]:
    """All sources visible to `role`, internal first."""
    out: List[SourceDescriptor] = []
    if policy.can_use_source(role, INTERNAL):
        out.append(INTERNAL)
    if policy.rank(role) < policy.rank(_EXTERNAL_MIN_ROLE):
        return out  # consumers / store / regional only see the internal source
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT id, name, type, status FROM data_sources "
            "WHERE type <> 'builtin' AND status = 'ok' ORDER BY id"
        ))).fetchall()
    for r in rows:
        out.append(SourceDescriptor(
            id=f"ds:{r.id}",
            name=r.name,
            engine=r.type,
            description=f"Connected {r.type} source '{r.name}'.",
            min_role=_EXTERNAL_MIN_ROLE,
            # Only postgres is live-verified here; other engines are drop-in.
            verified=(r.type == "postgres"),
        ))
    return out


async def build_adapter(descriptor: SourceDescriptor, timeout_ms: int = 5000) -> SourceAdapter:
    """Instantiate the adapter for a descriptor (decrypting creds server-side)."""
    from .adapters.postgres import InternalPostgresAdapter, ExternalPostgresAdapter

    if descriptor.id == "internal":
        return InternalPostgresAdapter(descriptor)

    source_id = int(descriptor.id.split(":", 1)[1])
    row = await _fetch_source_row(source_id)
    if not row or not row.get("connection_enc"):
        raise ValueError(f"source {descriptor.id} has no usable connection")
    connection = decrypt(row["connection_enc"])
    mapping = row["mapping"]

    engine = descriptor.engine
    if engine == "postgres":
        return ExternalPostgresAdapter(descriptor, connection, mapping, timeout_ms)

    # Other engines (mysql/bigquery/snowflake/mongo/rest/dataset) — drop-in adapters.
    from .adapters.others import build_other_engine_adapter
    return build_other_engine_adapter(descriptor, connection, mapping, timeout_ms)


async def resolve_adapters(role: str, source_ids: Optional[List[str]] = None
                           ) -> Tuple[List[SourceAdapter], List[str]]:
    """Build adapters for the role's visible sources (optionally filtered to
    `source_ids`). Returns (adapters, errors) — a source that can't be built is
    skipped with a recorded error, never failing the whole request."""
    descriptors = await list_descriptors(role)
    if source_ids:
        wanted = set(source_ids)
        descriptors = [d for d in descriptors if d.id in wanted]
    adapters: List[SourceAdapter] = []
    errors: List[str] = []
    for d in descriptors:
        try:
            adapters.append(await build_adapter(d))
        except Exception as e:
            logger.warning(f"Federation: could not build adapter {d.id}: {e}")
            errors.append(f"{d.name}: {e}")
    return adapters, errors
