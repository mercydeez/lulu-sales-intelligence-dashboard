# Gap Analysis — Lulu Sales Intelligence Dashboard

> Every issue found during the June 2026 full-code inspection, grouped by severity.
> Effort scale: **S** = under ~2 h, **M** = half a day to 2 days, **L** = 3+ days.

---

## CRITICAL — must fix before any demo

### C1. Fresh database initialization fails (`init.sql` syntax error)
- **Problem:** `database/init.sql:369` has a bare `RAISE NOTICE '✅ Authentication system initialized…';` outside any `DO $$ … $$` block. `RAISE` is PL/pgSQL only. The postgres Docker image runs initdb scripts with `ON_ERROR_STOP=1`, so on a **brand-new volume the container init aborts**. Anyone cloning the repo today cannot boot the stack.
- **Why it matters:** "Easy to run locally" is the #1 quality bar; this breaks first-run for every new machine (it has gone unnoticed because existing dev volumes skip init).
- **Files:** `database/init.sql:369`
- **Fix:** wrap in `DO $$ BEGIN RAISE NOTICE '…'; END $$;` or delete the line. Then verify with `docker compose down -v && docker compose up`.
- **Effort:** S

### C2. Legacy SSE endpoint crashes — missing import
- **Problem:** `backend/app/main.py:214` returns `EventSourceResponse(...)` but `main.py` never imports it (it's only imported in `routes/stream.py`). Hitting `GET /api/stream/sales` raises `NameError` → 500.
- **Why it matters:** `NEXT_PUBLIC_SSE_URL` defaults to `http://localhost:8000/api/stream`, and `useSSE.ts` connects to that URL **as-is** — which matches *no* route (404), while the documented legacy route is broken. Any component relying on `useSSE` shows a permanently reconnecting stream.
- **Files:** `backend/app/main.py:210-214`, `frontend/src/hooks/useSSE.ts:6`, `.env.example:34`
- **Fix:** import `EventSourceResponse` in `main.py` (or delete the legacy shim) and point `useSSE`/`NEXT_PUBLIC_SSE_URL` at `/stream/sales`. Better: consolidate all SSE consumption into one hook (see H7).
- **Effort:** S

### C3. Most data APIs have no authentication at all
- **Problem:** Only `auth`, `admin`, `inventory`, `promotions`, `alerts`, `reports` routers use `get_current_user`. **`sales`, `kpis`, `analytics`, `history`, `stream`, `employees`, `monitoring`, `ai` are fully public.** The README explicitly claims Bearer auth on `/api/kpis`, `/api/sales`, `/api/ai/chat/stream`, etc. RBAC (region/store scoping) is therefore enforced only in the browser.
- **Why it matters:** the project's headline feature is "RBAC with row-level security." In an interview, one curl command disproves it. Employee PII-like records and the AI endpoint (which can burn OpenAI credits) are open to anyone on the network.
- **Files:** `backend/app/routes/{sales,kpis,analytics,history,stream,employees,monitoring,ai}.py`
- **Fix:** add `user: dict = Depends(get_current_user)` to every data route; filter queries by `user['permissions']['accessible_stores']`. For SSE (EventSource can't send headers), accept a short-lived signed token as a query param. Keep `/health` public.
- **Effort:** M (auth dependency: hours; real row-level filtering across queries: 1–2 days)

### C4. No version control
- **Problem:** the folder is an unzipped GitHub download (`-main` suffix), nested one level deep, with no `.git`.
- **Why it matters:** every rule we set ("small safe commits", "preserve working behavior") is impossible without git; one bad edit is unrecoverable.
- **Fix:** `git init` + initial commit before touching anything (consider moving `data/train.csv` to Git LFS or a download script — 17 MB).
- **Effort:** S

### C5. Units of measure presented as money
- **Problem:** the Kaggle dataset's `sales` column is **units sold per day**; there is no price column anywhere. The frontend formats these numbers as AED currency (`lib/formatters.ts` `formatCurrency`), so the dashboard shows "AED 1,547.00" for what is actually 1,547 units.
- **Why it matters:** the first question any retail person asks is "what's this revenue number?" — and the honest answer collapses the demo. Forecasting, promotions ROI, and KPIs all inherit the confusion.
- **Files:** `frontend/src/lib/formatters.ts`, `KPICards.tsx`, all chart components; `database/init.sql` (no price data)
- **Fix (choose one):** (a) add a `unit_price_aed` column to `items`, compute revenue = units × price in queries — keeps the AED story and is more impressive; or (b) relabel UI to units. Recommend (a).
- **Effort:** M

---

## HIGH — important for a credible MVP

### H1. Three sales tables, one actually used
- **Problem:** `sales_historical` / `sales_stream_raw` / `sales_fact_view` implement the README's architecture, but the generator, KPIs, analytics, predictor, and AI all use the legacy `sales` table. The "new" tables are dead weight holding a duplicate CSV copy.
- **Why it matters:** doubles DB size, makes the schema dishonest, and any future feature must pick a side.
- **Files:** `backend/app/models/sales.py`, `services/data_generator.py`, `routes/{kpis,sales,analytics,history}.py`, `database/init.sql`
- **Fix:** pick the documented architecture: write stream events to `sales_stream_raw` (use its `event_id` dedup), query through `sales_fact_view`, drop the legacy table. Or delete the unused pair and rename honestly. Either way, one source of truth.
- **Effort:** M–L

### H2. Token/session design flaws
- **Problem:**
  - Permissions are embedded in the JWT → stale until expiry; revoking access doesn't take effect.
  - `SessionInvalidationMiddleware` **fails open** when Redis is down.
  - `remember_me=True` issues a **7-day access token** (not just a longer refresh token).
  - Refresh tokens are never rotated or blacklisted on use.
  - `decode_token` builds `exp` with naive local-time `datetime.fromtimestamp()` while `get_current_user` compares against `datetime.utcnow()` — correct only when server TZ is UTC (containers are, but it's a landmine).
- **Files:** `backend/app/services/auth_service.py:140-170,390-410`, `app/middleware.py:306-334`, `app/routes/auth.py:24-48`
- **Fix:** keep only identity+role in the token and load permissions per request (already done in `get_current_user` — drop them from the token payload); rotate refresh tokens; cap access-token lifetime; use `datetime.fromtimestamp(ts, tz=timezone.utc)`.
- **Effort:** M

### H3. Tokens in localStorage + permissive CSP
- **Problem:** access/refresh tokens live in localStorage (readable by any XSS), while CSP allows `script-src 'unsafe-inline'` and hardcodes `connect-src http://localhost:8000` (breaks any non-localhost deploy).
- **Files:** `frontend/src/contexts/AuthContext.tsx`, `backend/app/middleware.py:188-199`
- **Fix (MVP-pragmatic):** keep localStorage but tighten CSP (drop unsafe-inline where possible, derive connect-src from CORS_ORIGINS setting). Document httpOnly-cookie auth as the production path.
- **Effort:** M

### H4. CI is lenient where it matters
- **Problem:** `npx tsc --noEmit || true` makes type errors invisible; backend CI runs only 2 of 5 test modules; there are zero frontend tests; `test_api.py` exists but isn't run in CI.
- **Files:** `.github/workflows/ci.yml:79,54`
- **Fix:** remove `|| true`; run the whole `tests/` dir (mock DB/Redis where needed); add a handful of React Testing Library smoke tests.
- **Effort:** S (CI flags) + M (frontend tests)

### H5. Schema management chaos
- **Problem:** schema comes from init.sql (first boot only) + 4 manual psql migrations + runtime employee migration; `alembic/` is configured but empty; `seed_data.sql` is 0 bytes yet mounted by the production compose as `02-seed.sql`. Also, production compose mounts `train.csv` into `/docker-entrypoint-initdb.d/` while `init.sql` COPYs from `/data/train.csv` → **production first boot fails to load data**.
- **Files:** `database/*`, `backend/alembic/`, `docker-compose.production.yml:33-35`, `app/services/employee_seeder.py`
- **Fix:** one mechanism. Simplest credible option: numbered idempotent SQL migrations all auto-applied by a tiny startup runner (or adopt Alembic for real). Fix the prod CSV mount path; fill or delete `seed_data.sql`.
- **Effort:** M

### H6. Dev experience: no hot reload despite mounted volumes
- **Problem:** `docker-compose.yml` mounts `./backend/app` and `./frontend/src`, but uvicorn runs without `--reload` and the frontend image runs the **pre-built standalone bundle** — source mounts do nothing. Every change requires `rebuild.ps1` (full no-cache rebuild, minutes).
- **Files:** `docker-compose.yml:59-60,77-78`, `backend/Dockerfile:29`, `frontend/Dockerfile`
- **Fix:** dev override file (`docker-compose.override.yml`) running `uvicorn --reload` and `next dev`; keep current Dockerfiles for prod.
- **Effort:** S–M

### H7. Six duplicate EventSource implementations
- **Problem:** `useSSE`, `useAlertStream` (×2 streams), `Navbar`, `LiveTable`, `LiveStreamChart`, `ReturnsLiveFeed`, `inventory/page`, `admin/page` each hand-roll connection + reconnect logic with hardcoded URLs.
- **Why it matters:** N reconnect bugs, N places to add SSE auth tokens (C3), wasted concurrent connections (browsers cap ~6 per origin on HTTP/1.1 — the app is at that limit already).
- **Fix:** one `useEventStream(channel)` hook (or a small client-side event bus that opens one connection per stream and fans out via context).
- **Effort:** M

### H8. Paid AI dependencies vs. free-first constraint
- **Problem:** OpenAI (chat) and Deepgram (voice) are the only external paid services. Fallback chat exists, but the "AI-powered" headline depends on a paid key.
- **Files:** `backend/app/services/ai_assistant.py`, `voice_service.py`, `frontend/src/components/ChatBot.tsx`
- **Fix:** add an **Ollama** provider (free, local, OpenAI-compatible API — small model like llama3.2/qwen2.5 3B works for this use case) with the existing rule-based engine as tier-3 fallback; make voice optional via the browser's free Web Speech API or drop it from MVP.
- **Effort:** M

### H9. Stale data story: dataset ends in 2017
- **Problem:** historical data covers 2013–2017, but KPIs compute "today / this week / this month," so historical charts and "today" views describe disjoint eras; only generator data populates recent dates (units in the tens, vs. historical daily aggregates).
- **Fix:** date-shift the CSV during load so the last historical day = yesterday (one SQL expression in init), making trends, forecasts and KPIs continuous.
- **Effort:** S–M

---

## MEDIUM — polish and robustness

| # | Problem | Files | Fix | Effort |
|---|---|---|---|---|
| M1 | KPI endpoint swallows all exceptions and returns zeros — outages look like "no sales" | `routes/kpis.py:125-141` | return 503 / surface degraded state | S |
| M2 | Frontend API cache not user-aware; logging out/in can show previous user's cached data | `lib/api.ts` | include user id in cache key; clear on logout | S |
| M3 | Duplicate auth-fetch logic (AuthContext method + module function + api.ts headers) with diverging behavior | `contexts/AuthContext.tsx`, `lib/api.ts` | single API client module | M |
| M4 | Rate limiter trusts `X-Forwarded-For` blindly (spoofable when not behind nginx) | `middleware.py:69-77` | trust XFF only when `ENVIRONMENT=production` behind known proxy | S |
| M5 | Mega-files: pages up to 46 KB, routes up to 34 KB, `ai_assistant.py` 39 KB | `frontend/src/app/*/page.tsx`, `routes/employees.py`, `routes/promotions.py` | extract components/services during the UI redesign | L |
| M6 | `data_generator` uses `print()` and emoji instead of the configured logger; hardcoded id ranges 1–10/1–50 | `services/data_generator.py` | use `logger`; query actual store/item ids | S |
| M7 | `get_db` commits on *every* request including pure reads | `services/database.py:60-70` | commit only in write paths | S |
| M8 | Conversation contexts in process memory — lost on restart, not shared across workers | `services/ai_assistant.py:51-70` | store in Redis with TTL | M |
| M9 | CORS `allow_methods/headers=["*"]` with `allow_credentials=True` | `main.py:174-181` | enumerate methods/headers | S |
| M10 | 17 MB `train.csv` in repo | `data/train.csv` | download script or Git LFS once git exists | S |
| M11 | README overclaims (auth coverage, alembic, "sub-second latency", test coverage) | `README.md` | rewrite once gaps are fixed — honesty is resume-critical | S |
| M12 | `predictions` table + `/api/sales/predictions` exist but forecast quality is a 30-day moving average labeled "confidence interval" | `services/predictor.py` | upgrade to seasonal-naive or statsmodels/Prophet-style model (free) and document the method honestly | M |
| M13 | Demo password `Lulu@2026!` hardcoded in `rebuild.ps1` and hashes shared across all 3 users | `rebuild.ps1:29`, `init.sql:341-345` | fine for demo, but generate per-user passwords in seed and document | S |

---

## LOW — nice to have

| # | Problem | Fix | Effort |
|---|---|---|---|
| L1 | No favicon/meta/OG tags; default Next.js metadata | brand pass in `app/layout.tsx` | S |
| L2 | Dark-mode-only UI; no theme toggle | design-system phase | M |
| L3 | No i18n (Arabic/RTL would be a real differentiator for a UAE retail product) | `next-intl`, RTL audit | L |
| L4 | Accessibility: no skip links, weak focus states, icon-only buttons unlabeled, charts without text alternatives | UI redesign phase | M |
| L5 | `windows` event handler leaks possible in some chart components (reconnect timers cleared inconsistently) | unify in shared hook (H7) | S |
| L6 | `.gitignore` exists but no `.dockerignore` for backend (frontend has one) — build context includes tests/venvs | add backend `.dockerignore` | S |
| L7 | Emoji-heavy logs and UI labels (`🔄 RETURN`) read "student project" | tone pass | S |
| L8 | No request logging/metrics persistence (monitoring page reads live only) | optional: lightweight Prometheus + Grafana later | L |

---

## What is genuinely GOOD (keep and showcase)

- Real async SQLAlchemy 2.0 + asyncpg usage, connection-pool tuning, retry-on-boot.
- Redis pub/sub → SSE pipeline is a legitimately interesting architecture to explain in interviews.
- Middleware stack (rate limit, CSRF, security headers, body limits, request IDs) is far beyond typical student work.
- `validate_security()` fail-fast on insecure prod config + tests for it — a great story.
- Account lockout, bcrypt, audit log, permission aggregation with region→store expansion.
- Synthetic data generator with market sentiment, seasonality and returns — makes demos feel alive.
- Non-root Docker images, healthchecks, multi-stage frontend build, production compose with resource limits.
- Consistent global JSON error envelope with field-level validation details.
