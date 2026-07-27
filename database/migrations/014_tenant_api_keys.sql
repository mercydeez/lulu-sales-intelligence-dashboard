-- 014_tenant_api_keys.sql
-- Per-tenant API keys for the public REST API and the embeddable AI assistant
-- (B4 PaaS layer / B5 external AI). Each key belongs to exactly one tenant, so
-- a key both authenticates AND scopes every public call to that tenant's data.
--
-- Only a salted SHA-256 hash of the key is stored; the plaintext is shown once
-- at creation. A short, non-secret prefix (e.g. `lsk_ab12cd34`) is kept for
-- display/lookup so users can identify a key without exposing it.

CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    key_prefix VARCHAR(20) NOT NULL,            -- shown in UI, not a secret
    key_hash VARCHAR(64) NOT NULL UNIQUE,       -- sha256 hex of the full key
    scopes TEXT[] NOT NULL DEFAULT ARRAY['read'],
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    request_count BIGINT NOT NULL DEFAULT 0,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_tenant ON tenant_api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_api_keys_hash ON tenant_api_keys(key_hash);

DO $$ BEGIN RAISE NOTICE 'tenant_api_keys table ready (public API / embeddable AI)'; END $$;
