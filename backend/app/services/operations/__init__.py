"""Retail IQ Operations Copilot — human-in-the-loop operational actions.

Turns a verified deterministic finding into an evidence-backed recommendation, a
human-approved draft, an auditable execution and a measured outcome. The agent
never acts alone: no draft leaves the building, no approval is implied, and
every number shown to a human comes from deterministic code.

Layout:
  contracts.py  — the typed output contract + the invented-number check
  policy.py     — tenant-configurable approval ladder, safety rules, freshness
"""
from app.services.operations.contracts import (
    ActionType,
    OperationsRecommendation,
    ProposalStatus,
    RiskLevel,
    RunStatus,
)
from app.services.operations.policy import DEFAULT_POLICY, OperationsPolicy, get_policy

__all__ = [
    "ActionType",
    "OperationsRecommendation",
    "ProposalStatus",
    "RiskLevel",
    "RunStatus",
    "OperationsPolicy",
    "DEFAULT_POLICY",
    "get_policy",
]
