"""
Sage v3 — multi-agent LangGraph chatbot for Retail IQ.

Extends (does not replace) the Sage v2 chatbot: each execution node is a thin
wrapper over an existing service (nl2sql, rag, sage2, federation), with new
dialogue (clarification, readback) and self-validation (critic, cross-validator,
arbiter, completeness) nodes. Gated behind settings.use_sage_v3 (default off) for
A/B and rollback. See docs/SAGE_V3_AGENT_INTEGRATION.md.

Importing this package does NOT import LangGraph — that happens lazily inside
get_graph() so the app boots regardless of whether the dependency is installed.
"""
from .state import AgentState, initial_state

__all__ = ["AgentState", "initial_state", "get_graph", "run_sage3"]


def __getattr__(name: str):
    # Lazy re-export of the orchestrator entrypoints so `from app.services.sage3
    # import run_sage3` works without importing LangGraph at package-import time.
    if name in ("get_graph", "run_sage3"):
        from . import orchestrator
        return getattr(orchestrator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
