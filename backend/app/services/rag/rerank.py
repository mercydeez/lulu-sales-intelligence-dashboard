"""
Reranking + context assembly (RAG-6).
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §1.7-1.8.

After hybrid retrieval + RRF (RAG-4), rerank the fused candidates for precision,
then assemble a token-budgeted, citation-carrying context block.

Reranker: ships a dependency-free LEXICAL cross-encoder-lite (query-term
coverage + density, length-normalized) — the biggest accuracy lever after hybrid
without a model server. `rerank()` takes an optional `scorer` so a real
cross-encoder (bge-reranker / cohere-rerank) drops in behind the same interface.

Context assembly: dedup near-identical chunks, order for the "lost in the middle"
effect (strongest evidence FIRST and LAST), enforce a char/token budget, and
attach a stable citation id to every included chunk.

Pure and unit-testable.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_STOP = set("the a an and or of to in for on is are was were be as at by with this "
            "that it its from your our their they we you i how what when which".split())


def _terms(s: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP and len(w) > 2]


def lexical_score(query: str, content: str) -> float:
    """Cross-encoder-lite: fraction of query terms present (coverage) weighted by
    their density in the passage, length-normalized. Range ~[0,1+]."""
    q = _terms(query)
    if not q:
        return 0.0
    c = _terms(content)
    if not c:
        return 0.0
    cset = set(c)
    covered = sum(1 for t in set(q) if t in cset)
    coverage = covered / len(set(q))
    # density: how concentrated the query terms are (reward focused passages)
    hits = sum(1 for t in c if t in set(q))
    density = hits / (len(c) ** 0.5)  # sqrt length-normalization
    return coverage * (1.0 + min(density, 1.0))


def rerank(
    query: str,
    chunks: Sequence[dict],
    top_k: int = 5,
    *,
    scorer: Optional[Callable[[str, str], float]] = None,
) -> List[dict]:
    """Reorder chunks by rerank score (desc), return top_k. Each returned chunk
    gets a `rerank_score`. `scorer(query, content)->float` overrides the default
    lexical scorer (plug a cross-encoder here)."""
    score = scorer or lexical_score
    scored = []
    for c in chunks:
        s = score(query, c.get("content", ""))
        cc = dict(c)
        cc["rerank_score"] = round(float(s), 4)
        scored.append(cc)
    scored.sort(key=lambda x: (-x["rerank_score"], _cite(x)))
    return scored[:top_k]


def _cite(c: dict) -> str:
    return f"{c.get('title', 'doc')} (chunk {c.get('chunk_no', 0)})"


def _dedup(chunks: Sequence[dict]) -> List[dict]:
    """Drop near-identical chunks (same normalized content prefix)."""
    seen = set()
    out = []
    for c in chunks:
        key = " ".join(_terms(c.get("content", ""))[:30])
        if key and key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _interleave_for_recency(chunks: List[dict]) -> List[dict]:
    """Lost-in-the-middle: put the strongest evidence at the START and END, weak
    in the middle. chunks are assumed already rank-ordered (best first)."""
    if len(chunks) <= 2:
        return chunks
    head: List[dict] = []
    tail: List[dict] = []
    for i, c in enumerate(chunks):
        (head if i % 2 == 0 else tail).append(c)
    tail.reverse()
    return head + tail


def assemble_context(
    query: str,
    chunks: Sequence[dict],
    *,
    budget_chars: int = 6000,
    rerank_first: bool = True,
    top_k: int = 6,
) -> Tuple[str, List[dict], List[str]]:
    """Rerank (optional) -> dedup -> budget -> order for recency -> build the
    context string with inline citations.

    Returns (context_text, included_chunks, citations). The context string is
    delimited per chunk with its citation id so the narrator can cite it.
    """
    ranked = rerank(query, chunks, top_k=top_k) if rerank_first else list(chunks)
    ranked = _dedup(ranked)

    # Budget: greedily include highest-ranked chunks until the char budget.
    included: List[dict] = []
    used = 0
    for c in ranked:
        body = c.get("content", "")
        cost = len(body) + 80  # citation + delimiter overhead
        if included and used + cost > budget_chars:
            break
        included.append(c)
        used += cost

    ordered = _interleave_for_recency(included)
    citations = [_cite(c) for c in ordered]
    context_text = "\n\n".join(f"[{_cite(c)}]\n{c.get('content','')}" for c in ordered)
    return context_text, ordered, citations
