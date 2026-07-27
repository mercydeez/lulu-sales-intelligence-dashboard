# Retail IQ — Production Baseline Audit

> **Status:** Current-state snapshot taken at the start of the production-hardening program (branch `prod-hardening`).
> **Method:** Repo inspection of `backend/app/{config,main}.py`, `services/{data_sources,auth_service}.py`, routes, `docker-compose*.yml`, `render.yaml`, `database/migrations/`, `frontend/`, `worker/`, and the existing docs.
> **Honesty rule:** This document separates **current facts** (what the code does *today*) from **recommendations** (deferred to the gap analysis / risk register). It changes no behavior.

This is a strong, security-conscious **MVP/demo**. It is **not yet a deployed production multi-tenant SaaS**. The gaps are operational and lifecycle hardening, not core capability.

---

## 1. What is already production-grade

These are real strengths and should not be weakened:

- **Secret validation fails fast.** `config.validate_security()` raises `RuntimeError` in production/staging on default `JWT_SECRET_KEY`/`SECRET_KEY`, secrets `<32` chars, and `salespass` in the DB URL.
- **Tenant isolation has two layers.** App-layer `tenant_id` scoping **plus** Postgres FORCE RLS via the non-owner `app_rw` role (migrations 010–012, 020–021, 026). Opt-in via `USE_RLS_ROLE`.
- **Least-privilege AI execution.** Sage runs generated SQL as `sage_ro` (migration 023) against curated `sage_*` views only, through a SELECT-only allow-list guard (`services/nl2sql/guard.py`): no DDL/DML, no dangerous functions, hard row cap, statement timeout.
- **Auth is feature-complete.** JWT access/refresh, Redis token blacklist (fail-**closed** when Redis is down by default), RBAC (`require_role`/`require_permission`), TOTP 2FA with hashed backup codes (migration 032), email-verified flag (migration 033).
- **Defense-in-depth middleware.** SecurityHeaders → CSRF (Bearer-exempt) → BodySizeLimit → SessionInvalidation → RateLimit (Redis sliding window) → RequestID → CORS (enumerated origins, never `*` in prod). `TRUST_PROXY_HEADERS` off by default (no IP spoofing).
- **Structured logging available.** `JsonLogFormatter` + `RequestIDLogFilter` emit one JSON line per record with a correlated `request_id`. Enabled via `LOG_JSON`.
- **API docs disabled in production.** `_docs_enabled` hides `/docs`, `/redoc`, `/openapi.json` outside development.
- **Data-source credentials are protected.** `data_sources._row_public()` strips `connection_enc`; connection strings are Fernet-encrypted at rest.
- **Migrations auto-apply** via `migration_runner.run_migrations` and are idempotent; 35 ordered SQL migrations (001–035).
- **Public API is read-only and guarded.** Per-tenant `lsk_` API keys with scopes, `last_used_at`, `request_count`, `revoked_at` (migration 014).
- **Worker has tests.** `worker/` (Node BullMQ diagnostics) ships `node --test`.

## 2. What is MVP-only (works, but not production-shaped)

- **The API process does everything.** One FastAPI lifespan runs seed + migrations + employee-init + data generator + cache warmer + forecast trainer. Fine for a single demo box; wrong for N replicas.
- **Health is binary.** Only `/health` (DB+Redis) and an authed `/api/monitoring/health/detailed`. No liveness/readiness separation for orchestrators.
- **Auth tokens are JWT-only.** Reset/verify tokens rely on JWT expiry; the `used_at` columns that exist in migration 001 are never written → replayable until expiry.
- **Invites use temporary passwords**, not single-use invite tokens.
- **No session management UI/API.** `user_sessions.revoked_at` exists but nothing lists or revokes sessions.
- **API keys never expire by date** (only manual revocation).

## 3. What is demo-only (must never be mistaken for real data)

- **All sales data is synthetic.** Historical data is a date-shifted Kaggle store-item demand dataset (units, 10 stores × 50 items); the live feed is a `DataGenerator` writing a synthetic sale every ~5–15 s. See `docs/product/DEMO_VS_REAL_DATA.md`.
- **Demo users** (`atharva@`, `krishna@`, `yash@retaildemo.app`) are seeded by `init.sql`.
- **`render.yaml`** is a **demo** deploy: it sets `ENVIRONMENT=production` **but** depends on the in-API seeder loading 913k rows and the generator running — i.e. it is production-env-but-demo-behavior. This contradiction is resolved in Phase 1/2 (demo behavior must be opt-in via `DEMO_MODE`).

## 4. What is risky in production (today, as written)

| # | Risk | Evidence |
|---|------|----------|
| R1 | **Migrations run from every API replica** | `main.py` lifespan calls `run_migrations()` unconditionally |
| R2 | **Seed runs from every API replica** | lifespan calls `run_seed()` unconditionally |
| R3 | **Synthetic generator runs in the production API** | `DataGenerator().start()` unconditionally |
| R4 | **Cross-tenant active data source** | `services/data_sources.get_active_source()` / `set_active()` have **no `tenant_id` filter** — global query/mutation |
| R5 | **Replayable reset/verify tokens** | `used_at` never written; single-use not enforced in DB |
| R6 | **No fail-closed feature flags** | `DEMO_MODE`, `ALLOW_DEMO_USERS`, `EXPOSE_API_DOCS`, generator/migration/seed toggles don't exist |
| R7 | **Redis unauthenticated in prod compose** | `docker-compose.production.yml` redis has no `--requirepass` |
| R8 | **No backup/restore/rollback tooling** | `scripts/` absent |
| R9 | **No readiness probe** | orchestrator can route traffic before DB/migrations ready |
| R10 | **Zero frontend tests** | no vitest/playwright; high regression risk on auth/data flows |

## 5. Readiness scores (current, honest)

Scored 0–10 against a real pilot deployment bar. These are starting points; the program raises them.

| Dimension | Score | One-line justification |
|-----------|:-----:|------------------------|
| **MVP completeness** | 8/10 | Rich features, real RBAC/RLS/AI; lacks self-serve data import |
| **Deployment readiness** | 3/10 | API does one-shot+background work; no process split; no migrate job |
| **Security readiness** | 6/10 | Strong middleware/RLS/secret-validation; cross-tenant data-source bug + token replay drag it down |
| **Operations readiness** | 2/10 | No backup/restore, no runbooks, no readiness probe, no metrics |
| **AI safety readiness** | 7/10 | SELECT-only guard + least-privilege role; needs external-AI gating + no-raw-SQL-in-prod + evidence/approval flows |

## 6. Test inventory

**Present (26 files)** incl. `test_health`, `test_tenant_isolation`, `test_tokens`, `test_ai_rbac`, `test_nl2sql_guard`, `test_api_keys`, `test_federation`, `test_rbac`, `test_security`, `test_onboarding`, `test_config`.
**Missing:** `test_production_config`, `test_imports`, `test_public_ingestion`, frontend tests (none), data-source isolation regression test.
**Trap:** backend tests must run **in-container** or in a `requirements.txt`-pinned venv — a global `httpx>=0.28` breaks the TestClient suites (documented in CLAUDE.md).

## 7. Documentation contradictions found

- `render.yaml` = `ENVIRONMENT=production` while relying on demo seed + generator (see §3).
- `README`/docs describe always-available live generator as a feature; in production that violates "no synthetic data in real tenants." Reconcile by making it `DEMO_MODE`-gated.
- `docs/README.md` indexes product/strategy docs but had **no production/operations section** until this program.

---

*Recommendations and remediation live in [`PRODUCTION_GAP_ANALYSIS.md`](PRODUCTION_GAP_ANALYSIS.md), [`RISK_REGISTER.md`](RISK_REGISTER.md), and [`READINESS_CHECKLIST.md`](READINESS_CHECKLIST.md). This file states current facts only.*
