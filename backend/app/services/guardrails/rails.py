"""
Concrete guardrails (GR-2 input, GR-3 output, GR-4 structural).
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §2.

All rule-based / deterministic — no LLM required, so they run in-process, are
unit-testable, and can't themselves hallucinate. The faithfulness check ships as
a lexical-grounding heuristic with a hook for an NLI/LLM-judge upgrade (§1.10);
the rest are exact. Each factory returns a `Guardrail` for the pipeline (GR-1).
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

from .pipeline import FailMode, Guardrail, GuardrailContext, Phase, Severity, Verdict

# --------------------------------------------------------------------------- #
# Shared detectors
# --------------------------------------------------------------------------- #
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|phc_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{16,})\b")

_INJECTION_PATTERNS = [
    r"ignore (all |the |your )?(previous|prior|above) (instructions|prompt)",
    r"disregard (the |your )?(system|previous) (prompt|instructions)",
    r"you are now\b", r"\bact as\b.*\b(dan|jailbreak|developer mode)\b",
    r"reveal (your |the )?(system prompt|instructions|hidden)",
    r"pretend (you are|to be)\b", r"\bbypass\b.*\b(guardrail|filter|policy|safety)\b",
    r"print (your |the )?(system prompt|instructions)",
]
_INJECTION = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Very conservative off-topic signal — only clearly-unrelated asks (WARN, not
# BLOCK, to avoid false positives on legitimate retail phrasing).
_OFFTOPIC = re.compile(
    r"\b(write (me )?(a )?(poem|song|story|essay|joke)|who is the (president|ceo of)"
    r"|translate this|recipe for|weather (today|tomorrow)|stock price of (?!our))\b",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    text = _SECRET.sub("[REDACTED_SECRET]", text)
    text = _EMAIL.sub("[REDACTED_EMAIL]", text)
    text = _CARD.sub("[REDACTED_CARD]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    return text


# --------------------------------------------------------------------------- #
# INPUT guardrails (GR-2)
# --------------------------------------------------------------------------- #
def pii_input_redaction() -> Guardrail:
    """Redact PII/secrets from the query before it reaches logs/LLM. Never
    blocks (redacts and continues); WARN so the trip is visible."""
    def check(ctx: GuardrailContext) -> Verdict:
        red = _redact(ctx.query)
        if red != ctx.query:
            return Verdict(ok=False, reason="PII/secret redacted from query",
                           transformed={"redacted_query": red})
        return Verdict(ok=True)
    return Guardrail("pii_input_redaction", Phase.INPUT, Severity.WARN, FailMode.OPEN, check)


def prompt_injection() -> Guardrail:
    """Block obvious prompt-injection / jailbreak attempts. Fail-closed."""
    def check(ctx: GuardrailContext) -> Verdict:
        if _INJECTION.search(ctx.query or ""):
            return Verdict(ok=False, reason="prompt-injection / jailbreak pattern detected")
        return Verdict(ok=True)
    return Guardrail("prompt_injection", Phase.INPUT, Severity.BLOCK, FailMode.CLOSED, check)


def query_length_limit(max_chars: int = 2000) -> Guardrail:
    def check(ctx: GuardrailContext) -> Verdict:
        n = len(ctx.query or "")
        if n > max_chars:
            return Verdict(ok=False, reason=f"query too long ({n} > {max_chars} chars)")
        return Verdict(ok=True)
    return Guardrail("query_length_limit", Phase.INPUT, Severity.BLOCK, FailMode.OPEN, check)


def topical_scope() -> Guardrail:
    """Warn on clearly off-topic (non-retail-ops) asks. Conservative — WARN."""
    def check(ctx: GuardrailContext) -> Verdict:
        if _OFFTOPIC.search(ctx.query or ""):
            return Verdict(ok=False, reason="query appears outside retail-operations scope")
        return Verdict(ok=True)
    return Guardrail("topical_scope", Phase.INPUT, Severity.WARN, FailMode.OPEN, check)


# --------------------------------------------------------------------------- #
# OUTPUT guardrails (GR-3)
# --------------------------------------------------------------------------- #
def pii_output_leak() -> Guardrail:
    """Block answers that leak PII/secrets. Fail-closed."""
    def check(ctx: GuardrailContext) -> Verdict:
        a = ctx.answer or ""
        if _SECRET.search(a) or _EMAIL.search(a) or _CARD.search(a):
            return Verdict(ok=False, reason="answer contains PII/secret")
        return Verdict(ok=True)
    return Guardrail("pii_output_leak", Phase.OUTPUT, Severity.BLOCK, FailMode.CLOSED, check)


def citation_enforcement(min_citations: int = 1) -> Guardrail:
    """Require the answer to carry at least one citation (grounding). Applies
    only when context chunks were retrieved. Fail-closed."""
    def check(ctx: GuardrailContext) -> Verdict:
        if not ctx.chunks:
            return Verdict(ok=True)  # nothing retrieved -> handled elsewhere (refuse)
        if len(ctx.citations) < min_citations:
            return Verdict(ok=False, reason="answer lacks a citation to the retrieved context")
        return Verdict(ok=True)
    return Guardrail("citation_enforcement", Phase.OUTPUT, Severity.BLOCK, FailMode.CLOSED, check)


def faithfulness_lexical(min_overlap: float = 0.30) -> Guardrail:
    """Lexical grounding proxy: what fraction of the answer's content words
    appear in the retrieved context? Below threshold => likely ungrounded.
    A cheap stand-in for an NLI/LLM-judge (swap `check` when a judge is wired).
    Fail-closed (a low score forces refuse/regenerate upstream)."""
    stop = set("the a an and or of to in for on is are was were be as at by with "
               "this that it its from your our their his her they we you i".split())

    def words(s: str):
        return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in stop and len(w) > 2]

    def check(ctx: GuardrailContext) -> Verdict:
        if not ctx.chunks or not ctx.answer:
            return Verdict(ok=True)
        ans = set(words(ctx.answer))
        if not ans:
            return Verdict(ok=True)
        ctxt = set()
        for c in ctx.chunks:
            ctxt.update(words(c.get("content", "")))
        overlap = len(ans & ctxt) / max(1, len(ans))
        if overlap < min_overlap:
            return Verdict(ok=False, reason=f"low grounding overlap ({overlap:.2f} < {min_overlap})",
                           detail={"overlap": round(overlap, 3)})
        return Verdict(ok=True, detail={"overlap": round(overlap, 3)})
    return Guardrail("faithfulness_lexical", Phase.OUTPUT, Severity.BLOCK, FailMode.OPEN, check)


def numeric_units_sanity() -> Guardrail:
    """Honesty guardrail: flag a units≠AED confusion — a bare unit count labeled
    as AED (or vice versa). Heuristic; the registry-range check (RAG-6/EVAL) adds
    magnitude bounds. WARN (surfaced, doesn't hard-block)."""
    aed_units = re.compile(r"AED\s*[\d,]+(?:\.\d+)?\s*(units|pcs|pieces|items)\b", re.IGNORECASE)

    def check(ctx: GuardrailContext) -> Verdict:
        if aed_units.search(ctx.answer or ""):
            return Verdict(ok=False, reason="units mislabeled as AED (units≠AED convention)")
        return Verdict(ok=True)
    return Guardrail("numeric_units_sanity", Phase.OUTPUT, Severity.WARN, FailMode.OPEN, check)


# --------------------------------------------------------------------------- #
# STRUCTURAL guardrail (GR-4) — schema-constrained output
# --------------------------------------------------------------------------- #
def structural_schema(required_keys: Sequence[str], types: Optional[dict] = None) -> Guardrail:
    """Validate a structured payload (ctx.meta['structured']) has the required
    keys and (optionally) types. The 'LLM proposes, validator disposes' pattern
    — same philosophy as nl2sql/guard.py (the SQL allowlist). Fail-closed."""
    types = types or {}

    def check(ctx: GuardrailContext) -> Verdict:
        obj = ctx.meta.get("structured")
        if obj is None:
            return Verdict(ok=True)  # not a structured-output turn
        if not isinstance(obj, dict):
            return Verdict(ok=False, reason="structured output is not an object")
        missing = [k for k in required_keys if k not in obj]
        if missing:
            return Verdict(ok=False, reason=f"structured output missing keys: {missing}")
        bad = [k for k, t in types.items() if k in obj and not isinstance(obj[k], t)]
        if bad:
            return Verdict(ok=False, reason=f"structured output wrong types: {bad}")
        return Verdict(ok=True)
    return Guardrail("structural_schema", Phase.OUTPUT, Severity.BLOCK, FailMode.CLOSED, check)
