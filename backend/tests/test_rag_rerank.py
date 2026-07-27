"""Unit tests for reranking + context assembly (RAG-6). Pure — no DB/model."""
from app.services.rag.rerank import lexical_score, rerank, assemble_context


def test_reranker_ranks_on_topic_first():
    chunks = [
        {"title": "off", "chunk_no": 0, "content": "penguins in antarctica are very cold"},
        {"title": "on", "chunk_no": 0, "content": "ramadan dairy restock policy increase stock"},
    ]
    r = rerank("ramadan dairy restock", chunks, top_k=2)
    assert r[0]["title"] == "on"
    assert r[0]["rerank_score"] >= r[1]["rerank_score"]


def test_lexical_score_zero_for_no_overlap():
    assert lexical_score("ramadan restock", "quantum physics lecture") == 0.0
    assert lexical_score("", "anything") == 0.0


def test_custom_scorer_overrides_default():
    chunks = [{"title": "a", "chunk_no": 0, "content": "x"}, {"title": "b", "chunk_no": 0, "content": "y"}]
    # scorer that prefers title 'b'
    r = rerank("q", chunks, top_k=2, scorer=lambda q, c: 1.0 if c == "y" else 0.0)
    assert r[0]["title"] == "b"


def test_assemble_enforces_budget():
    many = [{"title": f"D{i}", "chunk_no": 0, "content": "ramadan dairy restock " * 50} for i in range(10)]
    _, inc, _ = assemble_context("ramadan restock", many, budget_chars=1200, top_k=6)
    assert 1 <= len(inc) < 10


def test_assemble_dedups_identical():
    dup = [
        {"title": "X", "chunk_no": 0, "content": "same same same content here now"},
        {"title": "Y", "chunk_no": 1, "content": "same same same content here now"},
    ]
    _, inc, _ = assemble_context("same", dup, budget_chars=9000)
    assert len(inc) == 1


def test_assemble_attaches_citations():
    chunks = [{"title": "Runbook", "chunk_no": 2, "content": "ramadan restock dairy"}]
    ctx, inc, cites = assemble_context("ramadan restock", chunks)
    assert cites == ["Runbook (chunk 2)"]
    assert "Runbook (chunk 2)" in ctx


def test_empty_chunks_yield_empty_context():
    ctx, inc, cites = assemble_context("q", [])
    assert ctx == "" and inc == [] and cites == []
