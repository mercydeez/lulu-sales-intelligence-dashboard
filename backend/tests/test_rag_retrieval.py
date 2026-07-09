"""
Integration test: RBAC-aware hybrid retrieval (RAG-4 + RAG-5).
Requires a live pgvector DB — gated on RUN_DB_TESTS=1 (same convention as
test_metric_views_parity). This is also the RBAC-leak invariant (EVAL-2 core):
a query must return ZERO chunks the caller isn't authorized to see.

Run: docker compose exec -T -e RUN_DB_TESTS=1 backend \
       python -m pytest tests/test_rag_retrieval.py -v
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="needs live pgvector DB (set RUN_DB_TESTS=1)"
)

TITLES = ("RAG4TEST public", "RAG4TEST restricted", "RAG4TEST store3")


async def _seed():
    from sqlalchemy import text
    from app.services.database import async_session
    from app.services.embeddings import embed_texts, to_pgvector_literal

    docs = [
        ("RAG4TEST public",     "ramadan restock dairy policy all stores",  "public",     None),
        ("RAG4TEST restricted", "ramadan restock exec margin confidential", "restricted", None),
        ("RAG4TEST store3",     "ramadan restock al barsha runbook",        "internal",   [3]),
    ]
    emb = await embed_texts([d[1] for d in docs])
    async with async_session() as s:
        await s.execute(text("DELETE FROM documents WHERE title LIKE 'RAG4TEST%'"))
        for (title, content, sens, scope), vec in zip(docs, emb.vectors):
            await s.execute(text(
                "INSERT INTO documents (tenant_id,title,chunk_no,content,sensitivity,store_scope,embedding,embedding_model)"
                " VALUES (1,:t,0,:c,:s,:sc, CAST(:v AS vector), :m)"
            ), {"t": title, "c": content, "s": sens, "sc": scope,
                "v": to_pgvector_literal(vec), "m": emb.model})
        await s.commit()


async def _cleanup():
    from sqlalchemy import text
    from app.services.database import async_session
    async with async_session() as s:
        await s.execute(text("DELETE FROM documents WHERE title LIKE 'RAG4TEST%'"))
        await s.commit()


async def test_rbac_aware_hybrid_retrieval_isolates():
    from app.services.rag.retriever import search_documents
    await _seed()
    try:
        sm5 = await search_documents("ramadan restock", 1, role="store_manager", allowed_stores=[5])
        rm = await search_documents("ramadan restock", 1, role="regional_manager", allowed_stores=[])
        sm3 = await search_documents("ramadan restock", 1, role="store_manager", allowed_stores=[3])

        got5 = sorted(c["title"] for c in sm5)
        gotr = sorted(c["title"] for c in rm)
        got3 = sorted(c["title"] for c in sm3)
    finally:
        await _cleanup()

    # THE RBAC-leak invariant: store-5 manager sees ONLY public.
    assert got5 == ["RAG4TEST public"], f"ACL LEAK in retrieval: {got5}"
    # regional (restricted ladder + no store restriction) sees all three.
    assert gotr == sorted(TITLES), f"regional under-retrieved: {gotr}"
    # store-scoped access: store-3 manager also sees the store-3 runbook.
    assert got3 == ["RAG4TEST public", "RAG4TEST store3"], f"store-scope wrong: {got3}"
