# Architecture Plan - Production-Minded MVP

> Historical note: this file captures the June 2026 audit or planning state. Some issues listed here were later fixed. Use [../../README.md](../../README.md) and [../README.md](../README.md) for the current project state.


> Principle: **evolve, don't rewrite.** The FastAPI + Next.js + Postgres + Redis core is sound and interview-defensible. We fix the drift, enforce the boundaries the README already promises, and stay 100% free/local-first.

---

## 1. Target system shape (unchanged at the box level)

```
Browser ──HTTP/SSE──▶ Next.js 14 ──REST──▶ FastAPI ──▶ PostgreSQL 15
                          │                   │
                          └──────SSE──────────┼──▶ Redis 7 (pub/sub, cache,
                                              │         rate-limit, blacklist)
                              (optional, free) └──▶ Ollama (local LLM)
```

What changes is the **internal discipline**, not the boxes.

---

## 2. Backend structure (recommended)

```
backend/app/
├── main.py                  # wiring only: middleware, routers, lifespan
├── config.py                # settings + security validation (keep as-is)
├── api/                     # (rename of routes/) thin HTTP layer
│   ├── deps.py              # get_db, get_current_user, require_role, ScopedUser
│   └── v1/{sales,kpis,analytics,inventory,...}.py
├── services/                # business logic, no HTTP types
├── repositories/            # all SQL lives here (per aggregate: sales, inventory, users)
├── schemas/                 # pydantic request/response models (extract from route files)
├── models/                  # SQLAlchemy models — single Base, matches real schema
└── workers/                 # data_generator, employee_streamer (background tasks)
```

Migration is mechanical: move code, don't change behavior. Do it incrementally per module (start with `sales`/`kpis` when adding auth — you're touching them anyway).

### Key backend decisions

1. **One sales source of truth.** Adopt the documented design fully: generator writes `sales_stream_raw` (UUID dedup), history lives in `sales_historical` (date-shifted on load so it ends "yesterday"), all reads go through `sales_fact_view`. Drop the legacy `sales` table at the end of Phase 2 (after all readers are migrated — grep confirms readers in kpis, sales, analytics, history, predictor, ai_assistant, data_generator).
2. **Auth as a router-level dependency.** `APIRouter(dependencies=[Depends(get_current_user)])` per data router so no endpoint can be added unprotected by accident. A `ScopedUser` dependency exposes `accessible_store_ids` for query filtering — one `WHERE store_id = ANY(:ids)` clause pattern reused everywhere.
3. **SSE auth.** EventSource can't set headers → mint a 60-second single-purpose signed token via `GET /api/auth/stream-ticket`, passed as `?ticket=`. Validated before subscribing; user's store scope filters published events server-side.
4. **JWT slimming.** Token carries `user_id`, `email`, `role` only. Permissions are loaded per-request (already happens in `get_current_user`). Refresh-token rotation; access token capped at 30 min regardless of remember-me (remember-me only extends the *refresh* token).
5. **AI provider abstraction.** `LLMProvider` protocol with three implementations: `OllamaProvider` (default, free, local — OpenAI-compatible `/v1/chat/completions`, so the existing httpx code nearly works as-is), `OpenAIProvider` (optional, key-gated), `RuleBasedProvider` (existing fallback). Selected via `AI_PROVIDER` env var. Conversation contexts move to Redis (TTL 1 h).

---

## 3. Database design improvements

1. **Single migration mechanism.** Keep plain SQL (team already knows it) but make it automatic and idempotent: `database/migrations/NNN_*.sql` + a tiny startup runner that records applied versions in a `schema_migrations` table. Delete the empty `alembic/` (or adopt Alembic properly — only if the team wants to learn it; do not keep both).
2. **Prices → revenue.** `items.unit_price_aed NUMERIC(10,2)` seeded with realistic UAE grocery prices; revenue computed in queries (`sales * unit_price_aed`). KPIs expose both `units` and `revenue_aed` fields.
3. **Inventory with batches/expiry** (extends migration 002): `inventory_batches(store_id, item_id, qty, received_at, expiry_date)`; views for days-of-cover and expiry risk.
4. **Fix init pipeline:** repair `init.sql:369`; date-shift CSV on load (`date + (CURRENT_DATE - 1 - max_date)`); fix the production compose CSV mount path; fill `seed_data.sql` (demo inventory, promotions, alert history) or remove its mount.
5. **Indexes:** add `(store_id, date)` composites on the fact tables (current indexes are `(store_id, item_id)` + `(date)` separately; the dominant query pattern is store-scoped date ranges once RBAC filtering lands).

---

## 4. API design improvements

- **Consistent envelope** already exists for errors — mirror it for success on list endpoints: `{data, meta:{count, page}}`, enabling pagination on sales/employees lists.
- **Pagination** on every unbounded list (sales currently relies on `limit` only).
- `/api/v1/` prefix (alias old paths during transition; delete aliases in Phase 4 — including the broken `/api/stream/sales` shim and `/api/latest` redirect).
- **OpenAPI hygiene:** every route gets `response_model`, tags, and auth markers — the `/docs` page becomes a portfolio artifact itself.

## 5. Roles & access (already designed — enforce it)

| Role | Scope | Notable permissions |
|---|---|---|
| super_admin | all regions/stores | user management, deletes, financials |
| regional_manager | one region's stores | inventory, promotions, transfers, financials |
| store_manager | one store | inventory edit, alert ack, no financials |
| analyst | per-grant | read/export only |

No customer-facing role in MVP (ops platform — see PRODUCT_STRATEGY §2). The DB model (`user_permissions` with region→store expansion, validity windows) is good; the work is purely **applying it in queries**.

---

## 6. Local development strategy

- `docker-compose.override.yml` (auto-merged by compose) for dev: backend `uvicorn --reload` with source mount; frontend `next dev` (target the builder stage or run `npm run dev` on the host against containerized backend — recommend the latter, it's simpler and faster on Windows).
- `make`/`task` equivalents as PowerShell + bash scripts: `dev up`, `dev reset-db`, `dev test`, `dev seed`.
- `.env.example` stays the contract; compose reads `.env`. Never commit `.env`.
- **Ollama**: optional `ollama` service in compose (CPU-fine for 3B models) or host install; app degrades to rule-based provider when absent — zero hard dependency.

## 7. Free/open-source replacements for paid services

| Paid today | Free replacement | Notes |
|---|---|---|
| OpenAI chat | **Ollama** (llama3.2:3b / qwen2.5:3b) | OpenAI-compatible API; existing streaming code mostly reusable |
| Deepgram STT | Browser **Web Speech API** | Free, zero backend; Chrome/Edge support is fine for demos |
| Deepgram TTS | Browser `speechSynthesis` | Same |

Everything else is already self-hosted.

## 8. Testing strategy

- **Backend unit** (no I/O): predictor math, password policy, permission aggregation, alert thresholds.
- **Backend API**: httpx `ASGITransport` against the app with a dockerized test Postgres (or transaction-rollback fixtures); critical paths = login/lockout/refresh, RBAC scoping (Yash cannot read store 2 — *the* test that proves the product), KPI correctness on seeded data.
- **Frontend**: Vitest + React Testing Library smoke tests (login form, KPI render from mocked fetch, role-gated nav).
- **E2E (thin)**: one Playwright script: boot compose → login as each persona → assert scoped dashboards. Doubles as the demo rehearsal.
- **CI**: remove `|| true` from tsc; run full pytest dir; add frontend test job; keep Docker build checks. All free on GitHub Actions.

## 9. Error handling & logging

- Keep the global JSON error envelope (good as-is).
- Replace `print()` in workers with the structured logger; add `request_id` to log records (middleware already generates it).
- KPI/route handlers stop swallowing exceptions into fake zeros — return 503 with the envelope; frontend shows a degraded-state banner (UI plan §7).
- Log to stdout only (docker captures it); no log infra for MVP.

## 10. Deployment path for pitch/demo

| Stage | Where | Cost |
|---|---|---|
| Now → demo | Local `docker compose up` (the deliverable) | $0 |
| Shareable demo | Single small VM (Oracle Cloud Always-Free or a student-credit droplet) running the production compose + Caddy or the existing nginx with Let's Encrypt | $0 |
| Pitch-stage | Same VM; add seeded "demo reset" cron | $0 |

**Stays local-only for now:** Ollama (too heavy for free VMs — cloud demo uses rule-based provider), voice features, monitoring extras. No managed cloud services anywhere — that's a *talking point*, not a limitation: "runs anywhere, no vendor bill."


