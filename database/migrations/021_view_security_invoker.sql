-- 021_view_security_invoker.sql
-- Make the unified sales view honour the CALLER's row-level security.
--
-- By default a Postgres view runs with the view OWNER's privileges/RLS context,
-- so the non-owner app_rw role querying sales_fact_view would see every tenant's
-- rows (the owner is a superuser that bypasses RLS). `security_invoker = true`
-- (Postgres 15+) makes the view evaluate underlying-table RLS as the INVOKER, so
-- app_rw is scoped to its tenant through the view too. The superuser app path is
-- unaffected (it still bypasses RLS and is scoped by the app-layer WHERE clause).

ALTER VIEW sales_fact_view SET (security_invoker = true);

DO $$ BEGIN RAISE NOTICE 'sales_fact_view now runs with security_invoker (RLS follows the caller)'; END $$;
