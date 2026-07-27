-- =============================================================================
-- 054_pgvector_semantic.sql  (Sage grounded-intelligence — Stage 1, pgvector)
-- See docs/product/specs/SAGE_GROUNDED_INTELLIGENCE.md and STAGE1_SEMANTIC_LAYER.md.
--
-- Adds vector search to the EXISTING tenant-scoped `documents` table — the
-- upgrade path rag/retriever.py already documents. Purely ADDITIVE: new
-- columns + an ANN index, nothing dropped or renamed, so the existing
-- full-text retrieval keeps working untouched.
--
-- Every risky step is wrapped so the migration SUCCEEDS on a plain Postgres
-- image with no pgvector — the app then detects the missing extension and
-- keeps serving FTS. No hard dependency, no boot failure. Idempotent.
--
-- (Adapted from the parked Track-10 migration on `main`; renumbered to the
--  next free slot on this branch and kept dimension-compatible so vectors
--  produced there could be reused.)
-- =============================================================================

DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pgvector unavailable — semantic search disabled, FTS remains';
        RETURN;
    END;

    -- 384 dims = all-minilm (Ollama) and the built-in hashed fallback embedder.
    -- embedding_model records WHICH embedder produced the vector: vectors from
    -- different embedders live in DIFFERENT spaces and must never be compared,
    -- so retrieval filters on the active model tag. This is what lets us
    -- re-embed (swap models) without a downtime cutover.
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(384);
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_model TEXT;
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

    -- Cosine HNSW (best recall/latency); fall back gracefully on older pgvector.
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_documents_embedding
            ON documents USING hnsw (embedding vector_cosine_ops);
    EXCEPTION WHEN OTHERS THEN
        BEGIN
            CREATE INDEX IF NOT EXISTS idx_documents_embedding
                ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'no ANN index available — sequential vector scan (fine at this scale)';
        END;
    END;

    -- Partial index over the model tag speeds the "rows needing (re)embedding"
    -- scan the backfill worker runs.
    CREATE INDEX IF NOT EXISTS idx_documents_needs_embedding
        ON documents (tenant_id) WHERE embedding IS NULL;

    RAISE NOTICE 'pgvector semantic layer ready (documents.embedding 384d cosine, RLS inherited)';
END $$;
