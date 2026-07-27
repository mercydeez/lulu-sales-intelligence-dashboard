-- =============================================================================
-- 042_tenant_lifecycle.sql  (UAE SaaS Phase 2 — control plane)
-- Tenant lifecycle state machine + platform-operator audit trail.
--
-- Extends tenants.status from a free string into a defined set of lifecycle states,
-- records who/why/when on each transition, and adds operator support notes. These
-- two new tables are OPERATOR metadata (super-admin, cross-tenant) and — like the
-- `tenants` table itself — are intentionally NOT under tenant RLS; access is gated
-- in the app layer (super_admin only). Purely additive; existing rows are 'active'.
-- =============================================================================

-- 1. Lifecycle columns on tenants (status already exists; default stays 'active').
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status_reason     TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status_changed_by INTEGER REFERENCES users(id);

-- Constrain status to the known lifecycle states. Existing data is all 'active',
-- so the CHECK validates cleanly. Drop-and-recreate so re-runs are idempotent.
ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_status_check;
ALTER TABLE tenants ADD CONSTRAINT tenants_status_check CHECK (status IN (
    'trial', 'onboarding', 'active', 'payment_pending', 'past_due',
    'suspended', 'cancelled', 'deletion_requested', 'deleted'
));

-- 2. Status transition audit (append-only). Cross-tenant operator view.
CREATE TABLE IF NOT EXISTS tenant_status_events (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    reason      TEXT,
    changed_by  INTEGER REFERENCES users(id),
    changed_email TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_tenant_status_events_tenant
    ON tenant_status_events (tenant_id, created_at DESC);

-- 3. Operator support notes per tenant (cross-tenant operator view).
CREATE TABLE IF NOT EXISTS tenant_admin_notes (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    note        TEXT NOT NULL,
    author_id   INTEGER REFERENCES users(id),
    author_email TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_tenant_admin_notes_tenant
    ON tenant_admin_notes (tenant_id, created_at DESC);

DO $$ BEGIN RAISE NOTICE 'tenant lifecycle: status states + transition audit + admin notes ready'; END $$;
