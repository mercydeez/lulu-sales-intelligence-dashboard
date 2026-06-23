"""
Sage v2 orchestrator: decompose → route → recompose.

A multi-part business question is split into sub-questions; each is answered
independently and GROUNDED (NL→SQL over the sage_* layer through the allow-list
guard + sage_ro, document RAG, or an API call); the sub-answers are recomposed
into one source-attributed table. Nothing is invented — every cell traces to a
returned row / retrieved chunk.

Two decomposition paths:
  • LLM (when a provider is configured): free-form decompose + per-sub NL→SQL.
  • Deterministic (no LLM): keyword intents → curated template SQL (intents.py).
The deterministic path makes the flagship multi-part question answerable today and
is the test oracle; the LLM path generalizes it. Both share the guard + executor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.llm import LLMError, get_provider_chain
from app.services.nl2sql.guard import SqlGuardError, validate_sql
from app.services.nl2sql.executor import SageExecutionError, execute_sage_sql
from app.services.nl2sql.pipeline import _generate_sql
from . import intents as I
from .decompose import llm_decompose

logger = logging.getLogger(__name__)

MAX_ROWS = 200


@dataclass
class SubAnswer:
    label: str
    ok: bool
    rows: List[dict] = field(default_factory=list)
    sql: Optional[str] = None
    error: Optional[str] = None
    source: str = "Retail IQ"   # domain/source attribution


@dataclass
class MultiPartResult:
    ok: bool
    answer: str = ""
    parts: List[SubAnswer] = field(default_factory=list)
    used_llm: bool = False
    reason: str = ""


def _num(v):
    """Format a number with thousands separators, dropping a trailing .0."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, (int, float)) else str(v)


def _format_value(rows: List[dict]) -> str:
    """Render a sub-answer's rows for the recomposed table — rows-only, no invention."""
    if not rows:
        return "_no data_"
    if len(rows) == 1:
        cells = list(rows[0].values())
        if len(cells) == 1:
            return _num(cells[0])
        # multi-column single row, e.g. target: value/unit
        return " ".join(_num(v) for v in cells)
    # list answer: join the first column across rows
    key = next(iter(rows[0].keys()))
    vals = [str(r.get(key, "")) for r in rows]
    return ", ".join(vals)


def _recompose(parts: List[SubAnswer]) -> str:
    lines = ["Here's the breakdown:", "", "| Metric | Value | Source |", "|---|---|---|"]
    for p in parts:
        val = _format_value(p.rows) if p.ok else f"_error: {p.error}_"
        lines.append(f"| {p.label} | {val} | {p.source} |")
    return "\n".join(lines)


async def _run_sql(label: str, sql: str, tenant_id: int) -> SubAnswer:
    try:
        safe = validate_sql(sql, MAX_ROWS)
    except SqlGuardError as e:
        return SubAnswer(label, False, sql=sql, error=f"guard: {e}")
    try:
        rows = await execute_sage_sql(safe, tenant_id)
        return SubAnswer(label, True, rows=rows, sql=safe)
    except SageExecutionError as e:
        return SubAnswer(label, False, sql=safe, error=str(e))


async def _deterministic(question: str, tenant_id: int) -> List[SubAnswer]:
    zone = I.extract_zone(question)
    parts: List[SubAnswer] = []
    for intent in I.match_intents(question):
        label = intent.label
        if intent.zone_aware and zone:
            label = f"{intent.label} ({zone})"
        parts.append(await _run_sql(label, intent.build_sql(zone), tenant_id))
    return parts


async def _llm(question: str, tenant_id: int, providers) -> List[SubAnswer]:
    """LLM decompose → per-sub NL→SQL (guarded). Empty list signals 'fall back'."""
    subs = await llm_decompose(question, providers)
    if not subs:
        return []
    parts: List[SubAnswer] = []
    for sub in subs:
        sql = await _generate_sql(sub, providers)
        if not sql:
            parts.append(SubAnswer(sub, False, error="no SQL generated"))
            continue
        parts.append(await _run_sql(sub, sql, tenant_id))
    return parts


def is_multipart(question: str) -> bool:
    """Engage Sage v2 only for genuinely multi-part questions; single asks stay on
    the (cheaper) federated Sage path."""
    q = question.lower()
    if len(I.match_intents(question)) >= 2:
        return True
    # crude conjunction/comma heuristic for the LLM path
    return q.count(",") >= 2 or q.count(" and ") >= 2


async def answer_multipart(question: str, tenant_id: int, role: str = "admin",
                           providers=None) -> MultiPartResult:
    """Decompose → answer each sub → recompose. Never raises."""
    providers = providers if providers is not None else get_provider_chain()

    parts: List[SubAnswer] = []
    used_llm = False
    if providers:
        try:
            parts = await _llm(question, tenant_id, providers)
            used_llm = bool(parts)
        except LLMError:
            parts = []
    if not parts:
        parts = await _deterministic(question, tenant_id)

    if not parts:
        return MultiPartResult(ok=False, reason="no recognized sub-questions")
    if not any(p.ok for p in parts):
        return MultiPartResult(ok=False, parts=parts, reason="all sub-questions failed")

    return MultiPartResult(ok=True, answer=_recompose(parts), parts=parts, used_llm=used_llm)
