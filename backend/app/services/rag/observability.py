"""
RAG observability (OBS-1) — a per-answer trace + metrics.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §1.16.

One `RagTrace` per Sage answer stitches the whole pipeline together:
query → retrieval (latency, #candidates, fused/rerank scores) → guardrail trips
→ faithfulness → refusal/answer → cache hit → tokens/cost. It emits one
structured log line (a rising refusal-rate = a retrieval gap, not a model
problem) and returns a dict callers can forward to Prometheus (services/metrics)
/ Sentry / the telemetry pipeline.

Pure/importable; the trace assembly is unit-testable. Scale note (§1.13): vector
reads are pure SELECTs (route to a read replica); rerank/embed belong on a
worker queue — the trace's latency fields tell you when to.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("rag.trace")


@dataclass
class RagTrace:
    trace_id: str
    tenant_id: int = 0
    role: str = ""
    query_lang: str = "en"
    # filled as the pipeline runs
    stages_ms: Dict[str, float] = field(default_factory=dict)
    fts_candidates: int = 0
    vec_candidates: int = 0
    fused_returned: int = 0
    reranked_returned: int = 0
    embedder_semantic: bool = False
    faithfulness: Optional[float] = None
    guardrail_trips: List[str] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""
    cache_hit: bool = False
    answer_chars: int = 0
    citations: int = 0
    _t0: Dict[str, float] = field(default_factory=dict, repr=False)

    # ---- timing ----
    def start(self, stage: str) -> None:
        self._t0[stage] = time.perf_counter()

    def stop(self, stage: str) -> None:
        if stage in self._t0:
            self.stages_ms[stage] = round((time.perf_counter() - self._t0.pop(stage)) * 1000, 1)

    # ---- signals ----
    def record_retrieval(self, fts: int, vec: int, fused: int, semantic: bool) -> None:
        self.fts_candidates = fts
        self.vec_candidates = vec
        self.fused_returned = fused
        self.embedder_semantic = semantic

    def trip(self, guardrail: str) -> None:
        self.guardrail_trips.append(guardrail)

    def refuse(self, reason: str) -> None:
        self.refused = True
        self.refusal_reason = reason

    def to_dict(self) -> Dict:
        return {
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "role": self.role,
            "lang": self.query_lang,
            "stages_ms": self.stages_ms,
            "total_ms": round(sum(self.stages_ms.values()), 1),
            "retrieval": {
                "fts": self.fts_candidates, "vec": self.vec_candidates,
                "fused": self.fused_returned, "reranked": self.reranked_returned,
                "semantic": self.embedder_semantic,
            },
            "faithfulness": self.faithfulness,
            "guardrail_trips": self.guardrail_trips,
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "cache_hit": self.cache_hit,
            "answer_chars": self.answer_chars,
            "citations": self.citations,
        }

    def emit(self) -> Dict:
        """Log the structured trace + return it (for metrics/Sentry/telemetry)."""
        d = self.to_dict()
        logger.info("rag_trace %s", d)
        try:
            # Best-effort Prometheus counters if the metrics service is present.
            from app.services.metrics import get_metrics  # optional
            m = get_metrics()
            inc = getattr(m, "increment", None)
            if callable(inc):
                inc("rag_answers_total")
                if self.refused:
                    inc("rag_refusals_total")
                if self.cache_hit:
                    inc("rag_cache_hits_total")
                for g in self.guardrail_trips:
                    inc("rag_guardrail_trips_total")
        except Exception:
            pass  # observability must never break the answer path
        return d


def refusal_rate(traces: List[RagTrace]) -> float:
    """Health signal: a rising refusal rate is a RETRIEVAL gap (fix the corpus),
    not a model problem."""
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.refused) / len(traces)


def cache_hit_rate(traces: List[RagTrace]) -> float:
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.cache_hit) / len(traces)
