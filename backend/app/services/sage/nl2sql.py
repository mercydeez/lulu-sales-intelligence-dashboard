"""
NL->SQL orchestration for Sage: generate -> validate -> execute -> shape.

`answer_question` returns a SageResult. It deliberately does NOT write the
natural-language narrative — ai_assistant streams that from the provider chain
using the rows as context, reusing the existing summarization path. This module
owns everything up to and including "here are the correct rows + a chart spec".
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.config import logger
from app.services.llm import LLMError, get_provider_chain

from .schema_catalog import ALLOWED_RELATIONS, MAX_ROWS, SCHEMA_CATALOG
from .validator import SQLValidationError, clean_and_validate
from .executor import run_select

# Models occasionally answer "I can't" in prose; treat these as no-query.
_NO_QUERY_MARKERS = ("NO_QUERY", "NO QUERY", "I cannot", "I can't")


@dataclass
class SageResult:
    mode: str  # "sql" | "no_query" | "error"
    question: str
    sql: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    chart: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        """Trimmed, JSON-safe view for the API/done-event."""
        return {
            "mode": self.mode,
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows[:50],
            "row_count": self.row_count,
            "chart": self.chart,
            "error": self.error,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


def _safe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: _json_safe(v) for k, v in row.items()} for row in rows]


def _extract_sql(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    if any(marker.lower() in text.lower()[:40] for marker in _NO_QUERY_MARKERS):
        return None
    return text


async def _generate_sql(question: str, history: Optional[List[Dict[str, str]]]) -> Optional[str]:
    """Ask the LLM chain for a single SELECT. Returns raw text or None."""
    chain = get_provider_chain()
    if not chain:
        return None
    messages: List[Dict[str, str]] = [{"role": "system", "content": SCHEMA_CATALOG}]
    # A little recent context helps follow-up questions ("...and by store?").
    for m in (history or [])[-4:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})

    for provider in chain:
        try:
            return await provider.complete(messages)
        except LLMError as e:
            logger.warning("Sage SQL generation via %s failed: %s", provider.name, e)
            continue
    return None


def _infer_chart(columns: List[str], rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Heuristic chart spec: a label/time column + a numeric column over many rows."""
    if len(columns) < 2 or len(rows) < 2:
        return None
    first = rows[0]
    # Pick the first numeric column as the measure.
    numeric_cols = [c for c in columns if isinstance(first.get(c), (int, float))]
    label_cols = [c for c in columns if c not in numeric_cols]
    if not numeric_cols or not label_cols:
        return None
    x = label_cols[0]
    y = numeric_cols[0]
    is_time = "date" in x.lower() or "month" in x.lower() or "day" in x.lower()
    return {"type": "line" if is_time else "bar", "x": x, "y": y}


async def answer_question(
    question: str,
    tenant_id: int,
    history: Optional[List[Dict[str, str]]] = None,
) -> SageResult:
    """Run the full NL->SQL pipeline. Never raises — returns a SageResult whose
    mode tells the caller what happened (sql / no_query / error)."""
    q = (question or "").strip()
    if not q:
        return SageResult(mode="no_query", question=question)

    raw = await _generate_sql(q, history)
    candidate = _extract_sql(raw) if raw is not None else None
    if candidate is None:
        # Either no LLM available or the model declined to produce a query.
        return SageResult(mode="no_query", question=q)

    try:
        sql = clean_and_validate(candidate, ALLOWED_RELATIONS, MAX_ROWS)
    except SQLValidationError as e:
        logger.info("Sage rejected generated SQL: %s | candidate=%r", e, candidate[:200])
        return SageResult(mode="no_query", question=q, error=f"unsafe_sql: {e}")

    try:
        columns, rows = await run_select(sql, tenant_id, MAX_ROWS)
    except Exception as e:  # SQL error, timeout, connection — fall back gracefully
        logger.warning("Sage query execution failed: %s | sql=%r", e, sql[:200])
        return SageResult(mode="error", question=q, sql=sql, error=str(e))

    safe = _safe_rows(rows)
    return SageResult(
        mode="sql",
        question=q,
        sql=sql,
        columns=columns,
        rows=safe,
        row_count=len(safe),
        chart=_infer_chart(columns, safe),
    )
