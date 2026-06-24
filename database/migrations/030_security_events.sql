-- 030_security_events.sql
-- Real-time security telemetry (Security Operations panel). Every security-relevant
-- event the app detects — failed logins, lockouts, permission/role denials,
-- rate-limit breaches, CSRF failures, token replay/tampering, API-key abuse, and
-- sensitive actions (key create/revoke, password change, signup) — is recorded here
-- and published to the Redis `security:stream` channel for live dashboards.
--
-- Tenant-scoped + RLS (defense in depth), mirroring `findings` (migration 024).
-- IMPORTANT: rows are WRITTEN by the app on the owner session so a security log can
-- never be suppressed by RLS; they are READ on the request path (app_rw) where RLS
-- guarantees one tenant can never see another tenant's security events.

CREATE TABLE IF NOT EXISTS security_events (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL DEFAULT 1,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- machine code, e.g. login_failed, account_locked, permission_denied,
    -- role_denied, rate_limited, csrf_failed, token_invalid, token_blacklisted,
    -- token_tenant_mismatch, api_key_invalid, api_key_created, api_key_revoked,
    -- password_changed, signup.
    event_type    TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'info'
                  CHECK (severity IN ('critical','high','medium','low','info')),
    -- "threat" (someone attacking) vs "audit" (a sensitive but legitimate action).
    category      TEXT NOT NULL DEFAULT 'threat',
    actor_user_id INTEGER,
    actor_email   TEXT,
    ip_address    TEXT,
    method        TEXT,
    path          TEXT,
    detail        TEXT,                       -- human-readable sentence
    evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_events_tenant_time
    ON security_events (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_tenant_sev
    ON security_events (tenant_id, severity, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_tenant_type
    ON security_events (tenant_id, event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_ip
    ON security_events (tenant_id, ip_address, occurred_at DESC);

-- RLS: same model as findings — policy keyed off the per-connection tenant GUC.
ALTER TABLE security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON security_events;
CREATE POLICY tenant_isolation ON security_events
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- The request-path role reads its own tenant's events; the owner (app) writes them.
GRANT SELECT, INSERT ON security_events TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE security_events_id_seq TO app_rw;

DO $$ BEGIN RAISE NOTICE 'security_events ready (tenant-scoped + RLS; Redis channel security:stream)'; END $$;
