# Implementation Tracker

Living execution log for turning the Lulu Sales Intelligence Dashboard into a resume-grade MVP.
We work **one phase at a time**, stop at each phase boundary for your review, then commit.

> Detailed rationale lives in `docs/` (GAP_ANALYSIS, IMPLEMENTATION_ROADMAP, etc.).
> This file is the *current* state of execution — the source of truth for "what's next".

---

## What this project is (purpose)

A real-time retail sales-intelligence dashboard for a UAE supermarket chain ("Lulu"), built to
demonstrate full-stack + data engineering for a resume/portfolio.

- **Data pipeline:** a `DataGenerator` writes synthetic sales to Postgres every ~5–15s and publishes
  to Redis (`sales:stream`, `alerts:stream`, `inventory:stream`); SSE endpoints relay pub/sub to the
  browser via `EventSource`.
- **Security:** JWT auth + RBAC scoped by region→store, rate limiting, CSRF, security-header middleware.
- **Features:** live KPIs, sales analytics, seasonal forecasting, inventory/expiry, alerts→tasks,
  promotions, employees, and a free/local-first AI assistant (Ollama default, OpenAI optional,
  rule-based fallback).
- **Constraints:** free/local-first — no paid AI APIs without approval. Synthetic data. Student → MVP.

Data caveat baked into the codebase: the Kaggle `sales` values are **units**, not currency; revenue is
derived via `unit_price_aed` (migration 005). Historical data is 2013–2017, date-shifted on load.

---

## Status legend
✅ done & committed  ·  🟡 in progress / uncommitted  ·  ❌ not started  ·  ⏭️ deferred

---

## Where we are now (snapshot)

**Phase 0 — recovery** ✅  git init, `init.sql` crash fixed, SSE import fixed, dev override, CI honesty.

**Phase 1 — critical fixes** ✅  auth on all data routers, server-side store/region scoping, revenue
model (mig 005), date-shift, token hygiene, migration runner.

**Phase 2 — MVP completion** ✅ all 9 items (sales unification, inventory/expiry, alerts→tasks,
seasonal forecast, AI provider chain, `useEventStream`, API client foundation, CI, seed pack)
committed on `phase-2-mvp-completion`. Detail in changelog below.

---

**Phase 3 — UI/UX redesign** 🟡 *(active phase — following `docs/IMPLEMENTATION_ROADMAP.md` §3 order)*

| # | Task | Status |
|---|---|---|
| 3.1 | Design tokens, fonts, light/dark CSS vars, Tailwind config | ✅ Sunset Pop palette (coral/teal/violet/amber) + Inter via `next/font`; legacy dark-slate overrides removed |
| 3.2 | `ui/` primitives + `/dev/components` gallery | ✅ Button, Card, StatCard, Badge, Toast, Modal, EmptyState, Skeleton, ChartFrame, LiveIndicator, PageHeader, Tabs, Select, Input, Table (757eb6d) |
| 3.3 | App shell: sidebar nav, slim top bar, role-shaped home | ✅ sidebar replacing top Navbar (775d4c7) |
| 3.4 | Rebuild screens: Home → Inventory → Alerts → Analytics/Forecast → **Promotions** → Employees → Admin → Reports/Monitoring | 🟡 4/8 done — Live Operations home (6404c0b), Inventory/Procurement (9debab7), Alerts/Tasks (819b9c4), Analytics/Forecast (HEAD of phase-2-mvp-completion — real `/api/analytics/*` data, Sunset palette charts, Overview/Forecast tabs). **Next: Promotions.** Then Employees, Admin, Reports/Monitoring |
| 3.5 | States pass: skeletons, empty states, error panels, SSE-degraded banner | ❌ |
| 3.6 | Microinteractions: number tickers, delta flashes, live-row animations, reduced-motion | ❌ |
| 3.7 | Mobile pass (manager-on-the-floor) → accessibility pass (AA contrast, keyboard, aria-live) | ❌ |
| 3.8 | (Stretch) EN/AR with RTL on nav/home/inventory/alerts | ⏭️ deferred — cuttable without harming core story |

---

**Phase 4 — production readiness** ❌

| # | Task | Status |
|---|---|---|
| 4.1 | Tighten CSP + enumerate CORS origins | ❌ |
| 4.2 | Structured logging (request-id threaded through) | ❌ |
| 4.3 | DB indexes on hot query columns | ❌ |
| 4.4 | Pagination on all unbounded list endpoints | ❌ |
| 4.5 | Fix `except: pass` in `data_sync` → savepoints | ❌ pre-existing; flagged in open findings |
| 4.6 | Dead-code cleanup (`alembic/`, unused routes) | ❌ |

---

**Phase 5 — resume/demo polish** ❌

| # | Task | Status |
|---|---|---|
| 5.1 | Honest README rewrite (what works, what's synthetic) | ❌ |
| 5.2 | Demo script (walk-through order for portfolio review) | ❌ |
| 5.3 | Architecture decisions log (ADR format) | ❌ |
| 5.4 | Pitch one-pager (tech choices + tradeoffs) | ❌ |

---

## Criticality ranking (what to do next)

1. 🔴 **3.4 remaining screens** — Promotions next, then Employees, Admin, Reports/Monitoring.
2. 🟠 **3.5–3.7** — states/empty/error pass, microinteractions, mobile + a11y pass once all screens are rebuilt.
3. 🟡 **Phase 4** — production hardening (can run in parallel with late Phase 3).
4. 🟢 **Phase 5** — polish/demo (last, once everything looks and works right).

---

## Decision log

- **3.4 Analytics/Forecast rebuild:** replaced the mock-data page (random `generateMockData`,
  fake transactions/conversion/hourly) with a thin composer over a new `components/analytics/`
  folder fed by the real `/api/analytics/*` endpoints (trend, stores, categories, top-items) plus
  `/api/kpis`. Two tabs: **Overview** (KPI StatCards, sales trend + 7-day forecast, category mix,
  store revenue, top items, store-performance table) and **Forecast** (interactive store/item/holdout
  backtest with MAPE vs seasonal-naive baseline). Charts use a new Sunset Pop `chartTheme` instead of
  the legacy cyan/slate hex palette. Added typed client helpers (`fetchStoreDistribution`,
  `fetchCategoryBreakdown`, `fetchTopItems`) routed through `lib/apiClient` per decision 2.7.
  **Dropped the old `exportAnalyticsPDF`** path (it hardcoded fabricated transactions/conversion);
  PDF export now uses the generic `generatePDF` over real revenue/category data only — honest figures.
  The date-range selector intentionally drives only the trend window (the other endpoints are all-time
  aggregates with no range param). Store-comparison panel is hidden for store managers. Existing shared
  charts left untouched (the home screen still depends on them). Verified: `tsc --noEmit` clean + `npm run build` passes.
- **3.4 Alerts/Tasks rebuild:** switched the page off client-mocked alerts onto the real persisted
  `alerts` table workflow the backend already exposed but the old page never called — acknowledge,
  resolve-with-notes, and a "My Tasks" tab (`/api/alerts/my-tasks`). Deliberately dropped the
  assign-to-user picker: the only assignee-listing endpoint (`/api/admin/users`) is super-admin-only,
  so a proper picker needs a new backend endpoint — out of scope for a UI decomposition pass.
- **2.5 AI providers:** Ollama is the zero-cost default; OpenAI is opt-in via env var. Both providers raise `LLMError` on any upstream failure and the caller falls through to the rule-based responder, which always answers with live DB data. No paid key required for the demo.
- **2.7 API client scope:** built the foundation now (`lib/apiClient.ts` — auth,
  401→refresh single-flight→retry, user-aware cache fixing M2, error-envelope
  parsing fixing M3) and routed `lib/api.ts` + `AuthContext` through it. The 22
  scattered raw `fetch()` call sites migrate opportunistically during Phase 3 when
  those screens are rewritten, to avoid touching them twice.
- **2.1 sales storage:** adopted the 3-tier design (over collapsing to one table).
  `sales_stream_raw` = live events, `sales_historical` = CSV, `sales_fact_view` = the
  union every reader queries. View is shaped as a drop-in for the old `sales` columns;
  streaming ids offset by 1e9 to keep the ORM identity map correct. Legacy `sales`
  table dropped (migration 007). Verified via clean-volume boot: migrations 001–007
  apply, RBAC scoping holds, KPIs/analytics/sales serve real data.

---

## Open findings

- `data_sync.generate_alerts_from_sales` swallows query errors with `except: pass`,
  which poisons the asyncpg transaction and masks the real failure. Needs savepoints
  per sub-query. Pre-existing design issue — tracked as 4.5.

---

## Phase changelog

| Date | Commit | What landed |
|---|---|---|
| 2026-06-18 | _(HEAD)_ | feat(3.4): rebuild Analytics/Forecast screen — real `/api/analytics/*` data, Sunset-palette charts, Overview/Forecast tabs, interactive MAPE backtest |
| 2026-06-18 | 819b9c4 | feat(3.4): rebuild Alerts/Tasks screen — real ack/resolve+notes/my-tasks workflow |
| 2026-06-18 | 9debab7 | feat(3.4): rebuild Inventory/Procurement screen |
| 2026-06-17 | 6404c0b | feat(3.4): rebuild Live Operations home screen |
| 2026-06-17 | 775d4c7 | feat(3.3): sidebar app shell replacing top Navbar |
| 2026-06-17 | 757eb6d | feat(3.2): ui/ primitives gallery + finish Navbar restyle |
| 2026-06-17 | 4991f87 | docs: expand implementation tracker — Phase 3 task table, fix stale 2.x statuses |
| 2026-06-17 | c4c4c91 | docs: tracker updated, Phase 2 marked complete |
| 2026-06-17 | cefbef1 | feat(2.5): LLM provider chain wired into `ai_assistant.py` |
| 2026-06-17 | eed2632 | feat(2.7): single frontend API client foundation |
| 2026-06-17 | c17fc9b | docs: 2.8 CI + 2.9 populate screens verified complete |
| 2026-06-17 | f975d17 | fix: inventory/items empty for scoped requests |
| 2026-06-17 | d643b12 | fix: employee seeder ORM/schema mismatch on fresh boot |
| 2026-06-17 | f23be18 | fix: Phase 2.1 boot-test follow-up fixes |
| 2026-06-17 | 2ca2414 | feat(2.1): 3-tier sales unification + migration 007 |
| 2026-06-17 | e3af0e8 | chore: stop tracking tsconfig.tsbuildinfo |
| 2026-06-17 | 92f71e9 | docs: initial implementation tracker |
| earlier | b9502fa | chore: Phase 3 design-system groundwork (WIP) |
| earlier | c69bb47 | feat(2.2/2.3): alerts-tasks workflow + inventory batches |
| earlier | b14ad81 | feat(2.4): seasonal forecast + MAPE backtest |
| earlier | f429529 | feat(1.5): token hygiene — refresh rotation, remember_me, jti |
