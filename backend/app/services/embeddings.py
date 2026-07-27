"""
Text embeddings for the Sage semantic layer (Stage 1).
See docs/product/specs/STAGE1_SEMANTIC_LAYER.md.

Design goals:
  • Additive and self-contained — no changes to rag/retriever.py (that wiring is
    Atharva's, per the spec). This module only turns text into vectors.
  • Always works, degrades honestly. With Ollama configured, real semantic
    embeddings (all-minilm, 384d). Without it, a DETERMINISTIC HASHED embedder
    (zero dependencies) so the whole pipeline runs end-to-end in dev/CI/demo —
    but it carries a distinct model tag so its low-quality vectors are never
    silently compared against real ones.
  • Cosine-ready: every vector is L2-normalized, so cosine distance and the
    HNSW `vector_cosine_ops` index agree.
  • Model-tagged: `EmbeddingResult.model` records the embedder. Vectors from
    different models live in different spaces and MUST be filtered by tag at
    query time (the migration stores `documents.embedding_model` for exactly
    this). This is what makes re-embedding a background swap, not an outage.

Nothing here executes at import time — safe to import anywhere.
"""
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import List, Optional

# 384 matches all-minilm and the migration's vector(384) column. Keep in sync
# with database/migrations/054_pgvector_semantic.sql if this ever changes.
EMBED_DIM = 384

# Model tags — persisted in documents.embedding_model. The hashed fallback is
# deliberately named so it can never be mistaken for a real semantic space.
HASHED_MODEL_TAG = "hashed-bow-384-v1"
OLLAMA_MODEL_TAG_PREFIX = "ollama:"


@dataclass
class EmbeddingResult:
    vectors: List[List[float]]
    model: str
    dim: int = EMBED_DIM
    # True only for a real semantic embedder; False for the hashed stand-in.
    # Callers gate "is semantic search meaningful?" on this.
    semantic: bool = False


def detect_lang(text: str) -> str:
    """Cheap script-based language hint for ingest tagging + embedder routing
    (RAG-2). Arabic content embedded by an English-only model (all-minilm)
    silently fails to retrieve — so we tag `lang` at ingest and, when a
    multilingual embedder is configured, route accordingly.

    Returns 'ar' if the text is predominantly Arabic script, else 'en'.
    Recommended multilingual embedders that fit the existing vector(384) schema:
    `multilingual-e5-small` or `bge-small` (both 384d). bge-m3 (1024d) would need
    a schema migration to vector(1024)."""
    if not text:
        return "en"
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")
    letters = sum(1 for ch in text if ch.isalpha())
    if letters and arabic / letters > 0.4:
        return "ar"
    return "en"


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


# --------------------------------------------------------------------------- #
# Deterministic hashed bag-of-words embedder (zero-dependency fallback).
# Not a real semantic model — it captures lexical overlap only. Its job is to
# make the ingest → store → retrieve → verify loop runnable without any model
# server, so the migration, backfill, and query paths can be exercised in CI.
# --------------------------------------------------------------------------- #
def _hashed_embed_one(text: str) -> List[float]:
    vec = [0.0] * EMBED_DIM
    if not text:
        return vec
    for token in _tokenize(text):
        # Two independent hashes → bucket + sign, the standard hashing-trick
        # feature map. Deterministic across processes (hashlib, not hash()).
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = struct.unpack("<Q", h)[0] % EMBED_DIM
        sign = 1.0 if (h[0] & 1) else -1.0
        vec[bucket] += sign
    return _l2_normalize(vec)


def _tokenize(text: str) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _hashed_embed(texts: List[str]) -> EmbeddingResult:
    return EmbeddingResult(
        vectors=[_hashed_embed_one(t) for t in texts],
        model=HASHED_MODEL_TAG,
        semantic=False,
    )


# --------------------------------------------------------------------------- #
# Ollama embedder (real semantics, local, PDPL-clean). Used when ENABLE_LOCAL_AI
# + OLLAMA_URL are set. Falls back to the hashed embedder on any failure so a
# model-server hiccup never breaks ingest.
# --------------------------------------------------------------------------- #
async def _ollama_embed(texts: List[str], base_url: str, model: str) -> Optional[EmbeddingResult]:
    try:
        import httpx  # already a dependency (see llm/ollama_provider.py)
    except Exception:
        return None
    url = base_url.rstrip("/") + "/api/embeddings"
    vectors: List[List[float]] = []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for t in texts:
                resp = await client.post(url, json={"model": model, "prompt": t})
                resp.raise_for_status()
                emb = resp.json().get("embedding")
                if not emb or len(emb) != EMBED_DIM:
                    # Dimension mismatch means a different model than the schema
                    # expects — refuse rather than store an incomparable vector.
                    return None
                vectors.append(_l2_normalize([float(x) for x in emb]))
    except Exception:
        return None
    return EmbeddingResult(vectors=vectors, model=f"{OLLAMA_MODEL_TAG_PREFIX}{model}", semantic=True)


def _settings():
    try:
        from app.config import get_settings
        return get_settings()
    except Exception:
        return None


async def embed_texts(texts: List[str]) -> EmbeddingResult:
    """Embed a batch. Tries the configured real embedder, falls back to the
    deterministic hashed one so this NEVER raises and NEVER returns mixed-space
    vectors (the whole batch shares one model tag).

    Callers persist `result.model` into documents.embedding_model and, at query
    time, embed the question with the SAME path and filter retrieval to that tag.
    """
    if not texts:
        return EmbeddingResult(vectors=[], model=HASHED_MODEL_TAG, semantic=False)

    s = _settings()
    # Defensive getattr: works whether or not these settings exist yet, so this
    # module needs no config.py change to land.
    enable_local = bool(getattr(s, "enable_local_ai", False)) if s else False
    ollama_url = getattr(s, "ollama_url", None) if s else None
    # A dedicated embed model if configured, else reuse the chat model name.
    embed_model = (
        getattr(s, "ollama_embed_model", None)
        or getattr(s, "ollama_model", None)
        or "all-minilm"
    ) if s else "all-minilm"

    if enable_local and ollama_url:
        got = await _ollama_embed(texts, ollama_url, embed_model)
        if got is not None:
            return got

    return _hashed_embed(texts)


async def embed_one(text: str) -> EmbeddingResult:
    """Convenience for a single query string."""
    return await embed_texts([text])


def to_pgvector_literal(vec: List[float]) -> str:
    """Render a vector as the pgvector text literal '[f1,f2,...]' for
    parametrized SQL (`CAST(:v AS vector)`)."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
