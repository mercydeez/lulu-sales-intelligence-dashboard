# Stage 1 — Semantic layer on pgvector (build spec + landed foundation)

> Parent: `SAGE_GROUNDED_INTELLIGENCE.md` (the four-tier architecture).
> This is the concrete Stage-1 slice: give T2 (hybrid RAG) real semantic recall.
> Owner of the retrieval wiring: **Atharva** (his AI vertical). Foundation
> (migration + embeddings service) is already landed on this branch — additive,
> touches nothing in `rag/`, so it can't collide with live Sage work.

## What is already landed (additive, verified)

1. **`database/migrations/054_pgvector_semantic.sql`** — adds `embedding vector(384)`,
   `embedding_model`, `embedded_at` to the existing tenant-scoped `documents`
   table + a cosine HNSW index (IVFFlat → seqscan fallbacks). Every risky step is
   exception-wrapped: on a Postgres without pgvector the migration *succeeds* and
   the app keeps serving FTS. Idempotent. Inherits `documents`' RLS.
2. **`backend/app/services/embeddings.py`** — `embed_texts()` / `embed_one()`.
   Real embeddings via Ollama (`all-minilm`, 384d) when `ENABLE_LOCAL_AI` +
   `OLLAMA_URL` are set; otherwise a **deterministic hashed fallback** (zero deps)
   so the whole loop runs in CI/demo. Every vector is L2-normalized (cosine-ready)
   and carries a **model tag** — vectors from different embedders are never
   compared. Pure/importable; the hashed path is unit-verified (normalized,
   deterministic, lexical-overlap > unrelated).

Nothing above changes existing behavior — FTS retrieval is byte-for-byte
unchanged until step 1 below is wired.

## What Atharva wires next (in his files)

### 1. Hybrid retrieval in `rag/retriever.py` (interface unchanged)
`search_documents()` keeps its signature; internally becomes FTS ∪ vector via
**Reciprocal Rank Fusion** (RRF, k=60):

```python
from app.services.embeddings import embed_one, to_pgvector_literal

async def search_documents(query, tenant_id, top_k=5):
    # 1. existing FTS candidates (ts_rank), top ~20
    # 2. vector candidates: embed the query with the SAME embedder, filter to
    #    the active model tag, ORDER BY embedding <=> :qvec  (cosine), top ~20
    #        WHERE tenant_id = :tid AND embedding IS NOT NULL
    #          AND embedding_model = :active_model
    #        ORDER BY embedding <=> CAST(:qvec AS vector) LIMIT 20
    # 3. RRF-fuse the two ranked lists by (title, chunk_no); return top_k
```
- Query embedding uses `embed_one(query)` — same model tag as stored rows, so
  spaces match. If `result.semantic is False` (hashed fallback), you may skip
  the vector arm or weight it low; FTS still carries the answer.
- Tenant scoping stays in the SQL `WHERE` (RLS is defense-in-depth, not the
  only guard).

### 2. Backfill + on-write embedding
- **On write:** when a document/chunk is inserted, embed and store
  `embedding`, `embedding_model`, `embedded_at` in the same transaction.
- **Backfill worker:** a lifespan task (or admin endpoint) embeds rows where
  `embedding IS NULL` (the migration's partial index targets exactly these) in
  batches, respecting the tenant loop. Re-embedding = update `embedding_model`
  to the new tag and null-and-refill; queries filtering on the active tag never
  see half-migrated state.

### 3. Corpora beyond docs (the accuracy payoff)
Embed and store (same table or sibling tables with the same shape): runbooks,
changelog entries, **findings narratives**, metric-registry descriptions,
NL2SQL exemplars, and `product_state` slices. This is what lets T2/T3 answer
"what's happening & why" with citations.

## Accuracy machinery for Stage 1 (the point of the exercise)

- **Same-embedder invariant** (enforced by the model tag) — the single most
  common RAG accuracy bug is comparing query and doc vectors from different
  models. The tag filter makes that impossible.
- **Grounded-or-refused** — retriever already returns citations and says so
  when nothing is retrieved; keep that. Low fused-score top hit → refuse.
- **Golden eval gate** — port `ai_evals.py` + `test_semantic_layer.py` from the
  parked Track-10 work; add retrieval-quality cases (question → expected doc/
  finding cited). Gate CI on recall@k and citation coverage. This is how "98%"
  stays a measured number, not a claim.
- **Feedback → evals** — the Y6 `user_feedback` table (👍/👎) auto-drafts eval
  cases from thumbs-down, so accuracy compounds.

## Scalability notes baked into the foundation

- **HNSW** cosine index (→ IVFFlat → seqscan) — sub-linear ANN at the tenant
  scale, graceful on older pgvector.
- **RLS-inherited** — no separate isolation path to secure.
- **384d** — small vectors, cheap storage/index, matches the local PDPL-clean
  embedder; big enough for retrieval quality at this corpus size.
- **Read-replica ready** — vector reads are pure SELECTs; route them to the
  E10-7 replica when it lands. Dedicated vector store (Qdrant) only past
  ~10M chunks — deliberately deferred (see parent §7).
- **Batch embedding** + on-write path keeps ingest amortized; the hashed
  fallback means CI/dev never needs a GPU/model server.

## Config (optional — the service works without any of it)

`embeddings.py` reads these via defensive `getattr`, so nothing breaks if
they're absent. Add to `config.py` (Krishna's steward, append in a bannered
block) when convenient:

| Setting | Default | Purpose |
|---|---|---|
| `enable_local_ai` | existing flag | gates the Ollama embedder |
| `ollama_url` | existing | Ollama endpoint |
| `ollama_embed_model` | falls back to `ollama_model`/`all-minilm` | dedicated embed model |

## Verification checklist (must run in-container — pgvector + app deps)

- [ ] `docker compose up -d`; migration 054 applies (NOTICE, no error) on the
      pgvector image; and applies harmlessly on a plain `postgres:15` image.
- [ ] Backfill embeds seed docs; `SELECT count(*) FROM documents WHERE embedding IS NOT NULL` > 0.
- [ ] Tenant-isolation test: tenant A's query returns 0 of tenant B's chunks
      (vector arm included) — mirror the existing RLS tests.
- [ ] Ported eval set green in CI at the target recall@k.
- [ ] With `ENABLE_LOCAL_AI=false`, hashed fallback path serves without error
      (semantic=False, FTS carries answers).

## Explicitly out of scope for Stage 1

Reranker (Stage 2), semantic cache (Stage 2), dedicated vector store (Stage 3),
letting the LLM see raw tables (never). See parent doc.
