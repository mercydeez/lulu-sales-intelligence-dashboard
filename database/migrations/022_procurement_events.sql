-- 022_procurement_events.sql
-- Procurement audit log (Part III-H "audit timeline"). An append-only,
-- tenant-scoped record of every meaningful procure-to-pay action — PO created /
-- approved / sent / received, goods receipts, invoices, 3-way-match results.
-- Written inside the same transaction as the action it records, so the audit
-- trail can't drift from reality. Backs the timeline UI and feeds the same
-- domain events that fire webhooks.

CREATE TABLE IF NOT EXISTS procurement_events (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,       -- e.g. po.created, goods.received
    entity_type VARCHAR(30) NOT NULL,      -- purchase_order | goods_receipt | supplier_invoice | supplier
    entity_id INTEGER,
    entity_ref VARCHAR(60),                -- display ref (e.g. PO number) — no join needed
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_proc_events_tenant_time ON procurement_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proc_events_entity ON procurement_events(entity_type, entity_id);

-- RLS + FORCE, consistent with migration 020.
ALTER TABLE procurement_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE procurement_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON procurement_events;
CREATE POLICY tenant_isolation ON procurement_events
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- app_rw (non-owner request role) needs DML on the new table; ALTER DEFAULT
-- PRIVILEGES from migration 020 covers future tables, but grant explicitly too
-- in case this runs against a DB where app_rw already exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON procurement_events TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE procurement_events_id_seq TO app_rw;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'procurement_events audit log ready'; END $$;
