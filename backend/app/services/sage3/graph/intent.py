"""
Intent node — classify the query and score its CLARITY (Phase 2).

Reuses the existing keyword intent detector, then scores how answerable the query
is without guessing. With an LLM it asks for a JSON clarity score; with no LLM it
falls back to a conservative keyword heuristic (only flags genuinely vague asks so
the demo isn't over-clarifying). The router/orchestrator uses clarity_score to
decide whether to enter the clarification loop.
"""
from __future__ import annotations

from app.services.ai_assistant import detect_intent
from app.services.llm import get_provider_chain
from ..state import AgentState, add_trace
from .llm_util import complete_json
from .prompts import CLARITY_SYSTEM

# Bare, dimensionless asks that need a follow-up (no metric/time/store specified).
_VAGUE_SOLO = {
    "sales", "revenue", "returns", "stores", "store", "data", "report",
    "summary", "show me", "info", "details", "numbers", "performance", "stats",
}
_VAGUE_PRONOUNS = {"it", "that", "this", "them", "those", "there", "they"}


def _heuristic_clarity(query: str) -> tuple[float, list[str]]:
    q = (query or "").strip().lower().rstrip("?.! ")
    words = q.split()
    if not words:
        return 0.2, ["The question is empty."]
    if q in _VAGUE_SOLO or (len(words) <= 2 and words[0] in _VAGUE_SOLO):
        return 0.35, ["Which metric, time period, or store did you mean?"]
    # A lone vague pronoun subject with no concrete noun nearby.
    if len(words) <= 3 and any(w in _VAGUE_PRONOUNS for w in words):
        return 0.4, ["It's unclear what 'it/that' refers to — which store or metric?"]
    if "compare" in words and len(words) <= 2:
        return 0.4, ["Compare what — which stores, categories, or periods?"]
    return 0.9, []


async def intent_node(state: AgentState) -> AgentState:
    query = state.get("user_query", "")
    info = detect_intent(query)

    providers = get_provider_chain()
    clarity, ambiguities, cq = None, [], ""
    if providers:
        obj = await complete_json(providers, CLARITY_SYSTEM, f"Question: {query}")
        if obj is not None:
            try:
                clarity = float(obj.get("clarity", 1.0))
            except (TypeError, ValueError):
                clarity = None
            ambiguities = [str(a) for a in (obj.get("ambiguities") or [])]
            cq = str(obj.get("clarifying_question") or "")
    if clarity is None:  # no LLM or unparseable → heuristic
        clarity, ambiguities = _heuristic_clarity(query)

    info["clarity_score"] = clarity
    info["ambiguities"] = ambiguities
    state["intent"] = info
    state["clarity_score"] = clarity
    state["ambiguities"] = ambiguities
    if cq:
        state["clarification_question"] = cq

    labels = ", ".join(info.get("intents", [])) or "general"
    add_trace(state, "intent", f"intents: {labels} (clarity {clarity:.2f})")
    return state
