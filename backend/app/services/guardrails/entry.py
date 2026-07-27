"""
Universal input screen for EVERY LLM entry point (defense-in-depth).

Sage has several answer lanes (multipart NL→SQL, federated SQL, RAG docs,
sage3 graph, the public API). Each lane has its own downstream guards (the SQL
allow-list, the RAG output rails), but prompt-injection must be stopped BEFORE
any lane runs a model or builds a prompt — a jailbreak that reaches the LLM has
already partly won. So this screen runs once, deterministically, at the door.

`screen_input(message)` returns a refusal string if a BLOCK input-rail trips
(prompt injection, over-length), else None. It is pure w.r.t. the DB and cheap
(regex rails), safe to call on the hot path of every chat request.

This complements — does not replace — the per-lane guards. The SQL guard still
validates generated SQL; the RAG pipeline still runs its full INPUT+OUTPUT
rails and confidence gate.
"""
from __future__ import annotations

from typing import Optional

from .default import default_pipeline
from .pipeline import GuardrailContext, Phase, Severity

# One shared pipeline instance — the rails are stateless.
_PIPELINE = default_pipeline()

REFUSAL = (
    "I can't help with that request. It looks like an attempt to change my "
    "instructions or access data outside your permissions. Ask a question about "
    "your stores' sales, inventory, or operations and I'll help."
)


def screen_input(message: str, *, trace_id: str = "entry") -> Optional[str]:
    """Return a refusal string if the message trips a BLOCK input guardrail
    (prompt injection / jailbreak / over-length), else None. Never raises —
    a screen failure must not take the assistant down (fail-open to the
    lane-level guards, which still run)."""
    try:
        res = _PIPELINE.run(Phase.INPUT, GuardrailContext(query=message or "", trace_id=trace_id))
    except Exception:
        return None
    if not res.allowed:
        return REFUSAL
    # WARN-level trips (e.g. off-topic) don't block, but a BLOCK does.
    for t in res.trips:
        if t.severity == Severity.BLOCK:
            return REFUSAL
    return None


def input_block_reason(message: str, *, trace_id: str = "entry") -> Optional[str]:
    """Like screen_input but returns the guardrail NAME that blocked (for logs /
    the adversarial harness), or None if allowed."""
    try:
        res = _PIPELINE.run(Phase.INPUT, GuardrailContext(query=message or "", trace_id=trace_id))
    except Exception:
        return None
    if not res.allowed and res.trips:
        return res.trips[0].guardrail
    return None
