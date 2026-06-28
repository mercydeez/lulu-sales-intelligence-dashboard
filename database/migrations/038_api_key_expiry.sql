-- =============================================================================
-- 038_api_key_expiry.sql  (Phase 8* carve-out)
-- Long-lived public API credentials are a standing risk: a leaked `lsk_` key is
-- valid forever unless someone notices and revokes it. Add an optional expiry so
-- a key can be minted with a finite lifetime; existing keys (NULL) never expire,
-- preserving today's behaviour. Authentication treats an expired key exactly like
-- a revoked one. Additive + idempotent.
-- =============================================================================

ALTER TABLE tenant_api_keys
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;

-- Fast filtering of live keys by expiry on the public auth path.
CREATE INDEX IF NOT EXISTS ix_tenant_api_keys_expires_at
    ON tenant_api_keys (expires_at) WHERE expires_at IS NOT NULL;

DO $$ BEGIN RAISE NOTICE 'tenant_api_keys: optional expires_at added (NULL = never expires)'; END $$;
