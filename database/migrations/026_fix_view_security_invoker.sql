-- 026_fix_view_security_invoker.sql
-- Make sales_fact_view honour the CALLER's RLS (Track B; unblocks the app-wide
-- USE_RLS_ROLE flip). Migration 021 intended this but the option is not in effect
-- (an ALTER VIEW needs ACCESS EXCLUSIVE, which blocks behind the live generator's
-- reads on an already-running system; at fresh-boot migration time there is no such
-- contention, so this applies cleanly).
--
-- Safe for the current owner request path: the app connects as the superuser owner,
-- which bypasses RLS regardless, so data visibility is unchanged. It only MATTERS
-- once the request path runs as the non-owner app_rw role (USE_RLS_ROLE=true), where
-- it makes the base-table tenant_isolation policies apply through the view too.
--
-- lock_timeout keeps this from hanging forever if it ever runs under load; on a
-- fresh boot it grabs the lock instantly.
SET lock_timeout = '15s';

ALTER VIEW sales_fact_view SET (security_invoker = true);

DO $$ BEGIN RAISE NOTICE 'sales_fact_view security_invoker=true (RLS now follows the caller)'; END $$;
