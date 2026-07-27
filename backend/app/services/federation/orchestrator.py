"""
Federated Sage orchestrator.

    question --(LLM)--> ONE canonical SQL --(guard)--> safe SQL
            --> run on each visible source (role-scoped) --> merge rows (source-tagged)
            --> narrate strictly from rows, attribute every figure, flag discrepancies

Fails closed at every step: no LLM, blocked SQL, or zero usable sources => ok=False
so the caller falls back to single-source Sage / the rule-based responder. The LLM
only ever proposes SQL and phrases an answer from returned rows — never accesses data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.llm import LLMError, get_provider_chain
from app.services.nl2sql.guard import SqlGuardError, validate_sql
from app.services.nl2sql.pipeline import _generate_sql, _narrate
from . import catalog, policy
from .base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


@dataclass
class FederatedResult:
    ok: bool
    answer: str = ""
    sql: Optional[str] = None
    sources: List[SourceResult] = field(default_factory=list)
    reason: str = ""


async def _run_on_sources(adapters: List[SourceAdapter], sql: str, tenant_id: int,
                          allowed_stores: Optional[List[int]] = None) -> List[SourceResult]:
    results: List[SourceResult] = []
    for a in adapters:
        try:
            rows = await a.run_canonical(sql, tenant_id, allowed_stores)
            results.append(SourceResult(a.descriptor.id, a.descriptor.name, True, rows))
        except Exception as e:
            logger.info(f"Federation: source {a.descriptor.id} failed: {e}")
            results.append(SourceResult(a.descriptor.id, a.descriptor.name, False, error=str(e)[:300]))
    return results


def _scalar(rows: List[dict]):
    """If rows is a single 1-column row, return that value, else None."""
    if len(rows) == 1 and len(rows[0]) == 1:
        return next(iter(rows[0].values()))
    return None


def detect_discrepancy(results: List[SourceResult]) -> Optional[str]:
    """When ≥2 sources return the same single headline number, flag if they
    disagree materially — a genuine cross-system data-quality signal."""
    scalars = [(r.source_name, _scalar(r.rows)) for r in results if r.ok and _scalar(r.rows) is not None]
    nums = [(n, float(v)) for n, v in scalars if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None
    lo = min(v for _, v in nums)
    hi = max(v for _, v in nums)
    if lo > 0 and (hi - lo) / lo > 0.05:
        parts = ", ".join(f"{n}: {v:,.0f}" for n, v in nums)
        return f"⚠️ Sources disagree by {((hi - lo) / lo) * 100:.0f}% — {parts}. Worth reconciling."
    return None


def narrate_federated(results: List[SourceResult]) -> str:
    """Deterministic, rows-only multi-source answer (used when no LLM narrates)."""
    ok = [r for r in results if r.ok]
    if not ok:
        errs = "; ".join(f"{r.source_name}: {r.error}" for r in results) or "no sources"
        return f"I couldn't get an answer from any source ({errs})."

    lines: List[str] = []
    disc = detect_discrepancy(ok)
    if disc:
        lines.append(disc)
    for r in ok:
        if not r.rows:
            lines.append(f"• {r.source_name}: no matching data.")
            continue
        sv = _scalar(r.rows)
        if sv is not None:
            key = next(iter(r.rows[0].keys())).replace("_", " ")
            lines.append(f"• {r.source_name} — {key}: {sv}")
        else:
            cols = list(r.rows[0].keys())
            preview = r.rows[:5]
            tbl = "\n".join("   " + " | ".join(str(row.get(c, "")) for c in cols) for row in preview)
            more = f"\n   …+{len(r.rows) - len(preview)} more" if len(r.rows) > len(preview) else ""
            lines.append(f"• {r.source_name} ({' | '.join(cols)}):\n{tbl}{more}")
    return "\n".join(lines)


async def federated_answer(
    question: str,
    tenant_id: int,
    role: str,
    source_ids: Optional[List[str]] = None,
    providers=None,
    allowed_stores: Optional[List[int]] = None,
) -> FederatedResult:
    """Answer `question` across every source `role` may query. Never raises.

    `allowed_stores` is the caller's accessible-store RBAC scope; it is enforced
    on the internal Postgres source via the app.allowed_store_ids GUC (migration
    040). Empty/None => super_admin / all stores in the tenant."""
    providers = providers if providers is not None else get_provider_chain()
    adapters, build_errors = await catalog.resolve_adapters(role, source_ids)
    if not adapters:
        return FederatedResult(ok=False, reason="no usable sources")

    # Single-source callers (consumers, or only the internal source visible) take
    # the simpler Sage path upstream — federation adds value with ≥2 sources.
    if len(adapters) == 1 or not policy.allow_cross_source_merge(role):
        adapters = adapters[:1]

    if not providers:
        return FederatedResult(ok=False, reason="no LLM provider configured")

    sql = await _generate_sql(question, providers)
    if not sql:
        return FederatedResult(ok=False, reason="LLM produced no SQL")
    try:
        safe_sql = validate_sql(sql, policy.max_rows_for(role))
    except SqlGuardError as e:
        return FederatedResult(ok=False, sql=sql, reason=f"guard: {e}")

    results = await _run_on_sources(adapters, safe_sql, tenant_id, allowed_stores)
    if not any(r.ok for r in results):
        return FederatedResult(ok=False, sql=safe_sql, sources=results, reason="all sources errored")

    # Narrate: prefer the LLM over the merged, source-tagged rows; else deterministic.
    merged = []
    for r in results:
        for row in (r.rows or []):
            merged.append({"_source": r.source_name, **row})
    answer = await _narrate(question, merged, providers) if merged else narrate_federated(results)
    disc = detect_discrepancy([r for r in results if r.ok])
    if disc and disc not in answer:
        answer = f"{disc}\n\n{answer}"

    return FederatedResult(ok=True, answer=answer, sql=safe_sql, sources=results)
