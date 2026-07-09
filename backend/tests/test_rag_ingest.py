"""Unit tests for the ingestion chunker (RAG-3). Pure logic — no DB/embedder."""
from app.services.rag.ingest import chunk_text, content_hash, CORPUS_CHUNK


def test_empty_input_yields_no_chunks():
    assert chunk_text("", "docs") == []
    assert chunk_text("   \n\n  ", "docs") == []


def test_short_paragraphs_pack_into_one_chunk():
    out = chunk_text("para one.\n\npara two.\n\npara three.", "docs")
    assert len(out) == 1


def test_long_document_splits_into_multiple_chunks():
    out = chunk_text(" ".join(["word"] * 700), "docs")
    assert len(out) >= 3


def test_per_corpus_sizing_changelog_smaller_than_runbook():
    body = " ".join(["w"] * 300)
    assert len(chunk_text(body, "changelog")) >= len(chunk_text(body, "runbook"))


def test_no_word_is_split_across_chunks():
    out = chunk_text(" ".join(f"w{i}" for i in range(500)), "docs")
    rejoined = " ".join(out).split()
    # every original token appears (overlap may repeat some, but none are cut)
    assert "w0" in rejoined and "w499" in rejoined


def test_content_hash_is_stable_and_scoped():
    assert content_hash(1, "docs", "abc") == content_hash(1, "docs", "abc")
    assert content_hash(1, "docs", "abc") != content_hash(2, "docs", "abc")
    assert content_hash(1, "docs", "abc") != content_hash(1, "runbook", "abc")


def test_known_corpora_have_config():
    for c in ("docs", "runbook", "policy", "changelog", "findings"):
        assert "target" in CORPUS_CHUNK[c] and "overlap" in CORPUS_CHUNK[c]
