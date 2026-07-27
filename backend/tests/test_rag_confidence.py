"""ZH-3: source-confidence scoring unit tests (pure, no DB)."""
from datetime import datetime, timedelta, timezone

from app.services.rag.confidence import (
    ANSWER_CONFIDENCE_THRESHOLD, CHUNK_CONFIDENCE_FLOOR,
    answer_confidence, filter_confident, score_chunk,
)

NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _chunk(**kw):
    base = dict(content="restock dairy when stock dips below par level",
                corpus="policy", created_at=NOW - timedelta(days=10),
                in_fts=True, in_vec=True)
    base.update(kw)
    return base


def test_corroborated_fresh_policy_scores_high():
    s = score_chunk("restock dairy policy", _chunk(), now=NOW)
    assert s > 0.7


def test_single_arm_scores_lower_than_both_arms():
    both = score_chunk("restock dairy policy", _chunk(), now=NOW)
    one = score_chunk("restock dairy policy", _chunk(in_vec=False), now=NOW)
    assert one < both


def test_stale_changelog_decays_below_fresh_policy():
    fresh = score_chunk("restock dairy", _chunk(), now=NOW)
    stale = score_chunk("restock dairy", _chunk(
        corpus="changelog", created_at=NOW - timedelta(days=300)), now=NOW)
    assert stale < fresh


def test_unrelated_chunk_falls_below_floor_and_is_dropped():
    kept, dropped = filter_confident("ramadan cold chain compliance", [
        _chunk(),  # unrelated to the query, single topic overlap ~0
        _chunk(content="penguin migratory patterns in antarctica",
               corpus="exemplar", in_fts=False, in_vec=False,
               created_at=NOW - timedelta(days=400)),
    ], now=NOW)
    assert all(c["confidence"] >= CHUNK_CONFIDENCE_FLOOR for c in kept)
    assert any(c["confidence"] < CHUNK_CONFIDENCE_FLOOR for c in dropped)


def test_answer_confidence_gate_semantics():
    assert answer_confidence([]) == 0.0
    strong = [{"confidence": 0.9}, {"confidence": 0.8}, {"confidence": 0.7}]
    weak = [{"confidence": 0.31}]
    assert answer_confidence(strong) >= ANSWER_CONFIDENCE_THRESHOLD
    assert answer_confidence(weak) < ANSWER_CONFIDENCE_THRESHOLD


def test_scores_annotated_and_order_preserved():
    chunks = [_chunk(content="restock policy alpha"), _chunk(content="restock policy beta")]
    kept, _ = filter_confident("restock policy", chunks, now=NOW)
    assert [c["content"] for c in kept] == ["restock policy alpha", "restock policy beta"]
    assert all(0.0 <= c["confidence"] <= 1.0 for c in kept)
