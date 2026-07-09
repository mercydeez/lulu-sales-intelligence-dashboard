"""Default guardrail pipeline assembly (GR-1..GR-4).

The order below is the layered defense (§2.8): input gate → output gate.
Retrieval-phase ACL is enforced in rag/acl.py (pre-retrieval, not here).
"""
from __future__ import annotations

from .pipeline import GuardrailPipeline
from . import rails


def default_pipeline() -> GuardrailPipeline:
    return GuardrailPipeline([
        # INPUT gate
        rails.pii_input_redaction(),
        rails.prompt_injection(),
        rails.query_length_limit(),
        rails.topical_scope(),
        # OUTPUT gate
        rails.pii_output_leak(),
        rails.citation_enforcement(),
        rails.faithfulness_lexical(),
        rails.numeric_units_sanity(),
    ])
