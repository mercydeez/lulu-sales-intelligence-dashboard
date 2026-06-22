"""
Federated Sage: answer NL questions across multiple data sources (the app DB and
any connected databases) under one canonical schema, role-scoped and grounded —
the LLM proposes one canonical SQL, each source executes it, rows are merged and
narrated with per-source attribution and discrepancy detection.
"""
from .base import SourceAdapter, SourceDescriptor, SourceResult
from .orchestrator import FederatedResult, federated_answer
from . import catalog, policy

__all__ = [
    "federated_answer", "FederatedResult",
    "SourceAdapter", "SourceDescriptor", "SourceResult",
    "catalog", "policy",
]
