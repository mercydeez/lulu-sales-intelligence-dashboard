"""
Reciprocal Rank Fusion for hybrid retrieval (Sage Stage 1).
See docs/product/specs/STAGE1_SEMANTIC_LAYER.md.

Pure, dependency-free, and additive — this does NOT touch retriever.py. Atharva
wires it: run the existing FTS query and the new vector query independently,
each producing an ordered list of result keys (best first), then fuse them here
into one ranking. RRF needs only the RANK positions, not comparable scores —
which is exactly why it's robust for combining a ts_rank list with a cosine
list (two incomparable score scales).

Formula (Cormack et al. 2009): score(d) = Σ_r  weight_r / (k + rank_r(d))
with rank 1-based and k a smoothing constant (60 is the well-tested default).
"""
from __future__ import annotations

from typing import Dict, Hashable, List, Optional, Sequence, Tuple, TypeVar

K = TypeVar("K", bound=Hashable)

DEFAULT_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[K]],
    *,
    k: int = DEFAULT_K,
    weights: Optional[Sequence[float]] = None,
    top_k: Optional[int] = None,
) -> List[Tuple[K, float]]:
    """Fuse several ranked lists into one.

    Args:
        rankings: each inner sequence is result keys ordered best-first. A key
            may appear in several lists (that's the point — agreement boosts it)
            or just one. Keys must be hashable (e.g. a document id, or a
            (title, chunk_no) tuple).
        k: RRF smoothing constant. Larger k flattens the contribution of top
            ranks (less aggressive); 60 is the standard.
        weights: optional per-list weight (same length as `rankings`). Use to
            down-weight the vector arm when the embedder is the low-quality
            hashed fallback (semantic=False), or to trust FTS more for exact
            keyword hits. Defaults to 1.0 each.
        top_k: if set, return only the best `top_k` fused results.

    Returns:
        [(key, fused_score), ...] sorted by score desc. Ties broken by the key's
        best (lowest) rank across lists, then by the key itself, so the order is
        deterministic.
    """
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must match rankings length")
    w = list(weights) if weights is not None else [1.0] * len(rankings)

    scores: Dict[K, float] = {}
    best_rank: Dict[K, int] = {}
    for li, ranking in enumerate(rankings):
        for idx, key in enumerate(ranking):
            rank = idx + 1  # 1-based
            scores[key] = scores.get(key, 0.0) + w[li] / (k + rank)
            if key not in best_rank or rank < best_rank[key]:
                best_rank[key] = rank

    ordered = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], best_rank[kv[0]], _tiebreak(kv[0])),
    )
    return ordered[:top_k] if top_k is not None else ordered


def _tiebreak(key: Hashable) -> str:
    """Stable, type-agnostic final tiebreak so ordering never depends on dict
    insertion or raises when keys aren't mutually comparable."""
    return repr(key)


def fuse_keys(
    rankings: Sequence[Sequence[K]],
    *,
    k: int = DEFAULT_K,
    weights: Optional[Sequence[float]] = None,
    top_k: Optional[int] = None,
) -> List[K]:
    """Same as reciprocal_rank_fusion but returns just the ordered keys."""
    return [key for key, _ in reciprocal_rank_fusion(rankings, k=k, weights=weights, top_k=top_k)]
