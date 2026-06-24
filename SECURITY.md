# Security Overview

A one-page summary of how Retail IQ protects customer data — the kind a buyer's IT
team asks for. This reflects what is **implemented today**; items still in progress
are marked.

## Authentication & sessions
- **JWT** access + refresh tokens (python-jose), bcrypt password hashing (passlib).
- Access tokens are type-pinned (a refresh token cannot be replayed as an access token).
- Refresh-token rotation; logout **blacklists token hashes in Redis**, enforced by
  `SessionInvalidationMiddleware` (fails open if Redis is down, so availability is preserved).
- **Two-step verification (TOTP / RFC 6238)** — opt-in per user; when enabled, password
  alone returns a short-lived challenge and a 6-digit authenticator code is required to mint
  tokens. Works with Google Authenticator / Authy / 1Password. (`services/totp.py`, `/api/auth/2fa/*`.)
- Per-tenant **public API keys** (`lsk_`) for programmatic access, separate from user JWTs.

## Real-time security monitoring & alerting
- A `security_events` table (tenant-scoped + RLS) records failed logins, lockouts, role/
  permission denials, rate-limit breaches, CSRF failures, token replay/tampering, API-key abuse,
  and sensitive actions. Written on the owner session so RLS can never suppress a log.
- **Security Operations dashboard** (`/security`, admin) with live SSE feed, posture score, and
  high/critical flash alerts; a posture tile + threat badge surface it on the main dashboard.
- **Alerting**: high/critical events dispatch an email (SMTP, e.g. a Gmail app password) and/or an
  incoming webhook — the "we noticed a new sign-in" pattern. Env-gated; no-op until configured.

## Authorization (RBAC)
- Roles: super_admin · regional_manager · store_manager, with region→store scope expansion.
- Data routers enforce auth + tenant + accessible-store scoping server-side
  (`routes/auth.py`: `get_current_user` / `require_role` / `require_permission`).

## Tenant isolation (multi-tenancy)
- **App-layer scoping** (primary): every query filters `tenant_id`.
- **Postgres Row-Level Security — ENFORCED** (defense in depth): the authenticated request
  path connects as the non-owner `app_rw` role under FORCE RLS (`USE_RLS_ROLE=true`), so
  Postgres itself blocks cross-tenant reads — verified: as `app_rw` scoped to tenant B, an
  explicit `WHERE tenant_id = A` returns zero rows. Policies are keyed off the per-connection
  `app.tenant_id` GUC (migrations 010–012, 020), which is bound BEFORE any query runs by
  `resolve_request_tenant` (from the JWT `tenant_id` claim, or an owner-session API-key lookup),
  independent of FastAPI dependency order.
- **Least-privilege background worker**: the diagnostics worker connects as `worker_rw`
  (migration 029) — SELECT on sales/items/stores + R/W on `findings` only; it cannot read
  `users`, credentials, or any other table.
- **Tenant-scoped caching**: every cache key folds in the active tenant, so a cached response
  can never be served across tenants (super_admins of different tenants share the same scope
  params and previously collided on one key).
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
- ~~Flip `USE_RLS_ROLE`~~ — DONE: RLS is enforced on the request path (see Tenant isolation).
- Extend explicit app-layer `tenant_id` filters to the remaining analytics/reports/alerts/
  promotions queries (they are correct under RLS today; this is defense-in-depth).
- Enforce 2FA (schema columns exist but login does not yet check them).
- Backups + restore drill; data residency (UAE PDPL); ToS / Privacy / DPA; tenant
  export & delete-on-request; billing/metering.
