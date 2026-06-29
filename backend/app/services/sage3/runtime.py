"""
Sage v3 runtime — request-facing entry points used by routes/ai.py when
settings.use_sage_v3 is true.

Mirrors the shapes ai_assistant exposes (streaming generator + non-streaming
string) so the SSE route and the voice path switch to v3 with a one-line branch
and zero SSE-contract change. It also drives the cross-turn DIALOGUE loops the
graph itself can't (it's stateless): a pending clarification or readback is parked
on the per-session context and resolved on the user's next turn —
  • clarification: the next message is folded into the original question and re-run
    (clarification_round caps the loop at 2);
  • readback: an affirmative next message confirms and executes without re-asking.

RBAC: tenant_id/role/allowed_stores come straight from the (already-scoped)
request into the graph — never widened.
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Dict, List, Optional

from app.services.ai_assistant import get_or_create_context
from .orchestrator import run_sage3
from .state import AgentState

_AFFIRM_EXACT = {
    "yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "proceed", "go",
    "go ahead", "sure", "ok", "okay", "do it", "please do", "correct", "right",
    "sounds good", "yes please", "go for it",
}
_AFFIRM_PREFIX = ("yes", "yeah", "yep", "proceed", "go ahead", "confirm", "sure",
                  "ok", "okay", "please do", "do it")


def _is_affirmative(msg: str) -> bool:
    m = (msg or "").strip().lower().rstrip("!. ")
    return m in _AFFIRM_EXACT or m.startswith(_AFFIRM_PREFIX)


def _history(context) -> List[Dict[str, str]]:
    return [m for m in context.get_messages() if m.get("role") != "system"][-12:]


async def answer_sage3(
    session_id: str,
    message: str,
    tenant_id: int = 1,
    role: str = "store_manager",
    allowed_stores: Optional[List[int]] = None,
) -> AgentState:
    """Run the v3 graph once (resolving any pending dialogue), persist the turn,
    and return the terminal state (final_answer + confidence + trace + evidence)."""
    context = get_or_create_context(session_id)
    pending = getattr(context, "pending", None)

    effective_query = message
    clarification_round = 0
    readback_confirmed = False

    if pending:
        if pending.get("mode") == "readback":
            if _is_affirmative(message):
                effective_query = pending.get("original_query", message)
                readback_confirmed = True
            # else: treat as a brand-new question
        elif pending.get("mode") == "clarification":
            effective_query = f"{pending.get('original_query', '')} — {message}".strip(" —")
            clarification_round = int(pending.get("round", 0)) + 1
        context.pending = None

    state = await run_sage3(
        session_id=session_id,
        user_query=effective_query,
        tenant_id=tenant_id,
        role=role,
        allowed_stores=allowed_stores,
        conversation_history=_history(context),
        clarification_round=clarification_round,
        readback_confirmed=readback_confirmed,
    )

    # Park any new pending dialogue for the next turn.
    if state.get("needs_clarification"):
        context.pending = {"mode": "clarification", "original_query": effective_query,
                           "round": clarification_round}
    elif state.get("needs_readback"):
        context.pending = {"mode": "readback", "original_query": effective_query}
    else:
        context.pending = None

    answer = state.get("final_answer", "") or ""
    context.add_message("user", message)
    if answer:
        context.add_message("assistant", answer)
    return state


async def get_sage3_chat(
    session_id: str,
    message: str,
    tenant_id: int = 1,
    role: str = "store_manager",
    allowed_stores: Optional[List[int]] = None,
) -> str:
    """Non-streaming final answer (voice path and /chat?stream=false)."""
    state = await answer_sage3(session_id, message, tenant_id, role, allowed_stores)
    return state.get("final_answer", "") or ""


async def stream_sage3_chat(
    session_id: str,
    message: str,
    tenant_id: int = 1,
    role: str = "store_manager",
    allowed_stores: Optional[List[int]] = None,
) -> AsyncGenerator[str, None]:
    """Stream the final answer as word chunks (matches the existing SSE contract)."""
    state = await answer_sage3(session_id, message, tenant_id, role, allowed_stores)
    answer = state.get("final_answer", "") or ""
    words = answer.split(" ")
    for i, word in enumerate(words):
        yield word + (" " if i < len(words) - 1 else "")
        await asyncio.sleep(0.01)


def sage3_meta(state: AgentState) -> dict:
    """Extra fields for the SSE 'done' event (additive; old clients ignore them)."""
    return {
        "engine": "sage_v3",
        "route": state.get("route"),
        "confidence": state.get("final_confidence"),
        "grounded": state.get("grounded"),
        "needs_clarification": bool(state.get("needs_clarification")),
        "needs_readback": bool(state.get("needs_readback")),
        "readback_text": state.get("readback_text"),
        "clarification_question": state.get("clarification_question"),
        "trace": state.get("trace", []),
        "evidence": state.get("evidence", []),
    }
