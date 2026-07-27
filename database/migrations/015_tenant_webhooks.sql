-- 015_tenant_webhooks.sql
-- Outbound webhooks (B4 PaaS layer). A tenant registers HTTPS endpoints and the
-- events they care about; the platform POSTs signed JSON when those events fire.
-- Each endpoint has its own signing secret so receivers can verify authenticity
-- via an HMAC-SHA256 signature header.

CREATE TABLE IF NOT EXISTS tenant_webhooks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret VARCHAR(80) NOT NULL,                 -- per-endpoint HMAC signing secret
    events TEXT[] NOT NULL DEFAULT ARRAY['*'],   -- subscribed event types ('*' = all)
    description VARCHAR(200),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_delivery_at TIMESTAMP WITH TIME ZONE,
    last_status INTEGER,                         -- HTTP status of the last delivery
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenant_webhooks_tenant ON tenant_webhooks(tenant_id);

DO $$ BEGIN RAISE NOTICE 'tenant_webhooks table ready (outbound signed webhooks)'; END $$;
