# Retail IQ

> A full-stack, real-time retail sales-intelligence dashboard for a UAE supermarket chain — built as a **portfolio / MVP demonstration** of real-time data systems, analytics, RBAC security, and local-first AI. The data is **synthetic** (see [Data & Honesty Notes](#data--honesty-notes)); the engineering is real.

[![CI Pipeline](https://github.com/mercydeez/lulu-sales-intelligence-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/mercydeez/lulu-sales-intelligence-dashboard/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=nextdotjs)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docs.docker.com/compose/)

---

## Table of Contents

- [What This Is](#what-this-is)
- [Data & Honesty Notes](#data--honesty-notes)
- [Getting Started](#getting-started)
- [Live URLs & Demo Logins](#live-urls--demo-logins)
- [Architecture](#architecture)
- [The Live-Data Pipeline](#the-live-data-pipeline)
- [Tech Stack](#tech-stack)
- [Features (what actually works)](#features-what-actually-works)
- [Security](#security)
- [Configuration](#configuration)
- [Testing & CI](#testing--ci)
- [Project Structure](#project-structure)
- [Further Reading](#further-reading)
- [Roadmap](#roadmap)
- [Author](#author)

---

## What This Is

A real-time retail sales-intelligence dashboard for a fictional UAE supermarket chain ("Meridian"). It demonstrates:

- **A live data pipeline** — a background generator writes a synthetic sale every ~5–15s to PostgreSQL and publishes it to Redis; Server-Sent Events relay it to the browser, which updates without polling.
- **Analytics & forecasting** — sales trends, category/store breakdowns, top items, and a seasonal demand forecast with a MAPE backtest against a seasonal-naive baseline.
- **RBAC security** — JWT auth with region→store access scoping, rate limiting, CSRF, and a hardened security-header/middleware stack.
- **Operational modules** — inventory/expiry, alerts→tasks, promotions, employee performance, an admin console, reports, and system monitoring.
- **Local-first AI** — a chat assistant that prefers a local Ollama model, optionally uses OpenAI, and always falls back to a deterministic rule-based responder backed by live DB data (no paid API key required to run).

It is a **single-developer MVP**, not a deployed production system. The honesty notes below say exactly what is real, what is synthetic, and what is simplified.

---

## Data & Honesty Notes

This project deliberately documents its own simplifications — read this before trusting any figure on screen.

- **The data is synthetic.** Historical rows come from the public Kaggle *Store Item Demand Forecasting* dataset: **10 stores × 50 items, daily, 2013–2017**. On a fresh database the dates are **shifted forward** so that "today" always has data. Live rows are produced by an in-app generator, not a real POS.
- **`sales` values are UNITS, not currency.** The dataset has no price column. The number you see as a raw count is units sold.
- **Revenue (AED) is *derived*.** Migration `005` adds a per-item `unit_price_aed`; revenue = `units × unit_price_aed`. This derivation is applied **only** in the `/api/analytics/*` endpoints and KPIs. The **Reports** screen (`/api/reports/sales`) intentionally shows **raw units** and labels them as such, because that endpoint does not join the price.
- **Stores/employees/promotions are generated**, not from a real HR or merchandising system. Employee gender distribution and performance weights are explicit and visible, not hidden heuristics.
- **The AI assistant does not need a paid key.** Default path is local Ollama; OpenAI is opt-in via env var; if neither is configured it answers from live database aggregates via a rule-based responder.
- **"Real-time" means ~5–15s**, the generator's cadence — not sub-second tick data.

---

## Getting Started

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) + Docker Compose
- Git

### Quick Start
```bash
git clone https://github.com/mercydeez/lulu-sales-intelligence-dashboard.git
cd lulu-sales-intelligence-dashboard

docker compose up -d      # starts db, redis, backend, frontend
docker compose ps         # all four should be "Up"; db/redis show "healthy"
```

**Migrations apply themselves.** On startup the backend runs a migration runner that applies every `database/migrations/00*.sql` in order (tracked in a `schema_migrations` table), then a runtime employee seeder. `database/init.sql` also auto-runs the first time the Postgres volume is created (bulk-loads the CSV history and seeds demo users). No manual `psql` step is required.

To start completely fresh (re-trigger `init.sql`): `docker compose down -v && docker compose up -d`.

> **macOS/Linux note:** the repo's helper scripts (`rebuild.ps1`) are PowerShell; on macOS/Linux just use the `docker compose` commands above.

---

## Live URLs & Demo Logins

With the stack running:

| Service | URL |
|---|---|
| **Frontend (dashboard)** | http://localhost:3000 |
| **Backend API** | http://localhost:8000 |
| **Swagger / OpenAPI docs** | http://localhost:8000/docs |
| **Health check** | http://localhost:8000/health |

Demo users (password for all three: **`Demo@2026!`**):

| Role | Email | Access scope |
|------|-------|-------------|
| Super Admin | `atharva@retaildemo.app` | all regions & stores |
| Regional Manager | `krishna@retaildemo.app` | Dubai region only |
| Store Manager | `yash@retaildemo.app` | Al Barsha store only |

Logging in as the regional/store users is the quickest way to see RBAC scoping in action — the same screens show only the data each role is allowed to see.

**Self-serve onboarding (SaaS):** new customers don't need a seeded account — visit **`/signup`** to provision an isolated tenant workspace (optionally pre-loaded with sample data so the dashboard works immediately), then invite teammates from the app. Every tenant's data is isolated (app-layer scoping + Postgres RLS); a second seeded tenant (`owner@northwind.ae`) demonstrates two-tenant isolation. See [`docs/PUBLIC_API.md`](docs/PUBLIC_API.md) for the per-tenant public API + embeddable AI.

---

## Architecture

```
                 Browser (Next.js 14, App Router, 'use client' pages)
                  │  REST (fetch via a single auth-aware API client)
                  │  SSE (EventSource → ticket-authenticated /stream/*)
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (async, Python 3.11)               │
│  middleware: SecurityHeaders → CSRF → BodySize →              │
│              SessionInvalidation → RateLimit → RequestID → CORS│
│  routers: auth, kpis, sales, analytics, history, inventory,   │
│           alerts, promotions, employees, admin, reports,      │
│           monitoring, ai, stream                              │
│  lifespan: migration runner → employee seeder → DataGenerator │
└───────────────┬─────────────────────────────┬────────────────┘
                │                              │
        ┌───────▼────────┐            ┌────────▼────────┐
        │  PostgreSQL 15  │            │     Redis 7     │
        │  • sales_*      │            │  • pub/sub      │
        │  • users / RBAC │            │    (sales/alerts│
        │  • employees    │            │     /inventory) │
        │  • alerts/inv   │            │  • rate-limit   │
        │                 │            │  • token block  │
        └─────────────────┘            └─────────────────┘
```

NGINX is present only in `docker-compose.production.yml` (TLS termination / reverse proxy); the dev stack talks to the services directly.

---

## The Live-Data Pipeline

This is the core of the app:

1. A `DataGenerator` asyncio task (started in the FastAPI lifespan) writes a synthetic sale every **~5–15s** to PostgreSQL and publishes the event as JSON to the Redis channel `sales:stream` (also `alerts:stream`, `inventory:stream`).
2. SSE endpoints under `/stream/*` (sse-starlette) relay Redis pub/sub to browsers.
3. Frontend components open an `EventSource` and update KPIs, the live table, and charts in place.

**SSE auth:** because `EventSource` can't send an `Authorization` header, the streams are authenticated with a short-lived **stream ticket** — the client POSTs `/api/auth/stream-ticket` and passes the returned token as `?ticket=…`. The working stream URL is `/stream/sales`.

**Sales storage** uses a three-table design unified by a view: `sales_historical` (CSV) + `sales_stream_raw` (live events) → `sales_fact_view` (the union every reader queries). The legacy single `sales` table was dropped in migration `007`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router, TypeScript), Tailwind CSS, Recharts, Lucide |
| Backend | FastAPI, async SQLAlchemy 2 + asyncpg, sse-starlette, Python 3.11 |
| Database | PostgreSQL 15 |
| Cache / Pub-Sub | Redis 7 |
| AI | Ollama (local default) · OpenAI (optional) · rule-based fallback |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Infra | Docker Compose (+ NGINX in the production compose) |

---

## Features (what actually works)

- **Live operations home** — real-time KPIs (count-up tickers, reduced-motion aware), live sales feed, trend/category/store charts, returns analysis.
- **Analytics & Forecast** — real `/api/analytics/*` data; an interactive seasonal forecast with a **MAPE backtest vs a seasonal-naive baseline**. (Figures here are AED revenue — the only place units are priced.)
- **Inventory / Procurement** — stock levels derived from sales velocity, low-stock/out-of-stock alerts, an SSE-degraded connection banner.
- **Alerts → Tasks** — persisted alert workflow: acknowledge, resolve-with-notes, and a "My Tasks" view.
- **Promotions** — summary, active campaigns, category performance (real shape), and a create flow scoped to the user's accessible stores.
- **Employees / Performance** — bio cards, role/store analytics, performance charts (line/bar/radar) over real seeded data.
- **Admin** — honest **read-only** console (the admin backend is GET-only): dashboard, users, stores, activity feed; super-admin gated.
- **Reports** — single rich endpoint feeding KPIs + daily/category/store/item tables; **labelled in units** with a PDF export that states the no-price caveat.
- **Monitoring** — live `/api/monitoring/*` health, system stats, and metrics with an auto-refresh toggle.
- **AI assistant** — chat over live data with the local-first provider chain described above.
- **Design & a11y** — a "Sunset Pop" design system, **EN/AR with RTL**, WCAG-AA-checked contrast, focus-visible keyboard rings, and `aria-live` on live regions.

---

## Security

- **JWT auth** — access + refresh with rotation; logout blacklists token hashes in Redis (checked by `SessionInvalidationMiddleware`, which fails open if Redis is down).
- **RBAC** — region→store expansion; managers/admins are scoped server-side to their accessible stores. Note: the `admin`, `inventory`, `promotions`, `alerts`, `reports` routers enforce auth/roles; read/stream endpoints use optional auth or stream tickets.
- **Hardened middleware** — CSP (env-driven `connect-src`, `object-src 'none'`, prod `upgrade-insecure-requests`), HSTS, `X-Frame-Options`, `X-Content-Type-Options`; CORS with **enumerated** methods/headers (required once credentials are allowed); Redis sliding-window rate limiting with in-memory fallback; CSRF double-submit for non-Bearer requests; request body-size limit.
- **Structured logging** — a per-request `request_id` (reusing an inbound `X-Request-ID`) is threaded through **every** log line via a contextvar + log filter; optional JSON log output.
- **Fail-fast config** — in `production`/`staging`, startup raises on default secrets, short JWT keys, or default DB credentials.
- **Hardening details** are recorded in [`docs/architecture/ADR.md`](docs/architecture/ADR.md) (ADR-009) and the **Track 2** section of [`implementation.md`](implementation.md).

---

## Configuration

Backend settings (pydantic-settings; env vars or `.env`):

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb` | — |
| `REDIS_URL` | `redis://redis:6379` | — |
| `ENVIRONMENT` | `development` | `production`/`staging` enable fail-fast security checks |
| `JWT_SECRET_KEY` / `SECRET_KEY` | dev defaults | **must be ≥32 chars & non-default in production** |
| `CORS_ORIGINS` | `http://localhost:3000,http://frontend:3000` | comma-separated, enumerated |
| `CSP_CONNECT_SRC` | localhost dev origins | set to your API/ws origins in prod |
| `OLLAMA_URL` / `OLLAMA_MODEL` | — / `llama3.2` | enables the local AI provider |
| `OPENAI_API_KEY` | — | optional; opt-in AI provider |
| `LOG_JSON` | `false` | emit one JSON log object per line |
| `RATE_LIMIT_REQUESTS` | `100` | per minute per IP |

Frontend: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

---

## Testing & CI

```bash
# full backend suite (in the running container)
docker exec sales_backend python -m pytest tests/ -v --tb=short

# or locally
cd backend && pytest
```

92 backend tests cover config, security validation, health, and middleware. **GitHub Actions** (`.github/workflows/ci.yml`) runs three jobs on push/PR to `main`:

1. **Backend** — install deps, verify imports, run the full `pytest tests/`.
2. **Frontend** — `npx tsc --noEmit` (type check, enforced) + `npm run build`.
3. **Docker** — `docker compose config -q` + build both images.

Health check:
```bash
curl http://localhost:8000/health
# {"status":"healthy","database":"healthy","redis":"healthy","version":"1.0.0","environment":"development"}
```

All API errors return a consistent envelope (`error`, `status_code`, `message`, `path`, `timestamp`); validation errors add field-level `details`.

---

## Project Structure

```
backend/                      FastAPI app
  app/
    main.py                   entry point, lifespan, error handlers, middleware order
    config.py                 pydantic settings, security validation, logging (req-id, JSON)
    middleware.py             security headers, CSRF, rate limit, request-id, session check
    models/                   SQLAlchemy ORM models
    routes/                   one module per feature area
    services/                 data generator, migration runner, seeders, redis, data_sync
  tests/                      pytest suite (config, security, health, middleware)
database/
  init.sql                    base schema + CSV load + demo users (fresh-volume only)
  migrations/00*.sql          versioned migrations (auto-applied by the runner)
frontend/
  src/app/*/page.tsx          one 'use client' page per screen (thin composers)
  src/components/<feature>/   feature-folder components + barrels
  src/contexts/               AuthContext, LanguageContext (EN/AR)
  src/lib/                    auth-aware API client, formatters, PDF export
docs/                         indexed documentation (architecture, product, archive)
docker-compose.yml            dev stack
docker-compose.production.yml prod stack (adds NGINX)
implementation.md             single living forward roadmap (what's shipped + what's next)
```

---

## Further Reading

- [docs/README.md](docs/README.md) - documentation index and folder guide.

- [`docs/product/DEMO_SCRIPT.md`](docs/product/DEMO_SCRIPT.md) — a guided 8-minute walkthrough for reviewers.
- [`docs/architecture/ADR.md`](docs/architecture/ADR.md) — architecture decision records (the *why* behind the design).
- [`docs/product/PITCH.md`](docs/product/PITCH.md) — one-page pitch: problem, approach, and engineering tradeoffs.
- [`implementation.md`](implementation.md) — the single living forward roadmap (verified state + the remaining tracks).
- [`docs/archive/GAP_ANALYSIS.md`](docs/archive/GAP_ANALYSIS.md) — the original honest audit that drove the roadmap.

---

## Roadmap

**Done:** real-time pipeline · RBAC + server-side scoping · derived revenue model · seasonal forecast + MAPE backtest · local-first AI chain · full UI redesign (8 screens) · EN/AR + RTL · WCAG-AA contrast · production hardening (CSP/CORS, structured logging, covering index, pagination, transaction-safe alert generation).

**Next:** ML forecasting (Prophet/LSTM) trained on the history · frontend component tests · self-hosted Arabic web font · richer admin write operations (needs new backend endpoints) · WebSocket upgrade from SSE.

---

## Author

**Atharva Soundankar** — [GitHub](https://github.com/mercydeez)

A portfolio demonstration of full-stack engineering, real-time data systems, and pragmatic, honestly-scoped AI integration.

<p align="center"><sub>FastAPI · Next.js · PostgreSQL · Redis · Docker</sub></p>




