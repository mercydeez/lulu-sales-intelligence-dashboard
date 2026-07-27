"""
Scoped caching for RAG (GR-5) — embedding cache + RBAC-scoped answer cache.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §1.12, §3.2(6).

Two caches, both on the existing Redis:
  1. Embedding cache: content_hash -> vector. Never re-embed unchanged text.
  2. Answer cache: (normalized question + ACL filter_hash + tenant) -> a
     previously VERIFIED answer. **The key includes the ACL filter_hash** so a
     manager and an admin asking the same question get separately-scoped
     answers — an unscoped cache is the classic RAG cross-role leak. Fail-safe:
     any scope mismatch is a MISS.

Key derivation is pure/testable; get/set use Redis (cache_set/cache_get already
JSON-serialize with TTL and no-op when Redis is down — fail-open on cache).

NOTE: this is exact-normalized-question scoping (leak-safe). The cosine-near
"semantic" upgrade stores the query embedding and does an ANN lookup WITHIN the
filter_hash bucket — same security key, fuzzier match. Deferred; keys are ready.
"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional

_EMB_TTL = 30 * 24 * 3600  # embeddings are stable; cache long
_ANS_TTL = 3600            # answers: 1h (data changes)


def _normalize_q(q: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (q or "").lower()))


def embedding_key(content_hash: str, model: str) -> str:
    return f"rag:emb:{model}:{content_hash}"


def answer_key(query: str, acl_filter_hash: str, tenant_id: int) -> str:
    """Answer-cache key. The ACL filter_hash is IN the key — this is the
    cross-role leak guard. Same question + different authorization => different
    key => miss."""
    h = hashlib.blake2b(
        f"{tenant_id}\x00{acl_filter_hash}\x00{_normalize_q(query)}".encode("utf-8"),
        digest_size=16,
    ).hexdigest()
    return f"rag:ans:{h}"


async def embedding_cache_get(content_hash: str, model: str) -> Optional[List[float]]:
    from app.services.redis_client import cache_get
    v = await cache_get(embedding_key(content_hash, model))
    return v if isinstance(v, list) else None


async def embedding_cache_set(content_hash: str, model: str, vector: List[float]) -> None:
    from app.services.redis_client import cache_set
    await cache_set(embedding_key(content_hash, model), list(vector), expire=_EMB_TTL)


async def answer_cache_get(query: str, acl_filter_hash: str, tenant_id: int) -> Optional[dict]:
    """Return a cached {answer, citations} for this EXACT authorization scope, or
    None. A different role/tenant/store set yields a different key => miss."""
    from app.services.redis_client import cache_get
    v = await cache_get(answer_key(query, acl_filter_hash, tenant_id))
    return v if isinstance(v, dict) else None


async def answer_cache_set(query: str, acl_filter_hash: str, tenant_id: int,
                           answer: str, citations: List[str], ttl: int = _ANS_TTL,
                           confidence: float = 1.0, chunks: Optional[List[dict]] = None) -> None:
    """Cache a VERIFIED answer scoped to this authorization. Callers must only
    cache answers that PASSED the output guardrails (grounded + cited).
    `confidence` (stage-4 score) rides along so a cache hit reports the same
    evidence strength as the original answer. `chunks` (the source text) rides
    along too so a cache hit can still be checked by sage3's critic/
    cross_validator — without it a cached answer looks unevidenced and gets a
    false "unverified" caveat."""
    from app.services.redis_client import cache_set
    await cache_set(
        answer_key(query, acl_filter_hash, tenant_id),
        {"answer": answer, "citations": list(citations), "confidence": confidence,
         "chunks": chunks or []},
        expire=ttl,
    )
