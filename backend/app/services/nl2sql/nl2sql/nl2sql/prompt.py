"""Prompt construction for Sage's two LLM calls: NL->SQL, then narrate-from-rows."""
from __future__ import annotations

import json
import re
from typing import Dict, List

from .schema import FEW_SHOTS, SCHEMA_PROMPT

_SQL_SYSTEM = """\
You are Sage, a careful analytics SQL writer for a retail dashboard. Convert the \
user's question into ONE PostgreSQL SELECT over the provided views.

RULES:
- Output ONLY the SQL. No prose, no markdown fences, no trailing semicolon.
- A single SELECT (a leading WITH/CTE is fine). Never write to the database.
- Read only the sage_* views below. Do not reference any other table.
- The views are already tenant-scoped — never add a tenant filter.
- Follow the units (volume) vs revenue_aed (money) convention exactly.

{schema}
"""

_NARRATE_SYSTEM = """\
You are Sage, a retail analytics assistant. Answer the user's question using ONLY \
the SQL result rows provided. Rules:
- Use ONLY the numbers in the rows. Never invent or estimate values not present.
- If the rows are empty, say you found no matching data for that question.
- Money is AED (the *_aed columns); volume is units. Keep them distinct.
- Be concise and specific; format large numbers with thousands separators.
"""


def build_sql_messages(question: str) -> List[Dict[str, str]]:
    """Messages that ask the model for a single SELECT."""
    shots = "\n".join(f"Q: {s['q']}\nSQL: {s['sql']}" for s in FEW_SHOTS)
    return [
        {"role": "system", "content": _SQL_SYSTEM.format(schema=SCHEMA_PROMPT)},
        {"role": "user", "content": f"Examples:\n{shots}\n\nQ: {question}\nSQL:"},
    ]


def extract_sql(raw: str) -> str:
    """Pull the SQL out of a model response: strip markdown fences / leading 'sql:'."""
    if not raw:
        return ""
    text = raw.strip()
    # ```sql ... ``` or ``` ... ```
    fence = re.search(r"```(?:sql)?\s*(.+?)```", text, re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Drop a leading 'SQL:' label if present.
    text = re.sub(r"^\s*sql\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def build_narration_messages(question: str, rows: List[dict]) -> List[Dict[str, str]]:
    """Messages that ask the model to narrate strictly from the returned rows."""
    # Cap rows shown to the model to keep the prompt small; the answer summarizes.
    shown = rows[:50]
    rows_json = json.dumps(shown, ensure_ascii=False, default=str)
    return [
        {"role": "system", "content": _NARRATE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"SQL result rows ({len(rows)} total, showing {len(shown)}):\n{rows_json}\n\n"
                "Answer the question from these rows only."
            ),
        },
    ]
