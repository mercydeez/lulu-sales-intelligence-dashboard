"""
Embedding backfill for the Sage semantic layer (Stage 1).
See docs/product/specs/STAGE1_SEMANTIC_LAYER.md.

Fills `documents.embedding` for rows that don't have one yet (fresh install,
newly ingested docs, or a model swap). Additive and self-contained — it only
writes the embedding columns migration 054 added; it never touches the FTS
path, so retrieval keeps working throughout a backfill.

Safe by construction:
  • If pgvector / the embedding column isn't present, it no-ops and reports
    `skipped` — never raises, never blocks startup.
  • Batched, with a max-batch cap so a one-shot run can't monopolize the DB.
  • The whole batch shares ONE embedder/model tag (embed_texts guarantees this),
    so a row's vector and its `embedding_model` always agree.

Intended callers: an admin endpoint ("re-index knowledge") and/or a lifespan
task gated behind a flag — both Atharva's to wire. This module just does the work.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy import text

from app.services.database import async_session
from app.services.embeddings import embed_texts, to_pgvector_literal

logger = logging.getLogger(__name__)


async def _embedding_column_exists() -> bool:
    """True only if migration 054 applied AND pgvector created the column
    (the migration succeeds even without pgvector, leaving no column)."""
    try:
        async with async_session() as s:
            row = (await s.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'embedding'
            """))).first()
            return row is not None
    except Exception:
        return False


async def embed_pending(batch_size: int = 64, max_batches: Optional[int] = None) -> Dict:
    """Embed documents whose `embedding IS NULL`, batch by batch.

    Returns a small report: {"status", "embedded", "batches", "model"}.
    `status` is one of: "skipped" (no column), "done" (nothing left / finished),
    "partial" (hit max_batches with rows remaining).
    """
    if batch_size <= 0:
        batch_size = 64

    if not await _embedding_column_exists():
        return {"status": "skipped", "embedded": 0, "batches": 0, "model": None}

    total = 0
    batches = 0
    last_model: Optional[str] = None

    while max_batches is None or batches < max_batches:
        # Pull a batch of un-embedded rows. RLS is bypassed by the platform DB
        # role this runs under; scoping isn't needed — we embed every tenant's
        # docs, and each row keeps its own tenant_id.
        async with async_session() as s:
            rows = (await s.execute(text("""
                SELECT id, content
                FROM documents
                WHERE embedding IS NULL AND content <> ''
                ORDER BY id
                LIMIT :lim
            """), {"lim": batch_size})).fetchall()

        if not rows:
            return {"status": "done", "embedded": total, "batches": batches, "model": last_model}

        ids = [r.id for r in rows]
        contents = [r.content for r in rows]

        result = await embed_texts(contents)
        last_model = result.model

        # Write each vector back with its model tag. One transaction per batch.
        async with async_session() as s:
            for doc_id, vec in zip(ids, result.vectors):
                await s.execute(text("""
                    UPDATE documents
                    SET embedding = CAST(:v AS vector),
                        embedding_model = :model,
                        embedded_at = now()
                    WHERE id = :id
                """), {"v": to_pgvector_literal(vec), "model": result.model, "id": doc_id})
            await s.commit()

        total += len(ids)
        batches += 1
        logger.info("embedding backfill: batch %d embedded %d rows (model=%s)",
                    batches, len(ids), result.model)

    return {"status": "partial", "embedded": total, "batches": batches, "model": last_model}


async def reembed_all(model_hint: Optional[str] = None, batch_size: int = 64) -> Dict:
    """Force a full re-embed (e.g. after switching embedders): null out existing
    vectors, then run the pending backfill. `model_hint` is advisory logging
    only — the actual model is whatever embed_texts resolves to.
    """
    if not await _embedding_column_exists():
        return {"status": "skipped", "embedded": 0, "batches": 0, "model": None}
    async with async_session() as s:
        await s.execute(text("UPDATE documents SET embedding = NULL, embedding_model = NULL"))
        await s.commit()
    logger.info("embedding backfill: cleared all vectors for re-embed (hint=%s)", model_hint)
    return await embed_pending(batch_size=batch_size)
