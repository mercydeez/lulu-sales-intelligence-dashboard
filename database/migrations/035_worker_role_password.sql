-- 035_worker_role_password.sql
-- Repair the worker_rw stale-volume auth bug (Track 2 hardening).
--
-- Bug: 029 set the login password only in its CREATE branch. On a volume where the
-- worker_rw role already existed, 029 took the ELSE (attributes-only) path and left
-- the role WITHOUT a password, so the diagnostics worker failed with
-- "password authentication failed for user worker_rw". 029 is recorded as applied on
-- such volumes, so patching it can't re-run — this forward migration unconditionally
-- (re)asserts the dev password so already-migrated volumes match the password the
-- compose file hands the worker via WORKER_DATABASE_URL.
--
-- Production: this dev default is overwritten automatically after every migration
-- pass — backend/app/services/role_password_sync.py re-asserts the password from
-- WORKER_DB_PASSWORD (and app_rw's from RLS_DATABASE_URL). No manual ALTER ROLE.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worker_rw') THEN
        ALTER ROLE worker_rw LOGIN PASSWORD 'worker_rw_dev_pass';
        RAISE NOTICE 'worker_rw login password (re)asserted';
    ELSE
        RAISE NOTICE 'worker_rw role absent; 029 will create it with a password';
    END IF;
END $$;
