# Tenant Isolation — How It Holds

Retail IQ isolates tenants in **two independent layers**. A bug in one is caught by
the other.

## Layer 1 — application scoping
Every data reader filters by `tenant_id`, sourced from the authenticated user's JWT
claim and bound to a request-scoped `tenant_context`:
- Data routers (`kpis`, `sales`, `analytics`, `history`, `inventory`, `promotions`,
  `reports`, `procurement`, `data_sources`, …) scope queries to the caller's tenant.
- `sales_fact_view` carries `tenant_id` (migration 011) so unified reads are scoped.
- Caches are keyed by tenant (`tests/test_tenant_isolation.py::*cache_key*`).
- A token whose `tenant_id` claim differs from the user's real tenant is rejected
  (`token_tenant_mismatch`).

## Layer 2 — Postgres RLS (FORCE)
When `USE_RLS_ROLE=true`, the request path connects as the non-owner `app_rw` role
and Postgres FORCE-RLS enforces `tenant_id = current_tenant_id()` policies
(migrations 010–012, 020–021, 026, 031). Even a missing app-layer filter cannot
leak rows, because the database itself refuses them. Production **requires** this
(see [`../production/ENVIRONMENT.md`](../production/ENVIRONMENT.md)); the only escape
is the explicit `ALLOW_INSECURE_NO_RLS` override (demo only).

## What Phase 6 closed
The data-source registry was the one place doing **global** queries. It is now
tenant-scoped at the SQL layer, and the "one active source" uniqueness is per-tenant
(migration 037). See [`DATA_SOURCE_SECURITY.md`](DATA_SOURCE_SECURITY.md).

## Evidence
- App-layer + cache isolation: `tests/test_tenant_isolation.py` (passing).
- Data-source isolation: `tests/test_data_source_isolation.py` (passing).
- Federation/source adapters scoped by request tenant: `tests/test_federation.py`.
- AI/Sage tenant scoping: `tests/test_ai_rbac.py`, `tests/test_nl2sql_guard.py`
  (Phase 11).

## Limits (honest)
- RLS only protects tables/views with policies and only when `USE_RLS_ROLE` is on.
  Owner-path code (startup, migrations, generator) bypasses RLS by design — it must
  never serve request traffic.
- App-layer scoping depends on each new reader filtering by tenant; the RLS layer is
  the backstop, and new tenant-scoped tables must add a policy (see
  [`../production/MIGRATIONS.md`](../production/MIGRATIONS.md)).
- A formal cross-tenant penetration test on a live multi-tenant dataset is a
  recommended pre-GA step (`MANUAL_CHECKS_REQUIRED.md`).
