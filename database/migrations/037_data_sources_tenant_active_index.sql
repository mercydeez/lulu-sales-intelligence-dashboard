-- =============================================================================
-- 037_data_sources_tenant_active_index.sql
-- Make "one active data source" per-TENANT instead of global.
--
-- Migration 009 created a GLOBAL partial-unique index:
--   uq_data_sources_one_active ON data_sources (is_active) WHERE is_active
-- which (a) lets only one tenant have an active source at all, and (b) combined
-- with the previously unscoped set_active(), allowed cross-tenant interference.
-- Replace it with a per-tenant partial-unique index so each tenant has exactly
-- one active source, independently. Additive + idempotent.
-- =============================================================================

DROP INDEX IF EXISTS uq_data_sources_one_active;

CREATE UNIQUE INDEX IF NOT EXISTS uq_data_sources_one_active_per_tenant
    ON data_sources (tenant_id) WHERE is_active;

DO $$ BEGIN RAISE NOTICE 'data_sources: one active source is now per-tenant'; END $$;
