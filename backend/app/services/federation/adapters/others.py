"""
Drop-in adapters for the non-Postgres engines (MySQL · BigQuery · Snowflake ·
MongoDB · REST/API · bundled dataset).

These are wired into the same canonical contract and registry as Postgres, so the
orchestrator treats them identically. They are intentionally *honest scaffolds*:
the structure + extension point is real, but they raise a clear, descriptive error
until their driver/service is enabled — rather than silently returning wrong data.
Enabling one is localized work (noted per engine below); no orchestrator change.

Implementation notes per engine:
  • mysql / bigquery / snowflake  → SQLAlchemy engine for the dialect; reuse the
    canonical-CTE idea from adapters/postgres.build_canonical_ctes but emit
    dialect-correct casts (MySQL has no `::` casts; BigQuery uses CAST/SAFE_CAST).
    Add the driver to requirements (aiomysql / sqlalchemy-bigquery / snowflake-
    sqlalchemy) and a read-only credential.
  • mongo  → translate the canonical query to an aggregation pipeline (motor),
    grouping by the mapped fields; return rows in the canonical shape.
  • rest   → fetch the canonical metrics from configured endpoints (httpx) and
    materialize them as canonical rows; good for partner/market data.
  • dataset→ load a bundled Parquet/CSV via DuckDB and run the canonical SQL
    directly (DuckDB speaks SQL), enabling cross-source joins in-process.
"""
from __future__ import annotations

from typing import List, Optional

from ..base import SourceAdapter, SourceDescriptor

_ENABLE_HINTS = {
    "mysql": "add aiomysql + a read-only DSN; emit MySQL-dialect canonical CTEs",
    "bigquery": "add sqlalchemy-bigquery + service-account creds; CAST() casts",
    "snowflake": "add snowflake-sqlalchemy + a read-only role",
    "mongo": "add motor; translate canonical query → aggregation pipeline",
    "rest": "add httpx endpoint config; materialize canonical rows",
    "dataset": "add duckdb; query the bundled Parquet/CSV directly",
}


class ScaffoldedAdapter(SourceAdapter):
    """Registers and routes like any source, but reports that its engine still
    needs its driver/service enabled for this build."""

    def __init__(self, descriptor: SourceDescriptor, connection: str, mapping: dict, timeout_ms: int):
        super().__init__(descriptor)
        self._connection = connection
        self._mapping = mapping
        self._timeout_ms = timeout_ms

    async def run_canonical(self, canonical_sql: str, tenant_id: int,
                            allowed_stores: Optional[List[int]] = None) -> List[dict]:
        hint = _ENABLE_HINTS.get(self.descriptor.engine, "implement run_canonical")
        raise NotImplementedError(
            f"{self.descriptor.engine} adapter is scaffolded (not enabled in this build) — {hint}"
        )


def build_other_engine_adapter(descriptor: SourceDescriptor, connection: str,
                               mapping: dict, timeout_ms: int) -> SourceAdapter:
    # All non-Postgres engines share the scaffold today; each becomes a real
    # adapter by implementing run_canonical per the notes above.
    return ScaffoldedAdapter(descriptor, connection, mapping, timeout_ms)
