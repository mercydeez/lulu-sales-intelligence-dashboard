# Security Overview

A one-page summary of how Retail IQ protects customer data — the kind a buyer's IT
team asks for. This reflects what is **implemented today**; items still in progress
are marked.

## Authentication & sessions
- **JWT** access + refresh tokens (python-jose), bcrypt password hashing (passlib).
- Refresh-token rotation; logout **blacklists token hashes in Redis**, enforced by
  `SessionInvalidationMiddleware` (fails open if Redis is down, so availability is preserved).
- Per-tenant **public API keys** (`lsk_`) for programmatic access, separate from user JWTs.

## Authorization (RBAC)
- Roles: super_admin · regional_manager · store_manager, with region→store scope expansion.
- Data routers enforce auth + tenant + accessible-store scoping server-side
  (`routes/auth.py`: `get_current_user` / `require_role` / `require_permission`).

## Tenant isolation (multi-tenancy)
- **App-layer scoping** (primary): every query filters `tenant_id`.
- **Postgres Row-Level Security** (defense in depth): policies keyed off the per-connection
  `app.tenant_id` GUC (migrations 010–012). A non-owner `app_rw` role exists for the
  FORCE-RLS request path (opt-in via `USE_RLS_ROLE`).
- **Sage (NL→SQL) isolation:** model-generated SQL runs as a dedicated least-privilege
  `sage_ro` role with SELECT on only seven tenant-filtered `sage_*` views (migration 023).
  Verified: `sage_ro` cannot read `users` or any base table, and the views filter to the
  caller's tenant via `current_tenant_id()`. An allow-list guard (single SELECT, no
  DDL/DML/comments/`;`, no catalog/GUC functions, hard row cap) sits in front.
- **Through-view RLS:** `sales_fact_view` runs with `security_invoker=true` (migration 026), so the
  base-table tenant policies apply to the querying role through the view. Verified: `app_rw` sees
  only its tenant's rows through the view. This unblocks the app-wide `USE_RLS_ROLE` flip (remaining
  follow-ups: GUC-after-auth ordering, cross-tenant public-API-key lookup).

## Application hardening
- **CSP** (env-driven `connect-src`, `object-src 'none'`, prod `upgrade-insecure-requests`),
  HSTS, `X-Frame-Options`, `X-Content-Type-Options`.
- **CORS** with enumerated methods/headers (required once credentials are allowed).
- **CSRF** double-submit for non-Bearer requests; **request body-size** limit.
- **Rate limiting**: Redis sliding-window per IP, in-memory fallback.
- **Fail-fast config**: startup raises in production/staging on default secrets, short JWT
  keys, or default DB credentials (`settings.validate_security()`).

## Auditability & observability
- Per-request `request_id` threaded through every log line (contextvar + filter); optional
  JSON logs. Diagnostics decisions (`findings.action_accepted_by/at`) are recorded.
- **Optional, env-gated**: Sentry (error tracking) and a notification webhook for
  high/critical findings — no-ops unless configured, so no data leaves the stack by default.

## Data handling
- Demo data is **synthetic** (Kaggle store-item demand dataset; revenue derived from a seeded
  per-item price). No real PII in the demo tenants.
- The diagnostics worker (Node/BullMQ) connects with app-layer tenant scoping and writes only
  the `findings` table.

## Reporting a vulnerability
This is a prototype. For a production deployment, route reports to a monitored security inbox
and acknowledge within a defined SLA. (Placeholder — set the contact before go-to-market.)

## Roadmap before handling real customer data (Track B)
- Flip `USE_RLS_ROLE` after the `security_invoker` fix + GUC-after-auth ordering.
- Backups + restore drill; data residency (UAE PDPL); ToS / Privacy / DPA; tenant
  export & delete-on-request; billing/metering.
