-- =============================================================================
-- 045_notifications.sql  (UAE SaaS Phase 7 — in-app notifications + preferences)
-- A per-user/in-app notification center. Notifications are tenant-scoped; a NULL
-- user_id means "everyone in the tenant" (e.g. a critical finding or a billing
-- event for all admins). Per-user preferences allow opting types out of in-app /
-- email. Email itself is a logged stub (no paid service) — wired later.
--
-- The Node worker (worker_rw, BYPASSRLS) inserts finding notifications, so it needs
-- an explicit grant on the new table + sequence.
-- =============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- NULL = tenant-wide
    type        TEXT NOT NULL,        -- finding | billing | lifecycle | export | quota | system
    title       TEXT NOT NULL,
    body        TEXT,
    severity    TEXT NOT NULL DEFAULT 'info'
                  CHECK (severity IN ('critical','high','medium','low','info')),
    link        TEXT,                 -- in-app route to open, e.g. /insights
    metadata    JSONB NOT NULL DEFAULT '{}',
    read_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_notifications_tenant_user_time
    ON notifications (tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notifications_unread
    ON notifications (tenant_id, created_at DESC) WHERE read_at IS NULL;

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON notifications;
CREATE POLICY tenant_isolation ON notifications
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    muted_types   JSONB NOT NULL DEFAULT '[]',   -- list of types opted out of in-app
    email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON notification_preferences;
CREATE POLICY tenant_isolation ON notification_preferences
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

-- The worker (BYPASSRLS) writes finding notifications.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worker_rw') THEN
        GRANT SELECT, INSERT ON notifications TO worker_rw;
        GRANT USAGE, SELECT ON SEQUENCE notifications_id_seq TO worker_rw;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'notifications + preferences ready (RLS on; worker grant set)'; END $$;
