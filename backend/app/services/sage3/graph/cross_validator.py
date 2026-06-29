"""
Cross-validator node (Phase 4) — independent grounding re-check.

Verifies the draft follows STRICTLY from the evidence: every numeric figure cited
in the answer must appear in the returned rows. This is the anti-hallucination
backstop — it catches a number the narrator invented even if the critic passed it.
Deterministic by default (number-set containment); an LLM, when present, also
flags unsupported store/claim references. Small "structural" numbers (years, top-N
limits) are ignored so they don't trip the check.
"""
from __future__ import annotations

from typing import List

from app.services.llm import get_provider_chain
from ..state import AgentState, add_trace
from .critic import evidence_rows
from .llm_util import complete_json, numbers_in
from .prompts import CROSS_SYSTEM

# Ignore structural integers that legitimately appear in phrasing but not rows.
_STRUCTURAL = set(range(0, 13)) | {2013, 2014, 2015, 2016, 2017, 2025, 2030, 2050, 100}


def _evidence_numbers(rows: List[dict]) -> set:
    nums: set = set()
    for r in rows:
        for v in r.values():
            nums |= numbers_in(str(v))
    return nums


def _heuristic_cross(state: AgentState) -> dict:
    if not state.get("grounded"):
        return {"supported": True, "confidence": 0.6, "unsupported": []}
    answer_nums = numbers_in(state.get("draft_answer", "")) - _STRUCTURAL
    ev_nums = _evidence_numbers(evidence_rows(state))
    # Allow rounded/aggregated values: a cited number is supported if it (or its
    # rounded form) is in evidence, OR evidence is a single scalar the answer states.
    unsupported = sorted(n for n in answer_nums if n not in ev_nums and round(n) not in ev_nums)
    if not answer_nums:
        return {"supported": True, "confidence": 0.8, "unsupported": []}
    frac_ok = 1 - len(unsupported) / max(1, len(answer_nums))
    return {"supported": not unsupported, "confidence": round(0.5 + 0.45 * frac_ok, 2),
            "unsupported": [str(n) for n in unsupported]}


async def cross_validator_node(state: AgentState) -> AgentState:
    result = None
    providers = get_provider_chain()
    if providers and state.get("grounded"):
        rows = evidence_rows(state)
        ev = "\n".join(str(r) for r in rows[:20]) or "(no rows)"
        obj = await complete_json(providers, CROSS_SYSTEM,
                                  f"DRAFT:\n{state.get('draft_answer','')}\n\nEVIDENCE rows:\n{ev}")
        if obj and "supported" in obj:
            obj.setdefault("confidence", 0.6 if obj.get("supported") else 0.3)
            obj.setdefault("unsupported", [])
            try:
                obj["confidence"] = float(obj["confidence"])
                result = obj
            except (TypeError, ValueError):
                result = None
    if result is None:
        result = _heuristic_cross(state)

    state["cross_check"] = result
    add_trace(state, "cross_validator",
              f"supported={result['supported']} @ {result['confidence']:.2f}"
              + (f", {len(result['unsupported'])} unsupported" if result.get("unsupported") else ""),
              confidence=result["confidence"])
    return state
