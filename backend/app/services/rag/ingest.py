"""
RAG ingestion pipeline (RAG-3): text -> structural chunks -> embeddings ->
idempotent, ACL-tagged upsert into the `documents` chunk store.
See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §1.1-1.2, §3.3.

Design:
  • Structural chunking (split on blank-line paragraph boundaries, then pack to
    a per-corpus target size with overlap) — respects meaning better than fixed
    windows. Per-corpus sizing (a changelog line and a 40-page runbook need
    different granularity).
  • parent_ref links every chunk to its source doc, enabling parent-document
    retrieval later (RAG-6).
  • content_hash makes upsert idempotent — re-ingesting unchanged text is a
    no-op, and it doubles as the embedding-cache key (GR-5).
  • ACL metadata (visibility_roles / store_scope / sensitivity) is set at ingest
    from the source's access rules — the security boundary lives with the data.

`chunk_text` is pure and unit-testable; `ingest_document` does the DB/embed work.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

# Per-corpus chunk sizing in ~words (target, overlap). Tune from eval (§1.2).
CORPUS_CHUNK = {
    "docs":      {"target": 220, "overlap": 40},
    "runbook":   {"target": 320, "overlap": 60},
    "policy":    {"target": 260, "overlap": 50},
    "changelog": {"target": 120, "overlap": 0},
    "findings":  {"target": 160, "overlap": 20},
    "exemplar":  {"target": 200, "overlap": 0},
    "state":     {"target": 200, "overlap": 20},
}
_DEFAULT = {"target": 220, "overlap": 40}


def _words(s: str) -> List[str]:
    return s.split()


def chunk_text(content: str, corpus: str = "docs") -> List[str]:
    """Structural chunking: paragraph-aware packing to a per-corpus word target
    with overlap. Never splits mid-word; keeps whole short paragraphs together.
    Returns [] for empty/whitespace input.
    """
    if not content or not content.strip():
        return []
    cfg = CORPUS_CHUNK.get(corpus, _DEFAULT)
    target, overlap = cfg["target"], cfg["overlap"]

    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    if not paras:
        paras = [content.strip()]

    chunks: List[str] = []
    buf: List[str] = []      # word buffer for the current chunk
    for para in paras:
        pw = _words(para)
        # A single huge paragraph: hard-split it into target-sized windows.
        if len(pw) > target:
            if buf:
                chunks.append(" ".join(buf)); buf = []
            i = 0
            step = max(1, target - overlap)
            while i < len(pw):
                chunks.append(" ".join(pw[i:i + target]))
                i += step
            continue
        # Would this paragraph overflow the buffer? flush first (with overlap).
        if buf and len(buf) + len(pw) > target:
            chunks.append(" ".join(buf))
            buf = buf[-overlap:] if overlap else []
        buf.extend(pw)
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def content_hash(tenant_id: int, corpus: str, text: str) -> str:
    return hashlib.blake2b(
        f"{tenant_id}\x00{corpus}\x00{text}".encode("utf-8"), digest_size=16
    ).hexdigest()


@dataclass
class IngestResult:
    chunks_written: int
    chunks_skipped: int   # already present (idempotent)
    model: str


async def ingest_document(
    tenant_id: int,
    title: str,
    content: str,
    *,
    corpus: str = "docs",
    sensitivity: str = "internal",
    visibility_roles: Optional[Sequence[str]] = None,
    store_scope: Optional[Sequence[int]] = None,
    lang: str = "en",
    parent_ref: Optional[str] = None,
) -> IngestResult:
    """Chunk -> embed -> idempotent ACL-tagged upsert. Returns counts."""
    from sqlalchemy import text as sql
    from app.services.database import async_session
    from app.services.embeddings import embed_texts, to_pgvector_literal

    chunks = chunk_text(content, corpus)
    if not chunks:
        return IngestResult(0, 0, "")
    emb = await embed_texts(chunks)
    pref = parent_ref or f"{corpus}:{title}"

    written = skipped = 0
    async with async_session() as s:
        for idx, (chunk, vec) in enumerate(zip(chunks, emb.vectors)):
            chash = content_hash(tenant_id, corpus, chunk)
            exists = (await s.execute(sql(
                "SELECT 1 FROM documents WHERE tenant_id=:t AND content_hash=:h AND embedding_model=:m LIMIT 1"
            ), {"t": tenant_id, "h": chash, "m": emb.model})).first()
            if exists:
                skipped += 1
                continue
            await s.execute(sql("""
                INSERT INTO documents
                  (tenant_id, title, chunk_no, content, corpus, sensitivity,
                   visibility_roles, store_scope, lang, parent_ref, content_hash,
                   embedding, embedding_model, embedded_at, acl_updated_at)
                VALUES
                  (:t, :title, :cn, :content, :corpus, :sens,
                   :vroles, :sscope, :lang, :pref, :chash,
                   CAST(:vec AS vector), :model, now(), now())
            """), {
                "t": tenant_id, "title": title, "cn": idx, "content": chunk,
                "corpus": corpus, "sens": sensitivity,
                "vroles": list(visibility_roles) if visibility_roles else None,
                "sscope": list(store_scope) if store_scope else None,
                "lang": lang, "pref": pref, "chash": chash,
                "vec": to_pgvector_literal(vec), "model": emb.model,
            })
            written += 1
        await s.commit()
    return IngestResult(chunks_written=written, chunks_skipped=skipped, model=emb.model)
