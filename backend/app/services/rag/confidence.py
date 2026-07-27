"""
Source-confidence scoring (zero-hallucination stage 4).
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md.

Every retrieved chunk gets a confidence in [0, 1] from four signals, and
low-confidence evidence is FILTERED before it can reach the generator — a
weakly-related paragraph that slips into the context is exactly how grounded
answers drift into hallucination.

Signals (weights sum to 1):
  * consistency 0.35 — retrieved by BOTH arms (keyword AND semantic) is
    corroborated; by one arm only is plausible; the fused straggler is weak.
  * overlap     0.30 — lexical query↔chunk relatedness (rag/rerank scorer).
  * trust       0.20 — per-corpus authority (a policy doc outranks a chat
    exemplar for factual claims).
  * freshness   0.15 — exponential age decay with per-corpus half-life (a
    changelog goes stale in weeks; a policy holds for a year).

Pure functions — unit-testable, no DB. The pipeline (rag/pipeline.py) applies
`filter_confident` and gates the answer on `answer_confidence`.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.rag.rerank import lexical_score

# Per-corpus authority for factual answering (deny-list unknown → modest).
CORPUS_TRUST: Dict[str, float] = {
    "policy": 1.0, "runbook": 1.0, "docs": 0.9, "findings": 0.8,
    "state": 0.7, "exemplar": 0.6, "changelog": 0.6,
}
_DEFAULT_TRUST = 0.7

# Freshness half-life in days — how fast this corpus's truth decays.
CORPUS_HALF_LIFE_DAYS: Dict[str, float] = {
    "policy": 365, "runbook": 365, "docs": 180, "findings": 60,
    "state": 30, "exemplar": 180, "changelog": 30,
}
_DEFAULT_HALF_LIFE = 180.0

# Below this, a chunk is not evidence — it never reaches the generator.
CHUNK_CONFIDENCE_FLOOR = 0.30
# Below this aggregate, the pipeline refuses instead of answering (stage 7).
ANSWER_CONFIDENCE_THRESHOLD = 0.45

WEIGHTS = {"consistency": 0.35, "overlap": 0.30, "trust": 0.20, "freshness": 0.15}


def _freshness(created_at: Optional[datetime], corpus: str, now: Optional[datetime] = None) -> float:
    if created_at is None:
        return 0.5  # unknown age: neither reward nor kill
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    half_life = CORPUS_HALF_LIFE_DAYS.get(corpus, _DEFAULT_HALF_LIFE)
    return math.pow(0.5, age_days / half_life)


def _consistency(in_fts: bool, in_vec: bool) -> float:
    if in_fts and in_vec:
        return 1.0
    if in_fts or in_vec:
        return 0.6
    return 0.3  # fused in without arm membership recorded


def score_chunk(query: str, chunk: dict, now: Optional[datetime] = None) -> float:
    """Confidence in [0,1] for one retrieved chunk dict (as returned by
    search_documents: content/corpus/created_at/in_fts/in_vec)."""
    corpus = chunk.get("corpus") or "docs"
    s = (
        WEIGHTS["consistency"] * _consistency(bool(chunk.get("in_fts")), bool(chunk.get("in_vec")))
        + WEIGHTS["overlap"] * min(1.0, lexical_score(query, chunk.get("content") or ""))
        + WEIGHTS["trust"] * CORPUS_TRUST.get(corpus, _DEFAULT_TRUST)
        + WEIGHTS["freshness"] * _freshness(chunk.get("created_at"), corpus, now)
    )
    return round(min(1.0, max(0.0, s)), 4)


def filter_confident(
    query: str,
    chunks: Sequence[dict],
    floor: float = CHUNK_CONFIDENCE_FLOOR,
    now: Optional[datetime] = None,
) -> Tuple[List[dict], List[dict]]:
    """Score every chunk (annotates chunk['confidence']) and split into
    (kept, dropped). Order is preserved."""
    kept: List[dict] = []
    dropped: List[dict] = []
    for c in chunks:
        c["confidence"] = score_chunk(query, c, now)
        (kept if c["confidence"] >= floor else dropped).append(c)
    return kept, dropped


def answer_confidence(kept: Sequence[dict]) -> float:
    """Aggregate evidence strength for the stage-7 gate: the best chunk carries
    the answer, corroborating chunks raise it slightly."""
    if not kept:
        return 0.0
    scores = sorted((c.get("confidence", 0.0) for c in kept), reverse=True)
    best = scores[0]
    support = sum(scores[1:3]) / 2 if len(scores) > 1 else 0.0
    return round(min(1.0, 0.8 * best + 0.2 * support), 4)
