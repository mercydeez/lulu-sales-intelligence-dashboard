"""Unit tests for Reciprocal Rank Fusion (Sage Stage 1 hybrid retrieval).
Pure logic — no DB, no model server."""
import pytest

from app.services.rag.fusion import reciprocal_rank_fusion, fuse_keys, DEFAULT_K


def test_agreement_wins():
    # A is high in both lists; C is #1 in vector but #3 in FTS. Agreement lifts A.
    fts = ["A", "B", "C", "D"]
    vector = ["C", "A", "E", "F"]
    fused = fuse_keys([fts, vector])
    assert fused[0] == "A"
    # every candidate from either list survives
    assert set(fused) == {"A", "B", "C", "D", "E", "F"}


def test_weight_zero_disables_a_list():
    fts = ["A", "B", "C", "D"]
    vector = ["C", "A", "E", "F"]
    assert fuse_keys([fts, vector], weights=[1.0, 0.0])[:4] == ["A", "B", "C", "D"]


def test_tuple_keys_and_agreement():
    # (doc,1) appears in both lists -> outranks (doc,0) which is only in one.
    fused = fuse_keys([[("doc", 0), ("doc", 1)], [("doc", 1)]])
    assert fused[0] == ("doc", 1)


def test_deterministic():
    a = reciprocal_rank_fusion([["X"], ["Y"]])
    b = reciprocal_rank_fusion([["X"], ["Y"]])
    assert a == b


def test_top_k_truncates():
    assert len(fuse_keys([["A", "B", "C", "D"]], top_k=2)) == 2


def test_empty_inputs():
    assert reciprocal_rank_fusion([]) == []
    assert fuse_keys([[], []]) == []


def test_weights_length_mismatch_raises():
    with pytest.raises(ValueError):
        fuse_keys([["a"], ["b"]], weights=[1.0])


def test_scores_use_rrf_formula():
    # Single list: score(rank i, 1-based) = 1/(k+i). Verify the top item's score.
    scored = reciprocal_rank_fusion([["A", "B"]])
    assert scored[0][0] == "A"
    assert scored[0][1] == pytest.approx(1.0 / (DEFAULT_K + 1))
