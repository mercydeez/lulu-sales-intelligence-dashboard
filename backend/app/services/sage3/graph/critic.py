"""
Critic node (Phase 4) — score the draft answer.

Scores grounding (figures trace to evidence), completeness (all parts answered),
and unit correctness. With an LLM it asks for a JSON verdict; deterministically it
scores from signals already in state (grounded?, rows returned?, fraction of
multipart sub-answers that succeeded). Output drives the CONDITIONAL validation
stack: high-confidence simple reads skip straight to the finaliser; borderline or
multi-part answers go through cross-validation.
"""
from __future__ import annotations

from typing import List

from app.services.llm import get_provider_chain
from ..state import AgentState, add_trace
from .llm_util import complete_json
from .prompts import CRITIC_SYSTEM


def evidence_rows(state: AgentState) -> List[dict]:
    """Flatten the rows the answer was built from, for grounding checks."""
    route = state.get("route")
    if route == "sql":
        return (state.get("sql_result") or {}).get("rows") or []
    if route == "hybrid":
        rows: List[dict] = []
        for p in (state.get("hybrid_result") or {}).get("parts", []):
            rows.extend(p.get("rows") or [])
        return rows
    return []


def _heuristic_critic(state: AgentState) -> dict:
    grounded = bool(state.get("grounded"))
    route = state.get("route")
    issues: List[str] = []

    if not grounded:
        # Real ORM-backed rule-based answer — accurate but not from the nl2sql
        # evidence trail, so medium confidence.
        return {"confidence": 0.6, "verdict": "uncertain",
                "issues": ["answer came from the deterministic responder, not a traced query"]}

    if route == "hybrid":
        parts = (state.get("hybrid_result") or {}).get("parts", [])
        ok = sum(1 for p in parts if p.get("ok"))
        total = len(parts) or 1
        frac = ok / total
        conf = round(0.5 + 0.45 * frac, 2)
        if ok < total:
            issues.append(f"{total - ok} of {total} sub-questions returned no data")
        verdict = "pass" if frac == 1 else ("retry" if frac < 0.5 else "uncertain")
        return {"confidence": conf, "verdict": verdict, "issues": issues}

    # sql / rag
    rows = evidence_rows(state)
    if route == "sql" and not rows:
        return {"confidence": 0.65, "verdict": "uncertain",
                "issues": ["query returned no rows"]}
    return {"confidence": 0.85, "verdict": "pass", "issues": []}


async def critic_node(state: AgentState) -> AgentState:
    verdict = None
    providers = get_provider_chain()
    if providers and state.get("grounded"):
        rows = evidence_rows(state)
        ev = "\n".join(str(r) for r in rows[:20]) or "(no rows)"
        obj = await complete_json(providers, CRITIC_SYSTEM,
                                  f"Question: {state.get('user_query','')}\n\n"
                                  f"DRAFT:\n{state.get('draft_answer','')}\n\nEVIDENCE rows:\n{ev}")
        if obj and "confidence" in obj:
            try:
                obj["confidence"] = float(obj["confidence"])
                obj.setdefault("verdict", "uncertain")
                obj.setdefault("issues", [])
                verdict = obj
            except (TypeError, ValueError):
                verdict = None
    if verdict is None:
        verdict = _heuristic_critic(state)

    state["critic_verdict"] = verdict
    add_trace(state, "critic",
              f"{verdict['verdict']} @ {verdict['confidence']:.2f}"
              + (f" ({len(verdict['issues'])} issue(s))" if verdict.get("issues") else ""),
              confidence=verdict["confidence"])
    return state
