-- =============================================================================
-- 055_rag_chunk_acl.sql  (RAG-1 — chunk metadata + the RBAC security boundary)
-- See docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md §1.5, §3.
--
-- Adds the metadata that makes retrieval BOTH accurate (rerank/routing signal)
-- and SAFE (per-chunk access control). Purely ADDITIVE to the existing
-- `documents` chunk store — nothing dropped; existing FTS + vector retrieval
-- keep working. Idempotent.
--
-- THE ACL MODEL (how RAG-5's pre-retrieval filter reads these):
--   tenant_id    — hard tenant scope (also enforced by RLS, already on).
--   visibility_roles TEXT[] — if non-empty, ONLY these roles may retrieve the
--                  chunk. If NULL/empty, visibility falls back to `sensitivity`.
--   store_scope  INTEGER[] — if non-empty, only callers whose accessible_stores
--                  OVERLAP may retrieve it. If NULL, tenant-wide.
--   sensitivity  — 'public' (any authed user) | 'internal' (default) |
--                  'restricted' (admins/managers). A default ladder used when
--                  visibility_roles is not set.
-- The canonical filter (applied in SQL BEFORE ANN scoring — never post-filter):
--   WHERE d.tenant_id = :tid
--     AND ( d.sensitivity = 'public'
--        OR (:role = ANY(d.visibility_roles))
--        OR (COALESCE(cardinality(d.visibility_roles),0) = 0
--            AND d.sensitivity = ANY(:allowed_sensitivities_for_role)) )
--     AND ( d.store_scope IS NULL
--        OR cardinality(d.store_scope) = 0
--        OR d.store_scope && :accessible_stores )
-- =============================================================================

-- Metadata + ACL columns (additive, idempotent).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS visibility_roles TEXT[];
ALTER TABLE documents ADD COLUMN IF NOT EXISTS store_scope      INTEGER[];
ALTER TABLE documents ADD COLUMN IF NOT EXISTS sensitivity      TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parent_ref       TEXT;        -- parent-doc retrieval
ALTER TABLE documents ADD COLUMN IF NOT EXISTS corpus           TEXT NOT NULL DEFAULT 'docs';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS lang             TEXT NOT NULL DEFAULT 'en';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash     TEXT;        -- idempotent upsert + embed cache
ALTER TABLE documents ADD COLUMN IF NOT EXISTS acl_updated_at   TIMESTAMPTZ; -- re-tag trigger for stale-ACL guard

-- Integrity: constrain sensitivity to the known ladder (guarded — ADD
-- CONSTRAINT isn't IF-NOT-EXISTS-able, so check the catalog first).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_sensitivity_chk'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_sensitivity_chk
            CHECK (sensitivity IN ('public', 'internal', 'restricted'));
    END IF;
END $$;

-- Access-path indexes for the RBAC filter's hot paths:
--   GIN array-containment on the two ACL arrays, btree on corpus + content_hash.
CREATE INDEX IF NOT EXISTS idx_documents_visibility_roles
    ON documents USING gin (visibility_roles);
CREATE INDEX IF NOT EXISTS idx_documents_store_scope
    ON documents USING gin (store_scope);
CREATE INDEX IF NOT EXISTS idx_documents_corpus
    ON documents (tenant_id, corpus);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash
    ON documents (content_hash);

DO $$ BEGIN
    RAISE NOTICE 'RAG chunk ACL ready (documents: visibility_roles/store_scope/sensitivity/corpus/lang/parent_ref/content_hash; RLS inherited)';
END $$;
