"""
Sage v2 — decompose-route-recompose answering for multi-part business questions
across the in-depth semantic layer (sales, distributors, CRM, online pricing,
targets, documents). Grounded + provider-agnostic.
"""
from .orchestrator import MultiPartResult, SubAnswer, answer_multipart, is_multipart

__all__ = ["answer_multipart", "is_multipart", "MultiPartResult", "SubAnswer"]
