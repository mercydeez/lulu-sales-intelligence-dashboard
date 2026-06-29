"""
Shared LLM helpers for Sage v3 nodes.

Every node that can use an LLM goes through `complete_json`, which tries the
provider chain and parses a JSON object out of the reply. It returns None when no
provider is configured or parsing fails — the caller then uses its deterministic
fallback. This keeps the hard invariant: the graph works with NO LLM configured.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from app.services.llm import LLMError, LLMProvider

logger = logging.getLogger(__name__)


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    # Prefer a fenced or bare {...} object.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def complete_json(providers: List[LLMProvider], system: str, user: str) -> Optional[dict]:
    """Try each provider for a JSON-object reply. None => caller uses fallback."""
    for provider in providers or []:
        try:
            raw = await provider.complete([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
            obj = _extract_json(raw)
            if obj is not None:
                return obj
        except LLMError:
            continue
        except Exception:  # never let a node crash on a provider quirk
            continue
    return None


# Numbers that appear in a grounded answer should trace to the evidence rows. This
# extracts comparable numeric tokens (commas/decimals stripped) for that check.
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def numbers_in(text: str) -> set:
    out = set()
    for tok in _NUM_RE.findall(text or ""):
        t = tok.replace(",", "")
        try:
            f = float(t)
            # Normalize to int when whole, so 1069 == 1069.0.
            out.add(int(f) if f.is_integer() else round(f, 2))
        except ValueError:
            continue
    return out
