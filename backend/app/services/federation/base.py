"""
Federation core types (multi-source Sage).

Sage generates ONE query against the canonical sage_* schema; each registered
SOURCE executes that same canonical SQL via its own adapter and returns rows.
The orchestrator merges the per-source rows and narrates strictly from them.

Adapters are engine-specific (Postgres, MySQL, BigQuery, Snowflake, Mongo, REST,
bundled dataset) but all speak the same canonical contract, so adding an engine
never touches the orchestrator, guard, or prompt.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

# Coarse capability/maturity flag so the catalog can advertise what's live vs.
# scaffolded (drop-in, needs its service to verify).
ENGINES = ("postgres", "mysql", "bigquery", "snowflake", "mongo", "rest", "dataset")


@dataclass(frozen=True)
class SourceDescriptor:
    """Static metadata about a queryable source — drives the router + role policy."""
    id: str                      # 'internal' or f'ds:{data_source_id}'
    name: str                    # human label, shown in answers
    engine: str                  # one of ENGINES
    description: str             # one line; the router/LLM uses this to pick sources
    min_role: str = "consumer"   # least-privileged role allowed (see policy.ROLE_RANK)
    verified: bool = True        # False => built but not live-tested (no local service)


@dataclass
class SourceResult:
    """Outcome of running the canonical SQL against one source."""
    source_id: str
    source_name: str
    ok: bool
    rows: List[dict] = field(default_factory=list)
    error: Optional[str] = None


class SourceAdapter(ABC):
    """Executes canonical sage_* SQL against one physical source, read-only and
    tenant-scoped. Implementations MUST NOT mutate data and SHOULD enforce a
    statement timeout / row cap (the guard already caps rows)."""

    def __init__(self, descriptor: SourceDescriptor):
        self.descriptor = descriptor

    @abstractmethod
    async def run_canonical(self, canonical_sql: str, tenant_id: int,
                            allowed_stores: Optional[List[int]] = None) -> List[dict]:
        """Execute guard-approved canonical SQL and return rows as dicts.
        Raise on failure so the orchestrator records a per-source error and
        continues with the other sources.

        `allowed_stores` is the caller's accessible-store RBAC scope. The internal
        Postgres source enforces it (via the app.allowed_store_ids GUC); external
        sources synthesize their own sage_sales (store_id NULL) and have no
        internal store identity to scope by, so they accept and ignore it."""
        raise NotImplementedError
