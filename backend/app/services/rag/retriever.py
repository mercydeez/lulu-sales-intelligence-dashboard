"""
Tenant-scoped document retrieval + grounded answering.

Retrieval: Postgres full-text (`tsv @@ plainto_tsquery`) ranked by ts_rank — no
external dependency, works today. SEMANTIC UPGRADE PATH: add a pgvector `embedding`
column to `documents` + an Ollama/OpenAI embedder and swap the ranking here; the
public interface (`search_documents`, `answer_from_docs`) stays the same.

Answering is grounded: with an LLM it narrates ONLY from retrieved chunks (with a
citation); without one it returns the top chunk verbatim + citation. It never
fabricates — if nothing is retrieved, it says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text

from app.services.database import async_session


@dataclass
class RagAnswer:
    ok: bool
    answer: str = ""
    citations: List[str] = field(default_factory=list)
    chunks: List[dict] = field(default_factory=list)


async def search_documents(query: str, tenant_id: int, top_k: int = 3) -> List[dict]:
    """Top-k tenant-scoped chunks for `query` by full-text rank."""
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT title, chunk_no, content,
                   ts_rank(tsv, plainto_tsquery('english', :q)) AS rank
            FROM documents
            WHERE tenant_id = :tid AND tsv @@ plainto_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :k
        """), {"q": query, "tid": tenant_id, "k": max(1, min(top_k, 10))})).mappings().all()
    return [dict(r) for r in rows]


def _cite(c: dict) -> str:
    return f"{c['title']} (chunk {c['chunk_no']})"


async def answer_from_docs(question: str, tenant_id: int, providers=None,
                           query: Optional[str] = None) -> RagAnswer:
    """Retrieve + answer grounded. `query` overrides the FTS search string."""
    chunks = await search_documents(query or question, tenant_id)
    if not chunks:
        return RagAnswer(ok=False, answer="No matching passage found in the documents.")

    citations = [_cite(c) for c in chunks]
    providers = providers or []
    # With an LLM: narrate strictly from the retrieved chunks.
    for provider in providers:
        try:
            ctx = "\n\n".join(f"[{_cite(c)}]\n{c['content']}" for c in chunks)
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
