"""
Readback gate (Phase 3).

For complex / multi-part requests, Sage paraphrases the plan it will run and asks
the user to confirm BEFORE executing — so a costly multi-domain query isn't run on
a misread. Approve-by-default for simple single reads (those never reach this
node). The runtime records the pending readback; an affirmative reply on the next
turn sets readback_confirmed and the graph executes without asking again.

Deterministic by default (paraphrases the planner's sub-question labels); an LLM,
when present, just phrases it more naturally.
"""
from __future__ import annotations

from app.services.llm import get_provider_chain
from app.services.sage2.intents import match_intents, extract_zone
from ..state import AgentState, add_trace
from .llm_util import complete_json
from .prompts import READBACK_SYSTEM


def _deterministic_readback(state: AgentState) -> str:
    q = state.get("user_query", "")
    subs = [i.label for i in match_intents(q)]
    zone = extract_zone(q)
    scope = f" for {zone}" if zone else ""
    if subs:
        listed = "; ".join(subs)
        return f"📝 To confirm, I'll pull{scope}: {listed}. Shall I proceed?"
    return (f"📝 I'll break this multi-part question down and answer each part{scope} "
            f"from your data. Shall I proceed?")


async def readback_node(state: AgentState) -> AgentState:
    text = ""
    providers = get_provider_chain()
    if providers:
        obj = await complete_json(providers, READBACK_SYSTEM,
                                  f"Question: {state.get('user_query', '')}")
        if obj and obj.get("readback"):
            text = str(obj["readback"])
    if not text:
        text = _deterministic_readback(state)

    state["needs_readback"] = True
    state["readback_text"] = text
    state["draft_answer"] = text
    state["grounded"] = False
    add_trace(state, "readback", "awaiting confirmation")
    return state
