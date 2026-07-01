-- =============================================================================
-- 043_usage_events.sql  (UAE SaaS Phase 3 — billing-period metering)
-- Append-only usage events so metering can be windowed to the CURRENT BILLING
-- PERIOD (the calendar month in Asia/Dubai) instead of the lifetime totals the
-- Track-5 scaffolding used. One row per metered action (Sage message, forecast
-- job, export, API request, …). Tenant-scoped + RLS like the rest of the schema.
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_events (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,          -- sage_message | forecast_job | export | import | api_request
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 0),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Access path: count a tenant's events of a type within a time window.
CREATE INDEX IF NOT EXISTS ix_usage_events_tenant_type_time
    ON usage_events (tenant_id, event_type, created_at DESC);

-- RLS: a tenant only ever sees its own usage (uses current_tenant_id() from 012).
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON usage_events;
CREATE POLICY tenant_isolation ON usage_events
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'usage_events: append-only billing-period metering ready (RLS on)'; END $$;
