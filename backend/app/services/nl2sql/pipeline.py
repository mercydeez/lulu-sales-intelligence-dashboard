"""
Sage NL->SQL pipeline orchestration (A2).

    question --(LLM)--> SQL --(guard)--> safe SQL --(sage_ro)--> rows --(LLM)--> answer

Every step can fail closed: no LLM provider, an unparseable/blocked query, an
execution error, or a narration failure each yield a result the caller can fall
back on (the rule-based responder). The LLM is only ever trusted to *propose*
SQL and to *phrase* an answer from rows it's handed — never to access data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import get_settings
from app.services.llm import LLMError, LLMProvider, get_provider_chain

from .executor import SageExecutionError, execute_sage_sql
from .guard import SqlGuardError, validate_sql
from .prompt import (
    build_narration_messages, build_repair_messages, build_sql_messages, extract_sql,
)

logger = logging.getLogger(__name__)


@dataclass
class SageResult:
    ok: bool
    answer: str = ""
    sql: Optional[str] = None
    rows: List[dict] = field(default_factory=list)
    reason: str = ""  # why it failed / fell back (for logs + debugging)


async def _generate_sql(
    question: str, providers: List[LLMProvider],
    failed_sql: Optional[str] = None, error: Optional[str] = None,
) -> Optional[str]:
    messages = (build_sql_messages(question) if failed_sql is None
                else build_repair_messages(question, failed_sql, error or ""))
    for provider in providers:
        try:
            raw = await provider.complete(messages)
            sql = extract_sql(raw)
            if sql:
                return sql
        except LLMError:
            continue
    return None


async def _narrate(question: str, rows: List[dict], providers: List[LLMProvider]) -> str:
    for provider in providers:
        try:
            answer = await provider.complete(build_narration_messages(question, rows))
            if answer and answer.strip():
                return answer.strip()
        except LLMError:
            continue
    return deterministic_answer(rows)


def deterministic_answer(rows: List[dict]) -> str:
    """A safe, rows-only answer when no LLM can narrate — never invents anything."""
    if not rows:
        return "I found no matching data for that question."
    if len(rows) == 1 and len(rows[0]) == 1:
        (key, val), = rows[0].items()
        return f"{key.replace('_', ' ')}: {val}"
    # Render a compact preview table from the first few rows.
    cols = list(rows[0].keys())
    preview = rows[:10]
    lines = [" | ".join(cols)]
    for r in preview:
        lines.append(" | ".join(str(r.get(c, "")) for c in cols))
    more = f"\n…and {len(rows) - len(preview)} more row(s)." if len(rows) > len(preview) else ""
    return "Here is what I found:\n" + "\n".join(lines) + more


async def answer_question(
    question: str,
    tenant_id: int,
    providers: Optional[List[LLMProvider]] = None,
    allowed_stores: Optional[List[int]] = None,
) -> SageResult:
    """Run the full NL->SQL->narrate pipeline. Never raises; returns SageResult.

    `allowed_stores` is the caller's accessible-store RBAC scope (empty/None =>
    super_admin / all stores in the tenant). It is DB-enforced via the
    app.allowed_store_ids GUC (migration 040) — see execute_sage_sql."""
    settings = get_settings()
    if not settings.sage_enabled:
        return SageResult(ok=False, reason="sage disabled")

    providers = providers if providers is not None else get_provider_chain()
    if not providers:
        # No LLM configured yet (the prototype state). Caller uses rule-based fallback.
        return SageResult(ok=False, reason="no LLM provider configured")

    sql = await _generate_sql(question, providers)
    if not sql:
        return SageResult(ok=False, reason="LLM produced no SQL")

    # Two attempts total: the original SQL, then one self-repair with the
    # guard/DB error fed back — most schema mistakes (wrong column, wrong view)
    # are fixable, and giving up on attempt one meant a real question always fell
    # through to the generic rule-based template.
    for attempt in range(2):
        try:
            safe_sql = validate_sql(sql, settings.sage_max_rows)
        except SqlGuardError as e:
            logger.info(f"Sage guard rejected SQL: {e} | sql={sql!r}")
            if attempt == 0:
                sql = await _generate_sql(question, providers, failed_sql=sql, error=f"guard: {e}")
                if sql:
                    continue
            return SageResult(ok=False, sql=sql, reason=f"guard: {e}")

        try:
            rows = await execute_sage_sql(safe_sql, tenant_id, allowed_stores)
        except SageExecutionError as e:
            logger.info(f"Sage execution failed: {e}")
            if attempt == 0:
                sql = await _generate_sql(question, providers, failed_sql=safe_sql, error=str(e))
                if sql:
                    continue
            return SageResult(ok=False, sql=safe_sql, reason=f"exec: {e}")

        answer = await _narrate(question, rows, providers)
        return SageResult(ok=True, answer=answer, sql=safe_sql, rows=rows)

    return SageResult(ok=False, sql=sql, reason="repair attempt exhausted")
