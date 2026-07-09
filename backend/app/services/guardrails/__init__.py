"""Guardrail system for Sage (GR-1..GR-4).

Layered, declarative, fail-open/closed guardrails around the RAG/answer path.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §2.

    from app.services.guardrails import default_pipeline, GuardrailContext, Phase
    gp = default_pipeline()
    res = gp.run(Phase.INPUT, GuardrailContext(query=q, trace_id=tid, ...))
    if not res.allowed:  # a BLOCK guardrail tripped
        refuse(res.block_reason)
"""
from .pipeline import (
    FailMode,
    Guardrail,
    GuardrailContext,
    GuardrailPipeline,
    Phase,
    PhaseResult,
    Severity,
    Trip,
    Verdict,
)
from .default import default_pipeline

__all__ = [
    "FailMode", "Guardrail", "GuardrailContext", "GuardrailPipeline", "Phase",
    "PhaseResult", "Severity", "Trip", "Verdict", "default_pipeline",
]
