"""
Sage NL->SQL package (A2): turn natural-language questions into guarded,
tenant-scoped SQL over a curated semantic layer, then narrate strictly from the
returned rows. Provider-agnostic — falls back to the rule-based responder when no
LLM is configured.
"""
from .guard import SqlGuardError, validate_sql
from .pipeline import SageResult, answer_question, deterministic_answer
from .schema import ALLOWED_RELATIONS

__all__ = [
    "answer_question",
    "SageResult",
    "deterministic_answer",
    "validate_sql",
    "SqlGuardError",
    "ALLOWED_RELATIONS",
]
