"""
Guardrail framework (GR-1) — a declarative, layered pipeline.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §2.

Guardrails are ordered, config-driven stages grouped by PHASE (input →
retrieval → output). Each declares a SEVERITY (block/warn/log) and a FAIL_MODE
(open/closed) so security checks fail closed and UX checks fail open. No single
guardrail is trusted alone — defense in depth (same philosophy as the SQL
allowlist guard). Every trip is recorded with the request trace id.

Pure and importable (no external deps here). Individual guardrails (GR-2..GR-4)
register themselves as `Guardrail` instances; this module just runs them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("guardrails")


class Phase(str, Enum):
    INPUT = "input"          # before retrieval/generation (query-time)
    RETRIEVAL = "retrieval"  # around retrieval (ACL/source/freshness)
    OUTPUT = "output"        # before the answer reaches the user


class Severity(str, Enum):
    BLOCK = "block"  # a trip stops the request (or forces refuse/regenerate)
    WARN = "warn"    # a trip is surfaced but doesn't stop
    LOG = "log"      # recorded only


class FailMode(str, Enum):
    OPEN = "open"     # if the CHECK itself errors, allow (UX guardrails)
    CLOSED = "closed"  # if the CHECK itself errors, block (security guardrails)


@dataclass
class Verdict:
    """What a single guardrail's check returns."""
    ok: bool                      # True = passed; False = tripped
    reason: str = ""              # why it tripped (for logs / user message)
    detail: Dict[str, object] = field(default_factory=dict)
    # A guardrail may transform the payload (e.g. PII redaction). If set, the
    # pipeline threads it into the context for downstream stages.
    transformed: Optional[Dict[str, object]] = None


@dataclass
class GuardrailContext:
    """Everything a guardrail may inspect. Fields are optional per phase."""
    trace_id: str = ""
    # input phase
    query: str = ""
    tenant_id: int = 0
    role: str = ""
    allowed_stores: List[int] = field(default_factory=list)
    lang: str = "en"
    # output phase
    answer: str = ""
    chunks: List[dict] = field(default_factory=list)   # retrieved context
    citations: List[str] = field(default_factory=list)
    # scratch for guardrails to pass signals forward
    meta: Dict[str, object] = field(default_factory=dict)


@dataclass
class Guardrail:
    """A declarative guardrail. `check` returns a Verdict."""
    name: str
    phase: Phase
    severity: Severity
    fail_mode: FailMode
    check: Callable[[GuardrailContext], Verdict]
    enabled: bool = True


@dataclass
class Trip:
    guardrail: str
    phase: Phase
    severity: Severity
    reason: str
    detail: Dict[str, object] = field(default_factory=dict)


@dataclass
class PhaseResult:
    allowed: bool                 # False if any BLOCK guardrail tripped
    trips: List[Trip] = field(default_factory=list)

    @property
    def block_reason(self) -> Optional[str]:
        for t in self.trips:
            if t.severity == Severity.BLOCK:
                return t.reason
        return None


class GuardrailPipeline:
    """Holds guardrails and runs them by phase."""

    def __init__(self, guardrails: Optional[List[Guardrail]] = None):
        self._rails: List[Guardrail] = list(guardrails or [])

    def register(self, rail: Guardrail) -> "GuardrailPipeline":
        self._rails.append(rail)
        return self

    def for_phase(self, phase: Phase) -> List[Guardrail]:
        return [g for g in self._rails if g.enabled and g.phase == phase]

    def run(self, phase: Phase, ctx: GuardrailContext) -> PhaseResult:
        """Run all enabled guardrails for `phase`. A BLOCK trip sets
        allowed=False but every guardrail still runs (so we log all findings).
        A guardrail whose check RAISES honors its fail_mode."""
        allowed = True
        trips: List[Trip] = []
        for g in self.for_phase(phase):
            try:
                v = g.check(ctx)
            except Exception as e:  # the check itself failed
                reason = f"guardrail '{g.name}' errored: {e}"
                if g.fail_mode == FailMode.CLOSED:
                    trips.append(Trip(g.name, g.phase, Severity.BLOCK, reason))
                    allowed = False
                    logger.warning("[%s] %s (fail-closed -> BLOCK)", ctx.trace_id, reason)
                else:
                    logger.warning("[%s] %s (fail-open -> allow)", ctx.trace_id, reason)
                continue

            if v.transformed:
                ctx.meta.update(v.transformed)

            if not v.ok:
                trips.append(Trip(g.name, g.phase, g.severity, v.reason, v.detail))
                if g.severity == Severity.BLOCK:
                    allowed = False
                logger.info("[%s] guardrail trip: %s/%s — %s",
                            ctx.trace_id, g.phase.value, g.name, v.reason)
        return PhaseResult(allowed=allowed, trips=trips)
