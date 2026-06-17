# Implementation Roadmap

> Rule of engagement: small, verifiable steps; never break `docker compose up`; each phase ends demo-able.
> Effort assumes 2–3 students part-time. Phases 0–1 ≈ one weekend. References: GAP_ANALYSIS items (C/H/M/L), ARCHITECTURE_PLAN (§), UI_UX_REDESIGN_PLAN.

---

## Phase 0 — Project recovery & setup (½ day) 🔴 do first

| # | Task | Files | Notes |
|---|---|---|---|
| 0.1 | `git init`, `.gitignore` review, initial commit; decide on train.csv handling (LFS or download script) | repo root | GAP C4 — nothing else starts before this |
| 0.2 | Fix `init.sql` RAISE NOTICE syntax error | `database/init.sql:369` | GAP C1 |
| 0.3 | Fix `EventSourceResponse` import; point `useSSE`/`NEXT_PUBLIC_SSE_URL` at `/stream/sales` | `backend/app/main.py`, `frontend/src/hooks/useSSE.ts`, `.env.example`, composes | GAP C2 |
| 0.4 | Full clean-room boot test: `docker compose down -v && docker compose up` on a wiped volume; apply the 4 migrations; log in as all 3 users | — | the recovery milestone |
| 0.5 | Create `docker-compose.override.yml` dev mode (uvicorn --reload; host `npm run dev`) | new file | GAP H6 |
| 0.6 | CI honesty: drop `\|\| true` on tsc; run full `tests/` dir; fix whatever falls out | `.github/workflows/ci.yml` | GAP H4 |

**Acceptance:** fresh clone → running app + passing CI in <10 min, with git history started.
**Test:** clean-volume boot, login×3, live feed visibly updating, `pytest` green locally.

---

## Phase 1 — Critical fixes (3–5 days) 🔴

Priority order within phase: 1.1 → 1.2 → 1.3 → 1.4.

| # | Task | Files | Notes |
|---|---|---|---|
| 1.1 | **Auth on all data routers** via router-level `Depends(get_current_user)`; SSE stream-ticket endpoint + query-param validation | `routes/{sales,kpis,analytics,history,stream,employees,monitoring,ai}.py`, `routes/auth.py`, frontend SSE consumers | GAP C3, ARCH §2.2–2.3 |
| 1.2 | **Server-side store/region scoping**: `ScopedUser` dep; `WHERE store_id = ANY(:ids)` in sales/kpis/analytics/inventory queries; filter SSE events per user scope | same + `services/` | the RBAC proof; add the "Yash can't see store 2" pytest |
| 1.3 | **Revenue model**: `unit_price_aed` on items (migration 005), seed realistic prices, expose `units` + `revenue_aed` separately in KPIs/analytics; relabel frontend (currency only where it's truly AED) | `database/migrations/005_*.sql`, `routes/kpis.py`, `analytics.py`, `KPICards.tsx`, `formatters.ts` | GAP C5 |
| 1.4 | **Date-shift historical data** on load so history ends yesterday | `database/init.sql` (COPY post-process) | GAP H9 |
| 1.5 | Token hygiene: permissions out of JWT, refresh rotation, remember-me fix, UTC-aware exp | `services/auth_service.py`, `routes/auth.py` | GAP H2 |
| 1.6 | Migration runner (`schema_migrations` table, auto-apply on startup); fold the 4 manual migrations in; fix prod compose CSV mount; fill or remove `seed_data.sql`; delete empty `alembic/` | `backend/app/` startup, `database/`, `docker-compose.production.yml` | GAP H5 |

**Acceptance:** unauthenticated curl to any `/api/*` data route → 401; Yash's curl for store 2 → 403/empty; KPIs show coherent revenue+units for current dates; clean boot needs zero manual psql.
**Test:** new pytest module `test_rbac.py` (the centerpiece), existing suites green, manual 3-persona walkthrough.

---

## Phase 2 — MVP completion (1–2 weeks) 🟠

| # | Task | Files | Notes |
|---|---|---|---|
| 2.1 | Unify sales storage: generator → `sales_stream_raw`; readers → `sales_fact_view`; drop legacy `sales` (last step) | `services/data_generator.py`, `models/sales.py`, all readers | GAP H1; do after 1.x since those touch the same queries |
| 2.2 | Inventory batches + expiry: migration, expiry-risk queries, reorder/expiry alerts via existing alert pipeline | `database/migrations/006_*.sql`, `services/data_sync.py`, `routes/inventory.py` | PRODUCT §3C.1 |
| 2.3 | Alerts → tasks: acknowledge/assign/resolve states + API | `routes/alerts.py`, migration | PRODUCT §3B.6 |
| 2.4 | Forecast upgrade: seasonal model (weekly seasonality + trend on 5y history), MAPE backtest endpoint | `services/predictor.py` | GAP M12; keep it explainable |
| 2.5 | AI provider abstraction: Ollama default, OpenAI optional, rule-based fallback; contexts → Redis | `services/ai_assistant.py` (split into `services/llm/`), compose (optional ollama service) | GAP H8, M8 |
| 2.6 | One `useEventStream` hook replacing 6+ EventSource implementations (carries stream tickets from 1.1) | `frontend/src/hooks/`, Navbar, LiveTable, charts, pages | GAP H7 |
| 2.7 | Single frontend API client (auth, refresh, user-aware cache, error envelope parsing) | `lib/api.ts`, `contexts/AuthContext.tsx` | GAP M2, M3 |
| 2.8 | Backend test expansion: RBAC, KPI correctness on seeded data, predictor math, alert thresholds; wire into CI | `backend/tests/` | ARCH §8 |
| 2.9 | Seed pack: demo inventory batches (some expiring soon), running promotions, alert history, so every screen is populated on first boot | `database/seed_data.sql` | "no empty demo screens" |

**Acceptance:** every nav page shows real populated content on a fresh boot; forecast page shows forecast-vs-actual with MAPE; AI chat answers data questions with zero paid keys; single SSE hook everywhere.
**Test:** CI green incl. new suites; clean-room boot script; manual demo run.

---

## Phase 3 — UI/UX redesign (1.5–2 weeks) 🟡

Follow UI_UX_REDESIGN_PLAN §13 order:

| # | Task | Files |
|---|---|---|
| 3.1 | Design tokens, fonts, light/dark CSS variables, Tailwind config | `tailwind.config.js`, `globals.css`, `app/layout.tsx` |
| 3.2 | `ui/` primitives (Button, Card, StatCard, DataTable, Badge, Toast, Modal, EmptyState, Skeleton, ChartFrame, LiveIndicator, PageHeader, Tabs, Select) + `/dev/components` gallery | `src/components/ui/` |
| 3.3 | App shell: sidebar nav, slim top bar with scope switcher, role-shaped home routes | `ClientLayout.tsx`, `Navbar.tsx` → `shell/` |
| 3.4 | Rebuild screens in order: Live Operations home → Inventory/Expiry → Alerts/Tasks → Analytics/Forecast → Promotions → Employees → Admin → Reports/Monitoring (each page: decompose mega-component into ui/ + feature components) | `src/app/*/page.tsx` |
| 3.5 | States pass: skeletons, empty states, error panels, SSE-degraded banner | all pages |
| 3.6 | Microinteractions: number tickers, delta flashes, live-row animations, reduced-motion | `ui/` |
| 3.7 | Mobile pass (manager-on-the-floor flows) → accessibility pass (AA contrast, keyboard, aria-live) | all |
| 3.8 | (Stretch, high payoff) EN/AR with RTL on nav/home/inventory/alerts | `next-intl`, dictionaries |

**Acceptance:** screenshot-worthy on every page; no blank/zero panels anywhere; keyboard-navigable; Lighthouse a11y ≥ 90; works at 375px width for manager flows.
**Test:** `/dev/components` visual review, Playwright persona walkthrough, axe/Lighthouse runs.

---

## Phase 4 — Production readiness (3–5 days) 🟡

| # | Task | Notes |
|---|---|---|
| 4.1 | CSP tightening (config-driven connect-src, minimize unsafe-inline), CORS method/header enumeration, XFF trust flag | GAP H3, M4, M9 |
| 4.2 | Logging pass: request_id in records, workers on logger, KPI fake-zeros → 503 + frontend degraded panels | GAP M1, M6 |
| 4.3 | Read-path commit removal, `(store_id,date)` indexes, pagination on unbounded lists | GAP M7, ARCH §3.5/§4 |
| 4.4 | Delete legacy aliases (`/api/latest`, `/api/stream/sales`), dead code, `routes/` files' inline schemas → `schemas/` | ARCH §2 cleanup |
| 4.5 | Backend `.dockerignore`; image size pass; compose healthcheck for frontend dev | GAP L6 |
| 4.6 | Playwright E2E (3-persona walkthrough) in CI nightly | ARCH §8 |
| 4.7 | Security re-review: run through GAP list, verify each closed; document accepted risks (localStorage tokens) in SECURITY.md | |

**Acceptance:** GAP_ANALYSIS Critical+High all closed or explicitly accepted in SECURITY.md; CI includes E2E; `docker compose -f docker-compose.production.yml up` boots cleanly with required env vars.

---

## Phase 5 — Resume / demo / pitch polish (2–3 days) 🟢

| # | Task | Notes |
|---|---|---|
| 5.1 | Rewrite README truthfully: new architecture diagram, honest feature list, 5-minute quickstart, screenshots/GIF of live feed | GAP M11 |
| 5.2 | Demo script doc: the 3-persona walkthrough with talking points + the curl that proves server-side RBAC | the interview weapon |
| 5.3 | Disclaimer & naming: product name decision, "independent student project, synthetic data" badge in footer + README | PRODUCT §5 |
| 5.4 | Architecture decision log (`docs/DECISIONS.md`): why SSE over WebSockets, why Ollama, why plain-SQL migrations — interviewers love this | |
| 5.5 | Optional public demo: Oracle free-tier VM + production compose + Caddy TLS; seeded reset cron | ARCH §10 |
| 5.6 | Pitch one-pager from PRODUCT_STRATEGY (problem, demo, roadmap-to-enterprise) | |

**Acceptance:** a stranger can clone→run→understand in 10 minutes; you can demo in 5; every claim in the README is verifiable in the code.

---

## Dependency notes

- 0.x blocks everything. 1.1→1.2 blocks 2.6 (tickets) and the RBAC tests. 2.1 should land before heavy Phase 3 work touches data fetching. 3.x can start tokens/primitives (3.1–3.2) in parallel with late Phase 2.
- Anything labeled "stretch" (3.8 RTL, 5.5 public demo) is cuttable without harming the core story.
