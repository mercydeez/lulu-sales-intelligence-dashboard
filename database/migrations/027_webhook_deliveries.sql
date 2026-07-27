-- 027_webhook_deliveries.sql
-- Per-delivery log for the Developer Portal's webhook delivery history. The
-- existing tenant_webhooks row only keeps last_status/last_delivery_at; this gives
-- developers the recent delivery timeline they need to debug integrations.

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL,
    webhook_id   BIGINT NOT NULL,
    event        TEXT NOT NULL,
    status_code  INTEGER,
    ok           BOOLEAN NOT NULL DEFAULT FALSE,
    error        TEXT,
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_hook
    ON webhook_deliveries (webhook_id, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_tenant
    ON webhook_deliveries (tenant_id, delivered_at DESC);

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON webhook_deliveries;
CREATE POLICY tenant_isolation ON webhook_deliveries
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT ON webhook_deliveries TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE webhook_deliveries_id_seq TO app_rw;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'webhook_deliveries log table ready'; END $$;
