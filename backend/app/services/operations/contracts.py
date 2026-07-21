"""Operations Copilot — the output contract.

THE RULE THIS FILE ENFORCES: every number the copilot shows a human must be
traceable to a deterministic measurement. The LLM writes prose; it never writes
numbers. `EvidenceItem` is where numbers come from, `measured_facts` cite
evidence, `hypotheses` are explicitly labelled as unproven, and
`ungrounded_numbers()` is the mechanical check that a generated narrative did
not invent a figure that no evidence supports.

Model output is treated as untrusted input: it is parsed into these models and
anything that fails validation is discarded in favour of the deterministic
template (see fallback.py). A proposal that cannot cite evidence never reaches a
human approver — the copilot refuses instead.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

#: Bumped whenever the shape of a persisted recommendation changes.
PAYLOAD_VERSION = "v1"
#: Bumped whenever the graph's node set or transitions change.
GRAPH_VERSION = "ops-v1"
#: Bumped whenever a prompt is edited. Stamped on every run so a bad batch of
#: recommendations can be traced back to the exact prompt that produced them.
PROMPT_VERSION = "ops-recommend-v1"


class ActionType(str, Enum):
    """The ONLY actions the copilot may propose. Anything else is refused.

    Deliberately absent, and never to be added without a policy review: pricing
    and promotion changes, supplier communication, and every employee-related
    action (discipline, hiring, termination, compensation).
    """

    REPLENISHMENT_DRAFT = "replenishment_draft"
    STOCK_TRANSFER_DRAFT = "stock_transfer_draft"
    INVESTIGATION_TASK = "investigation_task"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceType(str, Enum):
    """Where a measured value came from — surfaced in the UI verbatim so nobody
    mistakes a sales-derived estimate for a POS or ERP reading."""

    SALES_FACT = "sales_fact"          # sales_fact_view (real transactional history)
    INVENTORY_TABLE = "inventory"      # the inventory table (seeded, not POS-fed)
    DERIVED_ESTIMATE = "derived"       # computed from sales — NOT a stock count
    FINDING_EVIDENCE = "finding"       # the deterministic rule's own evidence blob
    METRIC_VIEW = "metric_view"        # a metric_* SQL view the worker also uses


class RunStatus(str, Enum):
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    MEASURING = "measuring"
    COMPLETED = "completed"
    REFUSED = "refused"
    ESCALATED = "escalated"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


#: Once a run reaches one of these it never transitions again.
TERMINAL_RUN_STATUSES = frozenset({
    RunStatus.COMPLETED, RunStatus.REFUSED, RunStatus.ESCALATED,
    RunStatus.REJECTED, RunStatus.CANCELLED, RunStatus.FAILED,
})


class ProposalStatus(str, Enum):
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class EvidenceItem(BaseModel):
    """One measured number with its provenance. Produced by deterministic read
    tools only — there is no code path that lets a model construct one."""

    evidence_id: str = Field(..., min_length=1, max_length=64)
    metric_name: str = Field(..., min_length=1, max_length=120)
    current_value: Optional[float] = None
    comparison_value: Optional[float] = None
    comparison_period: Optional[str] = None
    unit: str = Field(..., min_length=1, max_length=32)   # 'units' | 'AED' | 'days' | 'pct'
    source_type: SourceType
    source_reference: str = Field(..., min_length=1, max_length=200)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class MeasuredFact(BaseModel):
    """A statement that is TRUE because evidence says so. Must cite evidence."""

    statement: str = Field(..., min_length=1, max_length=500)
    evidence_ids: List[str] = Field(..., min_length=1)


class Hypothesis(BaseModel):
    """A possible cause. NOT a fact — the UI must render it as unproven, and
    nothing downstream may compute from it."""

    statement: str = Field(..., min_length=1, max_length=500)
    # How it could be confirmed or ruled out — this is what makes a hypothesis
    # actionable instead of decorative.
    check: Optional[str] = Field(None, max_length=500)
    supporting_evidence_ids: List[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    """A concrete, human-approvable draft. Every parameter in
    `calculated_parameters` comes from a deterministic calculator."""

    action_type: ActionType
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    target_store_ids: List[int] = Field(default_factory=list)
    target_item_ids: List[int] = Field(default_factory=list)
    calculated_parameters: Dict[str, Any] = Field(default_factory=dict)
    #: "unknown" is a legitimate, expected answer. An invented effect is not.
    expected_effect: str = Field(default="unknown", max_length=500)
    expected_effect_basis: str = Field(default="not calculable from available data",
                                       max_length=500)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reversible: bool = True
    #: Constrained to real roles so a model cannot persist a bogus/lower role that
    #: a downstream UI or filter might trust. The binding gate is still
    #: policy.can_approve(), which recomputes this server-side at approval time.
    required_approval_role: Literal[
        "analyst", "store_manager", "regional_manager", "super_admin"] = "super_admin"
    prerequisites: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    #: Evidence this action rests on. Empty means the action cannot be approved.
    evidence_ids: List[str] = Field(default_factory=list)


class ApprovalRequirement(BaseModel):
    required_role: str = Field(..., min_length=1, max_length=40)
    reason: str = Field(..., max_length=300)
    scope_store_ids: List[int] = Field(default_factory=list)


class MeasurementPlan(BaseModel):
    """How we will know whether the action worked. Set BEFORE approval so the
    success criterion cannot be redefined after the fact."""

    metric_name: str = Field(..., min_length=1, max_length=120)
    baseline_value: Optional[float] = None
    unit: str = Field(..., max_length=32)
    window_days: int = Field(..., ge=1, le=90)
    success_criterion: str = Field(..., max_length=300)


class OperationsRecommendation(BaseModel):
    """The full contract returned to the UI and persisted on the proposal.

    SERVER-ASSEMBLED, NEVER model-parsed. Do not `model_validate(llm_json)` into
    this type: `evidence`, `confidence`, `severity`, `measurement_plan` and the
    calculated parts of `proposed_actions` are produced by deterministic server
    code. The only thing an LLM contributes is prose, and that arrives as a
    separate `NarrativeDraft` (below) which carries no numbers-as-fields. The
    graph builds an OperationsRecommendation by MERGING server evidence with a
    validated NarrativeDraft — so an LLM cannot supply both a fabricated evidence
    list and a confidence score that grounds its own invented figures.
    """

    run_id: int
    finding_id: Optional[int] = None
    tenant_id: int
    scope: Dict[str, Any] = Field(default_factory=dict)   # stores/items/category
    title: str = Field(..., min_length=1, max_length=200)
    executive_summary: str = Field(default="", max_length=2000)
    severity: Severity = Severity.MEDIUM
    #: Deterministically derived (evidence completeness/freshness) — never a
    #: number the model chose for itself.
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    measured_facts: List[MeasuredFact] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    approval_requirement: Optional[ApprovalRequirement] = None
    measurement_plan: Optional[MeasurementPlan] = None
    #: Set when the copilot declined to propose anything. A recommendation with
    #: a refusal_reason and no actions is a VALID, useful outcome.
    refusal_reason: Optional[str] = None
    #: True when the narrative came from the deterministic template because no
    #: LLM was reachable. Surfaced in the UI — never hidden.
    llm_available: bool = True
    payload_version: str = PAYLOAD_VERSION
    graph_version: str = GRAPH_VERSION
    prompt_version: str = PROMPT_VERSION

    @model_validator(mode="after")
    def _evidence_is_traceable(self) -> "OperationsRecommendation":
        """Every cited evidence id must exist, and every proposed action must
        rest on at least one piece of evidence. This is the gate that stops an
        unsupported proposal from ever reaching a human approver."""
        known = {e.evidence_id for e in self.evidence}

        for fact in self.measured_facts:
            missing = [eid for eid in fact.evidence_ids if eid not in known]
            if missing:
                raise ValueError(
                    f"measured fact cites unknown evidence {missing}: {fact.statement!r}"
                )
        for hyp in self.hypotheses:
            missing = [eid for eid in hyp.supporting_evidence_ids if eid not in known]
            if missing:
                raise ValueError(f"hypothesis cites unknown evidence {missing}")
        for action in self.proposed_actions:
            missing = [eid for eid in action.evidence_ids if eid not in known]
            if missing:
                raise ValueError(f"action cites unknown evidence {missing}")
            if not action.evidence_ids:
                raise ValueError(
                    f"action {action.action_type.value!r} has no evidence — "
                    "unsupported proposals must be refused, not approved"
                )

        # A refusal and a live proposal are mutually exclusive: a consumer that
        # iterates proposed_actions must never build an approvable proposal from
        # a run that refused. Don't rely on is_actionable being consulted.
        if self.refusal_reason and self.proposed_actions:
            raise ValueError(
                "a refused recommendation must carry no proposed_actions"
            )
        return self

    @property
    def is_actionable(self) -> bool:
        return bool(self.proposed_actions) and not self.refusal_reason


class NarrativeHypothesis(BaseModel):
    """An LLM-authored possible cause. Prose only — no evidence, no numbers."""

    statement: str = Field(..., min_length=1, max_length=500)
    check: Optional[str] = Field(None, max_length=500)


class NarrativeDraft(BaseModel):
    """The ONLY thing parsed from LLM output. Treat as untrusted input.

    It carries prose and structure, deliberately NO evidence list, NO confidence,
    NO severity, NO numeric fields — those are the server's job. The graph parses
    model output into this, runs `ungrounded_numbers` over the free-text fields
    against server-side evidence, and only then merges it into an
    OperationsRecommendation. This is the boundary that keeps requirement #10
    ("the LLM must never invent numbers") a structural property, not a hope.
    """

    model_config = {"extra": "ignore"}     # ignore any smuggled extra fields

    title: str = Field(..., min_length=1, max_length=200)
    executive_summary: str = Field(default="", max_length=2000)
    #: Free-text statements that will be checked for ungrounded numbers and, if
    #: clean, turned into MeasuredFacts by server code that attaches the evidence.
    measured_fact_statements: List[str] = Field(default_factory=list)
    hypotheses: List[NarrativeHypothesis] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)

    def free_text(self) -> str:
        """Everything an ungrounded number could hide in, concatenated."""
        parts = [self.title, self.executive_summary, *self.measured_fact_statements,
                 *self.assumptions, *self.risks]
        for h in self.hypotheses:
            parts.append(h.statement)
            if h.check:
                parts.append(h.check)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Grounding check — the mechanical defence against an invented number.
# ---------------------------------------------------------------------------

#: A number token, optionally with a k/M/B/thousand multiplier suffix, and its
#: trailing context (up to a short currency/percent word). We capture the suffix
#: and the following unit so "25 000 AED", "12k AED" and "30%" are all caught.
#: Thousands separators may be commas OR spaces (LLMs use both).
_NUMBER_RE = re.compile(
    r"(?P<num>\d[\d,]*(?:[  ]\d{3})*(?:\.\d+)?)\s*(?P<suffix>[kKmMbB]\b)?\s*(?P<unit>%|[A-Za-z$]{1,8})?"
)

#: A trailing token that turns even a small number into a financial/statistical
#: CLAIM that must be grounded — "save 25 AED", "up 3%". Neutral units (units,
#: days, stores, items) are NOT here: "top 3 stores", "over 14 days" stay noise.
_CLAIM_UNIT_RE = re.compile(r"^(%|aed|usd|eur|gbp|sar|dirhams?|dollars?|pct|percent|\$)$", re.I)

_SUFFIX_MULT = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _numeric_forms(value: float) -> set:
    """The string forms a value may legitimately appear as in prose."""
    forms = set()
    for candidate in (value, round(value), round(value, 1), round(value, 2)):
        try:
            as_float = float(candidate)
        except (TypeError, ValueError):
            continue
        forms.add(f"{as_float:g}")
        if as_float == int(as_float):
            forms.add(str(int(as_float)))
        forms.add(f"{abs(as_float):g}")
        if abs(as_float) == int(abs(as_float)):
            forms.add(str(int(abs(as_float))))
    return forms


def ungrounded_numbers(narrative: str, evidence: List[EvidenceItem],
                       extra_allowed: Optional[List[float]] = None) -> List[str]:
    """Return the numbers in `narrative` that no evidence value supports.

    Polices LLM-written prose: the model may summarise the numbers it was given,
    never mint new ones. A non-empty result means the narrative is discarded in
    favour of the deterministic template (fail safe, not fail loud).

    Design after the Phase-1 review closed several smuggling holes:
      * thousands separators (comma OR space) are normalised before comparison,
        so "25 000 AED" is read as 25000, not "25" + "000";
      * k/M/B suffixes are expanded, so "12k AED" is 12000;
      * a number adjacent to a currency or percent word must be grounded even if
        it is small — "save 25 AED", "up 30%" no longer hide in the ordinal band;
      * only genuinely neutral small integers (0-31, e.g. "top 3 stores",
        "over 14 days") pass without grounding. There is no year allowlist —
        pass the current year via `extra_allowed` if a narrative needs it.
    """
    allowed: set = set()
    for item in evidence:
        for value in (item.current_value, item.comparison_value):
            if value is not None:
                allowed |= _numeric_forms(value)
    for value in extra_allowed or []:
        allowed |= _numeric_forms(value)

    ungrounded: List[str] = []
    for m in _NUMBER_RE.finditer(narrative or ""):
        token = m.group("num").rstrip(".")
        if not token:
            continue
        # Normalise comma AND space thousands groupings to a bare number.
        normalised = re.sub(r"[,\s]", "", token)
        try:
            base = float(normalised)
        except ValueError:
            continue
        suffix = (m.group("suffix") or "").lower()
        value = base * _SUFFIX_MULT.get(suffix, 1)
        unit = m.group("unit") or ""
        is_claim = bool(_CLAIM_UNIT_RE.match(unit))
        display = token + (m.group("suffix") or "")

        forms = _numeric_forms(value)
        if suffix:
            forms |= _numeric_forms(base)   # "12k" grounded by either 12000 or 12
        if forms & allowed:
            continue

        # A number next to money/percent is a claim — grounded or it is reported,
        # no ordinal escape hatch.
        if is_claim:
            ungrounded.append(display)
            continue
        if suffix:                          # a multiplier is never "noise"
            ungrounded.append(display)
            continue
        if 0 <= value <= 31 and value == int(value):
            continue                        # neutral small integers / list indices
        ungrounded.append(display)
    return ungrounded
