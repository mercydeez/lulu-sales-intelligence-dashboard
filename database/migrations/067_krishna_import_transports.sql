-- 067 — E2-2 completion: SFTP + IMAP import transports.
--
-- Migration 064 shipped `https` only and refused `sftp`/`imap` at the CHECK. Both
-- are now implemented (services/import_scheduler.py fetch_sftp/fetch_imap), so the
-- domain widens to admit them.
--
-- CREDENTIALS ARE NEVER STORED HERE. A schedule references its secret by the NAME
-- of an environment variable (source_config.password_env / private_key_env),
-- resolved in the singletons/scheduler process — the same pattern the e-invoicing
-- providers use for their API keys. The DB holds host/port/user/path/mailbox in
-- `source_config`; the password lives in the process environment or a secret
-- manager, never in a column that ends up in a backup.

BEGIN;

-- Non-secret transport config: for sftp {host,port,username,password_env|private_key_env,path};
-- for imap {host,port,username,password_env,mailbox,subject_contains,attachment_ext,mark_seen}.
ALTER TABLE import_schedules
    ADD COLUMN IF NOT EXISTS source_config JSONB NOT NULL DEFAULT '{}';

-- Widen the transport domain. Migration 064 named the CHECK by column convention.
ALTER TABLE import_schedules DROP CONSTRAINT IF EXISTS import_schedules_source_kind_check;
ALTER TABLE import_schedules
    ADD CONSTRAINT import_schedules_source_kind_check
    CHECK (source_kind IN ('https', 'sftp', 'imap'));

-- A non-https transport is unrunnable without its config, so the DB refuses an
-- empty one — a schedule you can create but that always fails is worse than a 422.
ALTER TABLE import_schedules DROP CONSTRAINT IF EXISTS import_schedules_transport_has_config;
ALTER TABLE import_schedules
    ADD CONSTRAINT import_schedules_transport_has_config
    CHECK (
        source_kind = 'https'
        OR (source_config ? 'host' AND source_config ? 'username')
    );

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'imports: sftp + imap transports admitted; credentials referenced by env-var name, never stored';
END $$;
