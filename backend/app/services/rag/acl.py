"""
RBAC-aware retrieval filter (RAG-5) — the security boundary for Sage retrieval.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §3.

Turns a caller's grants (tenant_id, role, allowed_stores — exactly what
sage3 AgentState already carries from the JWT) into a **hard, parameterized
SQL WHERE fragment** applied to BOTH retrieval arms (vector + FTS) BEFORE
scoring — never post-filter (post-filtering leaks: the LLM/reranker would still
see forbidden text). Also derives a stable `filter_hash` so the semantic cache
(GR-5) can be scoped per authorization — a manager and an admin asking the same
question must never share a cached answer.

Pure and importable; no DB, no app deps at import. The SQL it emits matches the
canonical filter documented in migration 055 and verified there.

Design notes / invariants:
  • `allowed_stores == []` means NO store restriction (super_admin / all stores),
    per AgentState's contract — NOT "sees nothing".
  • sensitivity ladder is role-derived and conservative (deny by default).
  • tenant_id is ALWAYS filtered here AND enforced by RLS (defense in depth).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# Which content sensitivities each role may retrieve when a chunk does NOT pin an
# explicit visibility_roles list. Deny-by-default: unknown roles get the floor.
_SENSITIVITY_LADDER: Dict[str, List[str]] = {
    "super_admin":      ["public", "internal", "restricted"],
    "admin":            ["public", "internal", "restricted"],
    "regional_manager": ["public", "internal", "restricted"],
    "store_manager":    ["public", "internal"],
    "analyst":          ["public", "internal"],
}
_FLOOR = ["public"]  # anything not recognized sees only public


def allowed_sensitivities(role: Optional[str]) -> List[str]:
    return _SENSITIVITY_LADDER.get((role or "").lower(), _FLOOR)


@dataclass(frozen=True)
class AclFilter:
    """A parameterized WHERE fragment + binds + a stable authorization hash."""
    where_sql: str
    params: Dict[str, object]
    filter_hash: str  # stable across identical authorizations; for cache scoping

    def cache_scope(self) -> str:
        return self.filter_hash


def build_acl_filter(
    tenant_id: int,
    role: Optional[str],
    allowed_stores: Optional[Sequence[int]],
    *,
    alias: str = "d",
    param_prefix: str = "acl",
) -> AclFilter:
    """Build the retrieval ACL filter for a caller.

    Args:
        tenant_id: caller's tenant (hard scope).
        role: caller's role (drives the sensitivity ladder).
        allowed_stores: caller's accessible store ids; **empty/None = no store
            restriction** (super_admin/all).
        alias: table alias the fragment references (default 'd').
        param_prefix: bind-parameter name prefix (avoid collisions).

    Returns:
        AclFilter with `.where_sql` (AND-joined, no leading AND), `.params`, and
        `.filter_hash`.
    """
    a = alias
    p = param_prefix
    sens = allowed_sensitivities(role)
    stores = list(allowed_stores or [])

    clauses: List[str] = []
    params: Dict[str, object] = {}

    # 1. tenant (also RLS-enforced; belt and suspenders).
    clauses.append(f"{a}.tenant_id = :{p}_tid")
    params[f"{p}_tid"] = int(tenant_id)

    # 2. visibility: public OR role explicitly listed OR (no explicit list AND
    #    the chunk's sensitivity is within the role's ladder).
    clauses.append(
        f"({a}.sensitivity = 'public'"
        f" OR :{p}_role = ANY({a}.visibility_roles)"
        f" OR (COALESCE(cardinality({a}.visibility_roles), 0) = 0"
        f"     AND {a}.sensitivity = ANY(:{p}_sens)))"
    )
    params[f"{p}_role"] = (role or "").lower()
    params[f"{p}_sens"] = sens

    # 3. store scope: null/empty scope = tenant-wide; else must overlap the
    #    caller's stores. Empty allowed_stores = no restriction (skip clause).
    if stores:
        clauses.append(
            f"({a}.store_scope IS NULL"
            f" OR cardinality({a}.store_scope) = 0"
            f" OR {a}.store_scope && :{p}_stores)"
        )
        params[f"{p}_stores"] = stores

    where_sql = " AND ".join(clauses)

    # Stable authorization hash for cache scoping: identical (tenant, role,
    # sensitivity set, store set) => identical hash. Order-independent for stores.
    scope_repr = json.dumps(
        {
            "t": int(tenant_id),
            "r": (role or "").lower(),
            "s": sens,
            "st": sorted(int(x) for x in stores),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    filter_hash = hashlib.blake2b(scope_repr.encode("utf-8"), digest_size=16).hexdigest()

    return AclFilter(where_sql=where_sql, params=params, filter_hash=filter_hash)
