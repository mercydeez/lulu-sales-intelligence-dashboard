-- =============================================================================
-- 039_data_requests.sql  (Phase 12 — trust & legal)
-- Audit trail for tenant data-subject requests: export (portability) and
-- delete-on-request (erasure). Deletion is NOT executed by the API: a request is
-- recorded here and must be approved + carried out by an operator (human-approved,
-- reversible review window), then marked completed. Tenant-scoped + idempotent.
-- =============================================================================

CREATE TABLE IF NOT EXISTS data_requests (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    kind            TEXT NOT NULL CHECK (kind IN ('export', 'delete')),
    status          TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'approved', 'completed', 'rejected', 'cancelled')),
    scope           TEXT,                       -- free-text scope/subject note
    requested_by    INTEGER REFERENCES users(id),
    requested_email TEXT,
    reviewed_by     INTEGER REFERENCES users(id),
    reason          TEXT,                       -- approval/rejection rationale
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_data_requests_tenant ON data_requests (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_data_requests_status ON data_requests (status) WHERE status = 'pending';

-- RLS: a tenant only ever sees its own requests (mirrors the rest of the schema;
-- uses the current_tenant_id() helper from migration 012 — GUC with demo fallback).
ALTER TABLE data_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON data_requests;
CREATE POLICY tenant_isolation ON data_requests
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'data_requests: export/delete request audit trail ready'; END $$;
