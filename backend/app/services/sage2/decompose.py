"""
LLM query decomposer for Sage v2: split one multi-part question into independent,
self-contained sub-questions the per-sub NL→SQL/RAG step can answer. Returns [] on
any failure so the orchestrator falls back to the deterministic intent matcher.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List

from app.services.llm import LLMError, LLMProvider

logger = logging.getLogger(__name__)

_SYSTEM = """\
You split a business question into independent, self-contained sub-questions, one
per distinct metric or fact asked for. Each sub-question must stand alone (carry
any zone/time qualifier from the original) and map to ONE of these domains:
sales, distributors, crm_pipeline, online_pricing, targets, documents.

Return ONLY a JSON array of strings — the sub-questions. No prose.
Example:
Q: "For North: 2030 target, total sales revenue, CRM pipeline revenue, which distributors serve North, and average online price?"
["What is the 2030 revenue target?","What is the total primary sales revenue?","What is the total CRM pipeline expected revenue for the North zone?","Which distributors serve the North zone?","What is the average online selling price?"]
"""


async def llm_decompose(question: str, providers: List[LLMProvider]) -> List[str]:
    for provider in providers:
        try:
            raw = await provider.complete([
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Q: {question}"},
            ])
            subs = _parse(raw)
            if subs:
                return subs
        except LLMError:
            continue
    return []


def _parse(raw: str) -> List[str]:
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [str(s).strip() for s in arr if isinstance(s, str) and s.strip()][:10]
