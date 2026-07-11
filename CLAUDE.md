# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Paths below are relative to the repository root.

Start with `docs/README.md` for the organized documentation index. If you need the original audit and planning context, read `docs/archive/GAP_ANALYSIS.md` before assuming older claims are still current.

**Team & parallel-development governance** (three devs — Atharva/Krishna/Yash): `TEAM_OWNERSHIP.md` (who owns which modules — bounded-context, with a shared-file rules table), `PROJECT_STRUCTURE.md` (subsystem map + dependency graph + ownership overlay), `GIT_WORKFLOW.md` (trunk-based branching/PRs), `CONTRIBUTING.md` (run/test/build + how to extend without touching hubs), `.github/CODEOWNERS` (path→reviewer). **Two conflict hubs were refactored out:** add a backend endpoint via `backend/app/routes/registry.py` (not `main.py`); add a frontend page via `frontend/src/config/nav.tsx` (not `Sidebar.tsx`).

## Commands

```powershell
# Full stack (frontend :3000, backend :8000, Swagger :8000/docs)
docker compose up -d

# Migrations now auto-apply on startup (services/migration_runner.run_migrations, called
# from main.py lifespan) — no manual psql step. db_seeder execs init.sql idempotently at
# startup (no postgres-entrypoint mount in dev), bulk-loads train.csv and date-shifts
# history so the latest day is "yesterday". alembic/ holds only the E6-2 baseline squash
# (validated by test_alembic_baseline.py + the CI migrations job) — runtime migrations
# stay plain SQL. To re-trigger a clean seed: docker compose down -v.

# Full rebuild (Windows)
./rebuild.ps1

# Backend tests
docker exec sales_backend python -m pytest tests/ -v --tb=short   # in container (pinned deps)
cd backend; pytest                                                # locally — use a venv with
                                                                  # requirements.txt (see trap below)
pytest tests/test_security.py -k <name>                           # single test

# Frontend (compose does NOT hot-reload; run dev server on host instead)
cd frontend; npm install --legacy-peer-deps
npm run dev
npm run build
npx tsc --noEmit        # CI currently runs this with `|| true` — type errors exist silently

# Backups & DR (blueprint E0-1) — prod runs the `backup` sidecar automatically.
# Dev exercise / on-demand:
docker compose --profile backup up backup                 # nightly loop + on-start dump
docker compose --profile backup run --rm backup /bin/sh /scripts/backup-postgres.sh   # one-off dump
docker compose --profile backup run --rm backup /bin/sh /scripts/drill-restore.sh     # non-destructive restore drill
# The rehearsed restore runs in CI on every push (`backup-restore-drill`).
# Runbooks: docs/runbooks/BACKUP_AND_RESTORE.md, RESTORE_FROM_BACKUP.md
```

Demo logins (password `Demo@2026!`): `atharva@retaildemo.app` (super_admin), `krishna@retaildemo.app` (regional_manager, Dubai only), `yash@retaildemo.app` (store_manager, Al Barsha only).

**Product name is "Retail Intelligence"** (owner-confirmed), centralized in one place: backend `settings.product_name` (`PRODUCT_NAME` env) and frontend `src/lib/brand.ts` (`NEXT_PUBLIC_PRODUCT_NAME`) — never hardcode it elsewhere. The fictional demo retailer is **"Meridian Hypermarket"** (tenant 1 = "Meridian Retail"); Meridian is DATA (store names, tenant workspace), never the product brand. The old "Lulu" brand has been removed except where it refers to the real Lulu Group (trademark/market discussion in `docs/product/*`) or the actual GitHub repo URL.

Tests set their own env (`backend/tests/conftest.py` forces `ENVIRONMENT=testing` and dummy secrets before app imports) and don't need live Postgres/Redis for the config/security/middleware suites.

## Architecture

FastAPI (async SQLAlchemy 2 + asyncpg) + PostgreSQL 15 + Redis 7 + Next.js 14 App Router (TypeScript/Tailwind/Recharts), all via Docker Compose. NGINX only in `docker-compose.production.yml`.

**Live-data pipeline (the core of the app):** a `DataGenerator` asyncio task (started in `main.py` lifespan) writes a synthetic sale every ~5–15s to Postgres and publishes JSON to the Redis channel `sales:stream`; SSE endpoints under `/stream/*` (`routes/stream.py`, sse-starlette) relay Redis pub/sub to browsers; frontend components open `EventSource` connections. Channels: `sales:stream`, `alerts:stream`, `inventory:stream` (`services/redis_client.py`). **Generated rows are confined to the demo tenant (E0-8):** each carries `tenant_id = settings.demo_tenant_id` + `is_synthetic=true`, the generator only draws store/item ids that tenant actually owns, and migration 057's trigger on `sales_stream_raw` rejects a synthetic row on any other tenant. `services/demo_reset.py` wipes them nightly. Never write synthetic sales without those two columns set.

**Sales source of truth (post-migration 007):** `sales_historical` (immutable CSV) + `sales_stream_raw` (append-only generator) are unified by the `sales_fact_view` (UNION ALL, stream IDs offset by 1B). Runtime readers (kpis, sales, analytics, history, reports, forecast) now query `sales_fact_view`; the legacy `sales` table is retired. `is_streaming` distinguishes CSV history from generated events. The view carries `tenant_id` (migration 011) so RLS can scope it.

**Auth (post-pull):** `routes/auth.py` defines `get_current_user` / `require_role` / `require_permission`, and the data routers (`sales`, `kpis`, `analytics`, `history`, `inventory`, `promotions`, `reports`, `employees`, `procurement`, etc.) now depend on them with tenant + accessible-store scoping. `public_api` is API-key-authenticated (per-tenant `lsk_` keys). RBAC data (`users`, `user_permissions`, region→store expansion) lives in `init.sql`; permission aggregation is in `services/auth_service.py`. JWTs embed permissions at login; logout blacklists token hashes in Redis (checked by `SessionInvalidationMiddleware`, which fails open if Redis is down). Multi-tenancy: app-layer `tenant_id` scoping + Postgres RLS (migrations 010–012, FORCE-RLS opt-in via `USE_RLS_ROLE`).

**Schema is managed three ways:** `database/init.sql` (executed idempotently by `db_seeder` at startup — includes CSV bulk load and demo users), `database/migrations/0*.sql` (auto-applied by the migration runner), and a runtime employee migration (`services/employee_seeder.py` called from lifespan). `backend/alembic/` carries only the E6-2 baseline squash used by CI — not runtime migrations. To re-trigger a clean seed: `docker compose down -v`.

**Config:** `app/config.py` (pydantic-settings, env vars, `.env`). `settings.validate_security()` runs at startup and **raises in production/staging** on default secrets or `salespass` in the DB URL — set `JWT_SECRET_KEY`/`SECRET_KEY` ≥32 chars when testing with `ENVIRONMENT=production`.

**Middleware order** (`main.py`, first added = outermost): SecurityHeaders → CSRF (Bearer-exempt) → BodySizeLimit → SessionInvalidation → RateLimit (Redis sliding window per IP) → RequestID → CORS.

**Frontend:** every page under `src/app/*/page.tsx` is a large `'use client'` component. Auth state in `contexts/AuthContext.tsx` (**httpOnly-cookie auth — no token in localStorage (E0-5); only the user profile is stored, for cache scoping**; `withAuth` HOC, auto-refresh on 401). State-changing requests carry the CSRF double-submit header (`X-CSRF-Token`) from `apiClient.getCsrfToken()`; API clients using `Authorization: Bearer` stay CSRF-exempt. REST goes through `lib/api.ts` (a typed facade mapping endpoints to TTLs) over `lib/apiClient.ts` (low-level auth/refresh + the in-memory TTL cache). **That cache is keyed on the full authorization scope — `id|tenant|role|stores|regions` (E0-6)** — and flushes when the identity changes; keying it on `user.id` alone let a role switch serve the previous role's privileged data. SSE consumption is centralized in `hooks/useEventStream.ts` (ref-counted, one connection per endpoint) — no longer duplicated/hardcoded across the stream consumers.

## Known traps

- **Units vs currency (active accuracy focus).** The raw `sales` values are **units** (Kaggle store-item demand dataset, 10 stores × 50 items). Migration 005 added `items.unit_price_aed`, so AED **revenue is derived** as `SUM(sales * unit_price_aed)` (see `routes/kpis.py` — the reference implementation). The product convention is: VOLUME metrics in units, VALUE metrics in AED, **never mixed on one axis**. Phase 1 audited/enforced this across every sales reader and panel (see "Resolved" below); keep new code aligned with `routes/kpis.py`.
- **Local test env drift.** `requirements.txt` pins `httpx==0.26.0`; a newer global `httpx` (≥0.28) removed the `app=` kwarg and breaks starlette's `TestClient`, failing the ~7 TestClient-based suites. Run `pytest` in a venv installed from `requirements.txt` (or in the container) — CI/Docker are unaffected.
- Compose volume mounts suggest hot reload, but uvicorn lacks `--reload` and the frontend image serves a pre-built standalone bundle — rebuild containers (or run `npm run dev` on host) to see changes.
**Resolved since the June 2026 audit** (don't re-report): **E0-4** the stale prod-compose mounts are gone — `seed_data.sql` was deleted (nothing mounted it) and `train.csv` is intentionally NOT mounted in production, with `test_deploy_config.py` guarding both; the bare `RAISE NOTICE` in `init.sql` is now inside a `DO` block; `main.py` imports `EventSourceResponse` (working SSE is `/stream/sales`; `useSSE.ts` was deleted in favor of `hooks/useEventStream.ts`); migrations auto-apply on startup; history is date-shifted so "today/this week" KPIs are populated; CI now runs the full `pytest tests/` suite **and** `tsc --noEmit` (no longer `|| true`); **Phase 1 accuracy pass done** — units/AED audited & enforced across all sales readers/panels (fixed: admin Stores "Revenue (30d)" and "Sales Today" cards rendered units as AED; `KPICards` "Avg Daily Sales" mislabeled an AED value; `ai_assistant` store list now matches the `init.sql` seed and the prompt carries an explicit units≠AED convention); **E0-6** the frontend cache is authorization-scoped (was user-id-only, leaked across role switches); **E0-8** the generator is tenant-confined at the DB level and demo data resets nightly.



