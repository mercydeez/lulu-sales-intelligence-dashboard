"""Unit tests for RAG observability (OBS-1). Pure — no metrics backend needed."""
from app.services.rag.observability import RagTrace, refusal_rate, cache_hit_rate


def test_trace_assembles_pipeline_signals():
    t = RagTrace(trace_id="abc", tenant_id=1, role="regional_manager")
    t.start("retrieval"); t.stop("retrieval")
    t.record_retrieval(fts=12, vec=8, fused=5, semantic=True)
    t.reranked_returned = 5
    t.faithfulness = 0.72
    t.trip("numeric_units_sanity")
    t.cache_hit = True
    t.answer_chars = 240
    t.citations = 3
    d = t.to_dict()
    assert d["trace_id"] == "abc"
    assert d["retrieval"] == {"fts": 12, "vec": 8, "fused": 5, "reranked": 5, "semantic": True}
    assert d["faithfulness"] == 0.72
    assert d["guardrail_trips"] == ["numeric_units_sanity"]
    assert d["cache_hit"] is True
    assert "retrieval" in d["stages_ms"] and d["total_ms"] >= 0


def test_refuse_sets_reason():
    t = RagTrace(trace_id="x")
    t.refuse("low grounding overlap")
    assert t.refused is True and t.to_dict()["refusal_reason"] == "low grounding overlap"


def test_emit_never_raises_without_metrics_backend():
    # emit() best-effort hooks Prometheus if present; must not raise otherwise.
    d = RagTrace(trace_id="e").emit()
    assert d["trace_id"] == "e"


def test_health_rates():
    a = RagTrace(trace_id="1"); a.refused = True; a.cache_hit = True
    b = RagTrace(trace_id="2")
    assert refusal_rate([a, b]) == 0.5
    assert cache_hit_rate([a, b]) == 0.5
    assert refusal_rate([]) == 0.0
