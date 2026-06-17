# Codebase Map — Lulu Sales Intelligence Dashboard

> Deep-dive reference produced from a full repository inspection (June 2026).
> Status: student project being upgraded to a production-minded MVP. Not an official Lulu Hypermarket product; all data is synthetic.

---

## 1. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI 0.109, Python 3.11, Uvicorn | Async REST + SSE streaming |
| ORM / DB driver | SQLAlchemy 2.0 (async) + asyncpg | Mix of ORM models and raw `text()` SQL |
| Database | PostgreSQL 15 (Docker) | Schema via `database/init.sql` + 4 manual SQL migrations |
| Cache / messaging | Redis 7 | Pub/sub for live events, response cache, rate limiting, JWT blacklist |
| Streaming | Server-Sent Events via `sse-starlette` | Backend publishes to Redis channels; SSE endpoints relay to browsers |
| Frontend | Next.js 14.1 (App Router), React 18, TypeScript 5.3 | `output: 'standalone'` build |
| Styling | Tailwind CSS 3.4 | Dark slate/cyan theme, no component library |
| Charts | Recharts 2.10 | |
| PDF export | jsPDF + jspdf-autotable + html2canvas | Client-side report generation |
| Auth | JWT (python-jose) + bcrypt (passlib) | Access + refresh tokens, account lockout, audit log |
| AI (optional, paid) | OpenAI Chat Completions via raw `httpx` | Falls back to data-driven responses without a key |
| Voice (optional, paid) | Deepgram STT/TTS | `voice_service.py` |
| Infra | Docker Compose (dev + production variants), NGINX (prod only) | |
| Tests | pytest, pytest-asyncio (backend only) | 5 test modules |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | Backend tests, frontend build, Docker build checks |

**Important environment note:** the working folder is `lulu-sales-intelligence-dashboard-main\lulu-sales-intelligence-dashboard-main` (a GitHub ZIP download nested inside a folder of the same name). **It is not a git repository** — there is no version control history locally.

---

## 2. Folder Structure

```
lulu-sales-intelligence-dashboard-main/
├── .github/workflows/ci.yml      # CI: backend pytest, frontend build, docker build
├── docker-compose.yml            # Dev stack: postgres, redis, backend, frontend
├── docker-compose.production.yml # Prod stack: + nginx, healthchecks, resource limits
├── rebuild.ps1                   # Windows helper: full rebuild + restart
├── .env.example                  # Safe placeholder env vars
├── data/train.csv                # 16.9 MB Kaggle "store item demand" dataset (2013–2017, 10 stores × 50 items, UNITS not revenue)
├── database/
│   ├── init.sql                  # Auto-run on first postgres boot: schema, stores/items seed, CSV load, users/RBAC tables, demo users
│   ├── seed_data.sql             # ⚠ EMPTY (0 bytes) — referenced by production compose
│   └── migrations/00{1..4}_*.sql # Manual migrations: auth, inventory/alerts, promotions/analytics, employees
├── backend/
│   ├── Dockerfile                # python:3.11-slim, non-root user, uvicorn (no --reload)
│   ├── pytest.ini / requirements.txt
│   ├── alembic/                  # ⚠ Configured but EMPTY — alembic is not actually used
│   └── app/
│       ├── main.py               # App factory, lifespan, global error handlers, middleware order, routers, /health
│       ├── config.py             # pydantic-settings; validate_security() fail-fast in prod/staging
│       ├── middleware.py         # RequestID, RateLimit (Redis sliding window), SecurityHeaders/CSP, BodySize, CSRF, SessionInvalidation
│       ├── models/               # SQLAlchemy models (sales.py, employee.py)
│       ├── routes/               # 14 routers (see §5)
│       └── services/             # Business logic (see §5)
├── frontend/
│   ├── Dockerfile                # Multi-stage, standalone output, non-root
│   ├── next.config.js            # standalone output, chunk splitting
│   ├── tailwind.config.js        # minimal: blue "primary" palette only
│   └── src/
│       ├── app/                  # App Router pages: / (dashboard), login, analytics, inventory, promotions, alerts, employees, admin, reports, monitoring
│       ├── components/           # Navbar, KPICards, LiveTable, ChatBot, modals, charts/
│       ├── contexts/AuthContext.tsx
│       ├── hooks/                # useSSE, useAlertStream, useSalesData
│       ├── lib/                  # api.ts (fetch + in-memory cache), formatters.ts (AED), pdfExport.ts
│       └── types/
└── nginx/nginx.conf              # Reverse proxy for production compose
```

---

## 3. Main User Flows

1. **Login** → `frontend/src/app/login/page.tsx` → `POST /api/auth/login` → JWT access+refresh stored in **localStorage** → `AuthContext` gates pages via `withAuth` HOC. Demo users: `atharva@lulu.ae` (super_admin), `krishna@lulu.ae` (regional_manager, Dubai), `yash@lulu.ae` (store_manager, Al Barsha). Shared password `Lulu@2026!` (seeded in `init.sql`).
2. **Live dashboard** (`/`) → KPI cards poll `/api/kpis`; LiveTable/LiveStreamChart open `EventSource(${API_URL}/stream/sales)`; events originate from the background `DataGenerator`.
3. **Domain modules** — analytics, inventory, promotions, alerts, employees, reports, monitoring, admin — each is one large page component calling its corresponding router.
4. **AI chat** → ChatBot component → `/api/ai/chat/stream` → OpenAI (if key set) else data-driven fallback built from live DB queries.

---

## 4. Data Flow (the heart of the system)

```
DataGenerator (asyncio task in FastAPI lifespan, every ~5–15s)
   └─ writes a row to legacy `sales` table (is_streaming=true)
   └─ publishes enriched JSON to Redis channel `sales:stream`
        └─ /stream/sales (SSE) relays Redis messages to every connected browser
             └─ LiveTable / LiveStreamChart / ReturnsLiveFeed update in place
```

The generator simulates market sentiment, time-of-day curves, weekend effects, promotional bursts, bulk purchases, and **returns (negative sales values, ~10–18% rate)**.

**⚠ Architectural drift:** `init.sql` defines the README's intended architecture — `sales_historical` (immutable CSV load) + `sales_stream_raw` (append-only, UUID-deduped) + `sales_fact_view` (UNION view). But the running code (generator, KPIs, analytics, predictor, AI assistant) reads and writes the **legacy `sales` table** almost exclusively. The "new" tables receive the CSV copy at init and then sit idle.

---

## 5. Backend Architecture

### Startup (lifespan in `main.py`)
1. `settings.validate_security()` — raises `RuntimeError` in production/staging when JWT/app secrets are known-insecure defaults or DB URL contains `salespass`.
2. `init_db()` — retry loop (30 × 3 s) until Postgres answers.
3. `init_redis()` — global client + pubsub.
4. `initialize_employee_system()` — *runtime* migration + seeding for employee tables (wrapped in try/except, failure tolerated).
5. Spawns `DataGenerator().start()` as a background task.

### Middleware stack (order matters; first added = outermost)
SecurityHeaders (CSP/HSTS/XFO) → CSRF (double-submit cookie; Bearer requests exempt) → BodySizeLimit (10 MB) → SessionInvalidation (Redis token blacklist, **fail-open**) → RateLimit (Redis sliding window per IP, in-memory fallback) → RequestID → CORS.

### Routers (`app/routes/`) and their auth status
| Router | Prefix | Auth enforced? |
|---|---|---|
| auth.py | /api/auth | login/refresh open; profile/validate/logout require Bearer. Defines `get_current_user`, `require_role`, `require_permission` |
| admin.py | /api/admin | ✅ role-checked |
| inventory.py | /api/inventory | ✅ |
| promotions.py | /api/promotions | ✅ |
| alerts.py | /api/alerts | ✅ |
| reports.py | /api/reports | ✅ |
| **sales.py** | /api/sales | ❌ **no auth** |
| **kpis.py** | /api/kpis | ❌ **no auth** |
| **analytics.py** | /api/analytics | ❌ **no auth** |
| **history.py** | /api/history | ❌ **no auth** |
| **stream.py** | /stream | ❌ **no auth** (SSE) |
| **employees.py** | /api/employees | ❌ **no auth** |
| **monitoring.py** | /api/monitoring | ❌ **no auth** |
| **ai.py** | /api/ai | ❌ **no auth** |

The README's claim that core endpoints require Bearer tokens is **not true today** — see GAP_ANALYSIS.

### Services (`app/services/`)
- `database.py` — async engine (pool 20+30, pre-ping), `get_db` dependency commits per request.
- `redis_client.py` — global client, channel constants (`sales:stream`, `alerts:stream`, `inventory:stream`), `publish_*`, `cache_get/set`.
- `auth_service.py` — bcrypt hashing, 12-char password policy, JWT create/decode, lockout (5 attempts → 30 min), permission aggregation from `user_permissions` (region → stores expansion), audit logging, Redis token blacklist on logout.
- `data_generator.py` — synthetic event stream (see §4). Uses `print()` not the logger; hardcodes store ids 1–10 and item ids 1–50.
- `ai_assistant.py` (39 KB) — per-session in-memory `ConversationContext` (max 1000, FIFO eviction), real-time KPI/DB queries injected into prompts, raw httpx calls to OpenAI, rule-based fallback when no key.
- `predictor.py` — moving average + linear trend + sinusoidal day-of-week seasonality, ±1.96σ confidence band, Redis-cached 1 h. Reads legacy `sales` table.
- `voice_service.py` — Deepgram STT/TTS (paid, optional).
- `employee_generator.py` / `employee_seeder.py` / `employee_performance_streamer.py` — synthetic workforce profiles, runtime table creation/seeding, live performance SSE.
- `data_sync.py` (34 KB) — inventory/alert sync logic.
- `cache.py`, `metrics.py` — Redis response cache helpers; system metrics for monitoring page.

---

## 6. Database / Schema

Created in three competing ways (a known weakness):
1. `database/init.sql` (auto-run by the postgres image on **first** boot of an empty volume): `stores` (10 Lulu UAE branches with regions), `items` (50 realistic UAE grocery SKUs), `sales_historical`, `sales_stream_raw`, legacy `sales`, `predictions`, `sales_fact_view`, plus `regions`, `users`, `user_permissions`, `audit_log` and the 3 demo users.
2. `database/migrations/001–004_*.sql` — applied **manually** via `docker exec … psql` (per README). Add auth extras, inventory + alert tables, promotions/analytics tables, employee tables.
3. `initialize_employee_system()` — creates/seeds employee tables at backend startup.

`alembic/` exists but is empty; it manages nothing.

**Semantics warning:** the Kaggle dataset's `sales` column is **units sold**, but the frontend (`lib/formatters.ts`) formats most figures as **AED currency**. There is no price/revenue column anywhere.

---

## 7. Frontend Architecture

- **App Router**, but every page is a `'use client'` mega-component (admin 45 KB, inventory 46 KB, promotions 32 KB). No server components in practice, no shared data layer beyond `lib/api.ts`.
- **AuthContext** (`contexts/AuthContext.tsx`): login/logout/refresh, permission helpers (`hasRole`, `canAccessStore`…), `withAuth` HOC, plus a *duplicate* module-level `authFetch` utility. Tokens in localStorage.
- **lib/api.ts**: fetch wrapper with 10 s timeout and an in-memory TTL cache (per endpoint type). Cache is **not user-aware** — switching users can serve the previous user's cached data.
- **SSE consumers**: `useSSE` (default URL `NEXT_PUBLIC_SSE_URL` → `/api/stream` — a route that doesn't exist, see GAP_ANALYSIS), while components mostly hardcode `${API_URL}/stream/sales` and `${API_URL}/stream/alerts` directly with their own reconnect logic — at least 6 separate EventSource implementations.
- **Styling**: hand-rolled Tailwind dark theme (slate-900 + cyan accents), inline everywhere; tailwind.config defines only a blue `primary` palette that is barely used.

---

## 8. External Services

| Service | Used for | Required? | Free? |
|---|---|---|---|
| OpenAI API | AI chat streaming | No (fallback exists) | ❌ paid |
| Deepgram API | Voice STT/TTS | No | ❌ paid (has free tier) |

Everything else (Postgres, Redis, NGINX) is self-hosted in Docker. No telemetry, no cloud SDKs.

---

## 9. Build / Run / Test Commands

```powershell
# Full stack (dev)
docker compose up -d                 # frontend :3000, backend :8000, docs :8000/docs
docker compose ps                    # verify

# First-run migrations (manual!)
Get-Content database/migrations/001_auth_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
# … repeat for 002, 003, 004

# Rebuild from scratch (Windows)
./rebuild.ps1

# Backend tests (inside container)
docker exec sales_backend python -m pytest tests/ -v --tb=short
# Backend tests (locally, needs pip install -r backend/requirements.txt)
cd backend; pytest                   # pytest.ini adds -v --tb=short
pytest tests/test_security.py -k insecure   # single test

# Frontend
cd frontend
npm install --legacy-peer-deps
npm run dev                          # local dev server (NOT used by docker compose)
npm run build                        # production build
npx tsc --noEmit                     # type check (CI currently ignores failures!)
```

Notes:
- The dev compose **does not hot-reload**: backend runs uvicorn without `--reload`, frontend image runs the pre-built standalone server; the `./backend/app` and `./frontend/src` volume mounts are effectively decorative for the frontend and only partially effective for the backend.
- CI (`ci.yml`) runs only `tests/test_config.py` and `tests/test_security.py`; the TypeScript check is `|| true`.

---

## 10. Important Files Quick Reference

| File | Why it matters |
|---|---|
| `backend/app/main.py` | Everything wires together here; middleware order; legacy `/api/stream/sales` shim (currently broken — missing import) |
| `backend/app/config.py` | All env vars + the production fail-fast security validation |
| `database/init.sql` | The real source of truth for core schema + demo users (contains a syntax error at line 369) |
| `backend/app/services/data_generator.py` | The "live data" illusion — the whole demo depends on it |
| `frontend/src/contexts/AuthContext.tsx` | All client-side auth/RBAC behavior |
| `frontend/src/lib/api.ts` | Every REST call funnels through here |
| `docker-compose.yml` / `docker-compose.production.yml` | The two supported run modes |

---

## 11. Confusing / Risky Areas (read GAP_ANALYSIS.md for full list)

1. **Three sales tables**, only the legacy one actually used at runtime.
2. **Auth exists but isn't applied** to the majority of data endpoints; RBAC store/region scoping is enforced client-side only for those routes.
3. **`init.sql` line 369**: bare `RAISE NOTICE` outside a `DO` block — psql runs initdb scripts with `ON_ERROR_STOP=1`, so a **fresh database volume fails to initialize**.
4. **`main.py:214`**: `EventSourceResponse` is referenced but never imported in that module → `NameError` on `/api/stream/sales`; meanwhile `useSSE.ts` defaults to `/api/stream`, which matches no route at all.
5. **Units displayed as AED currency** — numbers are unit counts from the Kaggle dataset.
6. **Schema management chaos**: init.sql vs manual SQL migrations vs runtime employee migration vs empty alembic.
7. **Token model**: permissions baked into JWT (stale until expiry), blacklist check fails open if Redis is down, `remember_me` silently makes a 7-day *access* token.
8. Duplicated SSE/auth-fetch logic across many frontend files; in-memory API cache shared across users.
9. `data/train.csv` (17 MB) committed to the repo; dates end in 2017 while the UI implies "today".
10. No git history, empty `seed_data.sql`, empty `alembic/` — artifacts of rapid student iteration.
