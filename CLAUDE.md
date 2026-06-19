# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Paths below are relative to the repository root.

Start with `docs/README.md` for the organized documentation index. If you need the original audit and planning context, read `docs/archive/GAP_ANALYSIS.md` before assuming older claims are still current.

## Commands

```powershell
# Full stack (frontend :3000, backend :8000, Swagger :8000/docs)
docker compose up -d

# First run only — migrations are applied MANUALLY (no alembic despite the alembic/ dir):
Get-Content database/migrations/001_auth_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
# repeat for 002, 003, 004

# Full rebuild (Windows)
./rebuild.ps1

# Backend tests
docker exec sales_backend python -m pytest tests/ -v --tb=short   # in container
cd backend; pytest                                                # locally (pytest.ini adds -v --tb=short)
pytest tests/test_security.py -k <name>                           # single test

# Frontend (compose does NOT hot-reload; run dev server on host instead)
cd frontend; npm install --legacy-peer-deps
npm run dev
npm run build
npx tsc --noEmit        # CI currently runs this with `|| true` — type errors exist silently
```

Demo logins (password `Lulu@2026!`): `atharva@lulu.ae` (super_admin), `krishna@lulu.ae` (regional_manager, Dubai only), `yash@lulu.ae` (store_manager, Al Barsha only).

Tests set their own env (`backend/tests/conftest.py` forces `ENVIRONMENT=testing` and dummy secrets before app imports) and don't need live Postgres/Redis for the config/security/middleware suites.

## Architecture

FastAPI (async SQLAlchemy 2 + asyncpg) + PostgreSQL 15 + Redis 7 + Next.js 14 App Router (TypeScript/Tailwind/Recharts), all via Docker Compose. NGINX only in `docker-compose.production.yml`.

**Live-data pipeline (the core of the app):** a `DataGenerator` asyncio task (started in `main.py` lifespan) writes a synthetic sale every ~5–15s to Postgres and publishes JSON to the Redis channel `sales:stream`; SSE endpoints under `/stream/*` (`routes/stream.py`, sse-starlette) relay Redis pub/sub to browsers; frontend components open `EventSource` connections. Channels: `sales:stream`, `alerts:stream`, `inventory:stream` (`services/redis_client.py`).

**Three sales tables, one real:** `sales_historical` + `sales_stream_raw` + `sales_fact_view` implement the README's intended design, but **all runtime code (generator, kpis, sales, analytics, history, predictor, ai_assistant) uses the legacy `sales` table** (`is_streaming` flag distinguishes CSV history from generated events). Don't add features against the unused tables without migrating the readers.

**Auth split (important):** `routes/auth.py` defines `get_current_user` / `require_role` / `require_permission`; only `admin`, `inventory`, `promotions`, `alerts`, `reports` routers actually use them. `sales`, `kpis`, `analytics`, `history`, `stream`, `employees`, `monitoring`, `ai` are **unauthenticated**, despite the README claiming otherwise. RBAC data (`users`, `user_permissions`, region→store expansion) lives in `init.sql`; permission aggregation is in `services/auth_service.py`. JWTs embed permissions at login time; logout blacklists token hashes in Redis (checked by `SessionInvalidationMiddleware`, which fails open if Redis is down).

**Schema is managed three ways:** `database/init.sql` (auto-runs only on a fresh postgres volume — includes CSV bulk load and demo users), manual `database/migrations/00*.sql`, and a runtime employee migration (`services/employee_seeder.py` called from lifespan). `backend/alembic/` is empty/unused. To re-trigger init.sql: `docker compose down -v`.

**Config:** `app/config.py` (pydantic-settings, env vars, `.env`). `settings.validate_security()` runs at startup and **raises in production/staging** on default secrets or `salespass` in the DB URL — set `JWT_SECRET_KEY`/`SECRET_KEY` ≥32 chars when testing with `ENVIRONMENT=production`.

**Middleware order** (`main.py`, first added = outermost): SecurityHeaders → CSRF (Bearer-exempt) → BodySizeLimit → SessionInvalidation → RateLimit (Redis sliding window per IP) → RequestID → CORS.

**Frontend:** every page under `src/app/*/page.tsx` is a large `'use client'` component. Auth state in `contexts/AuthContext.tsx` (tokens in localStorage, `withAuth` HOC, auto-refresh on 401). REST goes through `lib/api.ts` (in-memory TTL cache — not user-aware). SSE consumption is duplicated across ~6 files, mostly hardcoding `${API_URL}/stream/sales`.

## Known traps

- `database/init.sql:369` has a bare `RAISE NOTICE` outside a `DO` block → **fresh-volume DB init fails** until fixed.
- `main.py:214` uses `EventSourceResponse` without importing it → `/api/stream/sales` 500s; `hooks/useSSE.ts` defaults to `/api/stream`, which matches no route. Working SSE URL is `/stream/sales`.
- The DB `sales` values are **units** (Kaggle store-item demand dataset, 10 stores × 50 items, dates 2013–2017), but `lib/formatters.ts` renders most figures as AED currency. There is no price column.
- Historical data ends in 2017, so "today/this week" KPIs reflect only generator output.
- CI runs only `tests/test_config.py` + `tests/test_security.py` and ignores tsc failures.
- Compose volume mounts suggest hot reload, but uvicorn lacks `--reload` and the frontend image serves a pre-built standalone bundle — rebuild containers (or run `npm run dev` on host) to see changes.
- `database/seed_data.sql` is empty (0 bytes) yet mounted by the production compose; production compose also mounts `train.csv` at a path `init.sql`'s COPY doesn't read.



