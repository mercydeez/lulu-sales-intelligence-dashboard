"""
Tenant-scoped, RBAC-aware, hybrid document retrieval + grounded answering.

Retrieval (RAG-4): full-text (BM25/ts_rank) UNION vector (pgvector cosine),
fused by Reciprocal Rank Fusion (rag/fusion.py). Both arms are filtered by the
caller's RBAC grants BEFORE scoring (rag/acl.py — RAG-5); nothing the caller
can't see is ever scored, reranked, or narrated. Degrades gracefully: without
pgvector or embeddings the vector arm is empty and FTS carries the answer; with
the hashed fallback embedder the vector arm is down-weighted.

The public interface (`search_documents`, `answer_from_docs`) is unchanged;
RBAC context (role, allowed_stores) is optional-kwarg additive — callers that
pass only tenant_id keep working (tenant-scoped, public+internal visibility).

Answering is grounded: with an LLM it narrates ONLY from retrieved chunks (with
a citation); without one it returns the top chunk verbatim + citation. It never
fabricates — if nothing is retrieved, it says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from sqlalchemy import text

from app.services.database import async_session
from app.services.rag.acl import build_acl_filter
from app.services.rag.fusion import fuse_keys

_FTS_CANDIDATES = 20
_VEC_CANDIDATES = 20


@dataclass
class RagAnswer:
    ok: bool
    answer: str = ""
    citations: List[str] = field(default_factory=list)
    chunks: List[dict] = field(default_factory=list)


async def search_documents(
    query: str,
    tenant_id: int,
    top_k: int = 5,
    *,
    role: Optional[str] = None,
    allowed_stores: Optional[Sequence[int]] = None,
    use_vector: bool = True,
) -> List[dict]:
    """Top-k RBAC-scoped chunks for `query` via hybrid (FTS ∪ vector) + RRF.

    role/allowed_stores default to the tenant-wide public+internal view when
    omitted (backward compatible). Returns full chunk dicts in fused order.
    """
    acl = build_acl_filter(tenant_id, role, allowed_stores)
    k = max(1, min(top_k, 10))

    async with async_session() as s:
        # ── FTS arm (ACL-filtered) ──────────────────────────────────────────
        fts_ids: List[int] = []
        if query and query.strip():
            fts_ids = [r.id for r in (await s.execute(text(f"""
                SELECT d.id
                FROM documents d
                WHERE {acl.where_sql}
                  AND d.tsv @@ plainto_tsquery('english', :q)
                ORDER BY ts_rank(d.tsv, plainto_tsquery('english', :q)) DESC
                LIMIT {_FTS_CANDIDATES}
            """), {**acl.params, "q": query})).all()]

        # ── Vector arm (ACL-filtered, same-model-tag only) ──────────────────
        vec_ids: List[int] = []
        semantic = False
        if use_vector and query and query.strip():
            try:
                from app.services.embeddings import embed_one, to_pgvector_literal
                emb = await embed_one(query)
                semantic = emb.semantic
                if emb.vectors:
                    qlit = to_pgvector_literal(emb.vectors[0])
                    vec_ids = [r.id for r in (await s.execute(text(f"""
                        SELECT d.id
                        FROM documents d
                        WHERE {acl.where_sql}
                          AND d.embedding IS NOT NULL
                          AND d.embedding_model = :emb_model
                        ORDER BY d.embedding <=> CAST(:qvec AS vector)
                        LIMIT {_VEC_CANDIDATES}
                    """), {**acl.params, "emb_model": emb.model, "qvec": qlit})).all()]
            except Exception:
                # pgvector/embedder unavailable → FTS-only, no crash.
                vec_ids = []

        # ── Fuse (down-weight the vector arm when it's the hashed fallback) ──
        weights = [1.0, 1.0 if semantic else 0.3]
        fused_ids = fuse_keys([fts_ids, vec_ids], weights=weights, top_k=k)
        if not fused_ids:
            return []

        rows = (await s.execute(text("""
            SELECT id, title, chunk_no, content, corpus, created_at
            FROM documents WHERE id = ANY(:ids)
        """), {"ids": fused_ids})).mappings().all()
    by_id = {r["id"]: dict(r) for r in rows}
    # Arm membership feeds source-confidence scoring (rag/confidence.py):
    # a chunk found by BOTH keyword and semantic arms is corroborated evidence.
    fts_set, vec_set = set(fts_ids), set(vec_ids)
    out = []
    for i in fused_ids:
        if i not in by_id:
            continue
        c = by_id[i]
        c["in_fts"] = i in fts_set
        c["in_vec"] = i in vec_set
        out.append(c)
    return out


def _cite(c: dict) -> str:
    return f"{c['title']} (chunk {c['chunk_no']})"


async def answer_from_docs(question: str, tenant_id: int, providers=None,
                           query: Optional[str] = None, *,
                           role: Optional[str] = None,
                           allowed_stores: Optional[Sequence[int]] = None) -> RagAnswer:
    """Retrieve (RBAC-scoped, hybrid) + answer grounded. `query` overrides the
    search string. role/allowed_stores scope retrieval to the caller's grants."""
    chunks = await search_documents(query or question, tenant_id,
                                    role=role, allowed_stores=allowed_stores)
    if not chunks:
        return RagAnswer(ok=False, answer="No matching passage found in the documents.")

    # RAG-6: rerank + dedup + budget + lost-in-the-middle ordering + citations.
    from app.services.rag.rerank import assemble_context
    ctx, chunks, citations = assemble_context(query or question, chunks)
    providers = providers or []
    # With an LLM: narrate strictly from the assembled context.
    for provider in providers:
        try:
            from app.services.llm import LLMError
            try:
                ans = await provider.complete([
                    {"role": "system", "content": "Answer ONLY from the provided document excerpts. "
                     "Cite the source in parentheses. If they don't contain the answer, say so."},
                    {"role": "user", "content": f"Excerpts:\n{ctx}\n\nQuestion: {question}"},
                ])
                if ans and ans.strip():
                    return RagAnswer(ok=True, answer=ans.strip(), citations=citations, chunks=chunks)
            except LLMError:
                continue
        except Exception:
            continue

    # No LLM: return the top chunk verbatim with its citation (still grounded).
    top = chunks[0]
    return RagAnswer(ok=True, answer=f"{top['content']}  ({_cite(top)})",
                     citations=citations, chunks=chunks)
