-- 070 — E2-1: POS connector framework — per-tenant connections + sync-run ledger.
--
-- WHAT THIS DOES. It records a tenant's connection to a POS vendor (Square, Foodics,
-- Omnivore, Lightspeed) and every nightly SYNC RUN against it. The connector's job is
-- to pull receipts from the POS and land them at the BASKET grain (transactions /
-- transaction_lines, migration 059) — the grain that is currently empty and that only
-- a real transaction source can fill (shrink, cannibalisation, basket analysis).
--
-- WHAT IT DOES NOT DO — and this is the honest posture, identical to e-invoicing (044)
-- and payments (069):
--   * A real vendor is REFUSED until it is added to services/pos_connectors
--     .IMPLEMENTED_VENDORS AND its OAuth credentials are configured. Recognising a
--     vendor is not the same as being able to pull from it — the outbound OAuth +
--     receipt-mapping integration per vendor is not built. Only `mock` runs the flow.
--   * OAuth CLIENT SECRETS are never stored here. A connection names the ENV VAR that
--     holds the vendor credential (credential_env); the secret is resolved in-process.
--   * The connector NEVER writes sales_fact_view. Per ADR-010 the daily grain stays the
--     source of truth for revenue; this basket grain is parallel, never UNIONed in, or a
--     connected POS would double-count. A REAL adapter additionally lands daily
--     aggregates in external_sales -> sales_rollup_daily (migration 056) for the revenue
--     path; the `mock` demonstrates the basket grain only, so demo revenue is unperturbed.
--   * The `mock` vendor writes rows tagged is_synthetic=true, confined to the demo tenant
--     (E0-8), with MOCK- txn refs — so a demo pull can never be mistaken for real sales.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / DROP POLICY IF EXISTS / guarded constraints.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. pos_connections — one row per (tenant, vendor).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_connections (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    vendor               TEXT NOT NULL,
    -- disconnected -> connecting (OAuth in flight) -> connected -> error.
    status               TEXT NOT NULL DEFAULT 'disconnected'
                           CHECK (status IN ('disconnected', 'connecting', 'connected', 'error')),
    -- The POS account/merchant/location id the connection points at.
    external_account_ref TEXT,
    -- ENV-VAR NAME holding the vendor OAuth token/secret — never the secret itself.
    credential_env       TEXT,
    scopes               TEXT,
    -- Incremental-sync watermark (e.g. the last store-local day already pulled).
    sync_cursor          TEXT,
    connected_at         TIMESTAMPTZ,
    last_sync_at         TIMESTAMPTZ,
    last_sync_status     TEXT,
    last_sync_error      TEXT,
    created_by           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, vendor)
);

-- A connected connection must name the POS account it is bound to — so 'connected'
-- can never be a bare status with nothing behind it.
ALTER TABLE pos_connections DROP CONSTRAINT IF EXISTS pos_connections_connected_has_account;
ALTER TABLE pos_connections
    ADD CONSTRAINT pos_connections_connected_has_account
    CHECK (status <> 'connected' OR external_account_ref IS NOT NULL);

CREATE INDEX IF NOT EXISTS ix_pos_connections_tenant ON pos_connections (tenant_id, status);

ALTER TABLE pos_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_connections FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pos_connections;
CREATE POLICY tenant_isolation ON pos_connections
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 2. pos_sync_runs — the audit ledger of every nightly (or on-demand) pull.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_sync_runs (
    id                  BIGSERIAL PRIMARY KEY,
    connection_id       INTEGER NOT NULL REFERENCES pos_connections(id) ON DELETE CASCADE,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'ok', 'error')),
    window_start        DATE,
    window_end          DATE,
    receipts_ingested   INTEGER NOT NULL DEFAULT 0,
    lines_ingested      INTEGER NOT NULL DEFAULT 0,
    aggregates_computed INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS ix_pos_sync_runs_conn ON pos_sync_runs (connection_id, started_at DESC);

ALTER TABLE pos_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_sync_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pos_sync_runs;
CREATE POLICY tenant_isolation ON pos_sync_runs
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'pos_connections + pos_sync_runs ready; real vendors refused until '
                 'implemented + credentialed, mock writes the demo-tenant basket grain';
END $$;
