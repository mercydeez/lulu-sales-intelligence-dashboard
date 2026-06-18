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

**Phase 3 — UI/UX redesign** ✅ *(complete — all of 3.1–3.8 done, following `docs/IMPLEMENTATION_ROADMAP.md` §3 order)*

| # | Task | Status |
|---|---|---|
| 3.1 | Design tokens, fonts, light/dark CSS vars, Tailwind config | ✅ Sunset Pop palette (coral/teal/violet/amber) + Inter via `next/font`; legacy dark-slate overrides removed |
| 3.2 | `ui/` primitives + `/dev/components` gallery | ✅ Button, Card, StatCard, Badge, Toast, Modal, EmptyState, Skeleton, ChartFrame, LiveIndicator, PageHeader, Tabs, Select, Input, Table (757eb6d) |
| 3.3 | App shell: sidebar nav, slim top bar, role-shaped home | ✅ sidebar replacing top Navbar (775d4c7) |
| 3.4 | Rebuild screens: Home → Inventory → Alerts → Analytics/Forecast → Promotions → Employees → Admin → Reports/Monitoring | ✅ 8/8 — home (6404c0b), Inventory (9debab7), Alerts (819b9c4), Analytics/Forecast (bee4aae), Promotions (583f0f4), Employees (f5f007c), Admin (73ad59c), Reports + Monitoring (HEAD). All screens on the Sunset design system with real data. |
| 3.5 | States pass: skeletons, empty states, error panels, SSE-degraded banner | ✅ skeletons + empty states already shipped with the rebuilds; added `ui/ErrorState` (wired into KPICards + Reports) and `ui/ConnectionBanner` SSE-degraded banner (wired into Inventory, driven by stream error) |
| 3.6 | Microinteractions: number tickers, delta flashes, live-row animations, reduced-motion | ✅ shared reduced-motion-aware `ui/AnimatedNumber` (count-up) replacing the KPICards-local dup; `flashOnChange` delta flash (`.flash-up/.flash-down`) on live values (home Live, Admin sales/items); `useReducedMotion` hook + global `prefers-reduced-motion` CSS guard. Live-row animation uses the existing fade/slide keyframes |
| 3.7 | Mobile pass (manager-on-the-floor) → accessibility pass (AA contrast, keyboard, aria-live) | ✅ mobile nav drawer in shell; `:focus-visible` ring + `aria-live`/`role=status` on live regions. **AA contrast audit done** (measured ratios via script): darkened `ink-muted` #8b8699→#6b6680 (3.52→5.47), deepened the three sunset gradients + primary button to 700-level stops so white text clears AA (≥5:1 every stop, was 1.67–2.8), fixed coral Tabs/Badge text to coral-700 |
| 3.8 | EN/AR with RTL on nav/home/inventory/alerts | ✅ `LanguageProvider` (EN/AR dicts, persisted, sets `<html dir/lang>`); topbar language toggle; translated nav + home/inventory/alerts headings & tabs; shell converted to logical utilities (`ps`/`start`/`border-e`) so the sidebar flips to the right in RTL. Arabic uses system font fallback (Inter is latin-only) |

---

**Phase 4 — production readiness** ❌

| # | Task | Status |
|---|---|---|
| 4.1 | Tighten CSP + enumerate CORS origins | ❌ |
| 4.2 | Structured logging (request-id threaded through) | ❌ |
| 4.3 | DB indexes on hot query columns | ❌ |
| 4.4 | Pagination on all unbounded list endpoints | ❌ |
| 4.5 | Fix `except: pass` in `data_sync` → savepoints | ✅ both silent `except: pass` blocks in `generate_alerts_from_sales` now wrap their sub-query in `session.begin_nested()` (SAVEPOINT) and log a warning — a failed optional sub-query rolls back to its savepoint instead of aborting the shared asyncpg transaction and poisoning the queries that follow |
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

1. ✅ **Phase 3 — COMPLETE** (3.1–3.8: design system, all 8 screens, states, microinteractions, a11y/AA contrast, EN/AR + RTL).
2. 🟡 **Phase 4** — production hardening (CSP/CORS, structured logging, DB indexes, pagination, `except: pass` fix, dead-code cleanup).
3. 🟢 **Phase 5** — polish/demo (honest README, demo script, ADRs, pitch one-pager).

---

## Decision log

- **3.7 AA contrast audit + 3.8 EN/AR RTL (completes Phase 3):**
  - *Contrast (3.7):* measured WCAG ratios for the palette with a script. Fixes: `ink-muted`
    #8b8699→#6b6680 (3.52→**5.47** on white — the pervasive secondary-text colour now passes AA
    normal); the three `sunset-*` gradients + `btn-sunset` deepened from 500-level to **700-level stops**
    (coral-700/amber-700/violet-700/teal-700) so white text clears AA at every point (worst was
    white-on-amber **1.67**, now ≥**5.0**); coral Tabs-active and the coral Badge moved to coral-700 on a
    lighter tint. Gradient `StatCard` labels bumped to opaque `text-white` semibold. Trade-off: gradients
    read a touch deeper/richer than the original bright "pop", accepted for genuine AA.
  - *EN/AR + RTL (3.8):* added `contexts/LanguageContext` (EN/AR dictionaries scoped to nav +
    home/inventory/alerts, persisted to localStorage, drives `<html dir/lang>`), a topbar globe toggle,
    and converted the shell's directional classes to **logical utilities** (`lg:start-0`, `lg:ps-64`,
    `border-e`, `ms-`/`end-`) so the sidebar + content mirror correctly in `dir=rtl`. Flexbox rows mirror
    automatically under RTL. Scoped to the four areas the roadmap named; data/values and deeper screens
    stay English. Arabic falls back to a system font (Inter is latin-only) — a bundled Arabic face is a
    future nicety, not required for the demo.
- **3.5–3.7 states / microinteractions / a11y pass:** built cross-cutting primitives rather than
  touching every screen ad-hoc. New: `ui/ErrorState` (retry panel), `ui/ConnectionBanner`
  (SSE-degraded, `aria-live`), `ui/AnimatedNumber` (count-up, **respects `prefers-reduced-motion`**,
  optional `flashOnChange` delta flash), `hooks/useReducedMotion`. globals.css gained a global
  `prefers-reduced-motion` guard (neutralizes all animation/transition), `.flash-up/.flash-down`
  keyframes, and a `:focus-visible` keyboard ring. Wired: KPICards now uses the shared AnimatedNumber
  (deleting its local dup) with a delta flash on the live streaming count + ErrorState retry; Admin
  dashboard cards animate/flash; Inventory shows the ConnectionBanner when its alert stream errors;
  LiveIndicator + ConnectionBanner expose `role=status`/`aria-live`. **Deliberately deferred:** a formal
  AA-contrast audit (3.7) — the palette is light-on-ink by design but I haven't measured ratios, so I
  left it open rather than claim AA. Skeletons/empty states were already delivered during the 3.4 rebuilds.
- **3.4 Reports + Monitoring rebuild (completes 3.4):**
  - *Monitoring* — restyled the real health/stats/metrics console onto the Sunset system via a new
    `components/monitoring/` folder (`HealthChecksGrid`, `SystemStatsCards`, `MetricsPanel`, `StatusPill`),
    kept the 10s auto-refresh (now a toggle) and overall-status pill in the header. Already used `authFetch` +
    real `/api/monitoring/*` data; this was a styling/decomposition pass.
  - *Reports* — **caught a data-honesty bug**: `/api/reports/sales` aggregates `SUM(sales)` with no
    `unit_price_aed`, so its figures are **units, not AED** — but the old page and `exportReportsPDF`
    labelled them "AED". Rebuilt over `components/reports/` labelling everything as **units** (Units Sold,
    Avg Basket in units, Units by Category/Store/Item). Dropped all mock fallbacks (one rich endpoint feeds
    everything) and bypassed `exportReportsPDF` in favour of a direct `generatePDF` with honest unit labels
    and a "no price column" footer. Reused the Analytics `chartTheme`/`format`. (Contrast: the Analytics
    screen shows AED because that endpoint multiplies by `unit_price_aed`.)
- **3.4 Admin rebuild:** the admin backend is **GET-only** (`/users`, `/stores`, `/dashboard`,
  `/activity` — all super-admin gated; no create/update/delete despite `UserCreate`/`UserUpdate` models
  existing). The old page shipped non-functional Add-User / Edit / Save-Settings UI plus a big mock-user
  fallback and an employees tab duplicating the Employees screen. Rebuilt as an **honest read-only
  console** over `components/admin/`: super-admin access gate (EmptyState for others),
  `AdminDashboardCards` + `AdminTrendChart` (real `/dashboard`), `UsersTable` (search), `StoresTable`,
  `ActivityFeed` (real `/activity`). Four tabs (Overview/Users/Stores/Activity). **Dropped** the fake
  mutation UI and Settings tab — user/store management needs real POST/PUT endpoints first (tracked as a
  backend gap, same rationale as the Alerts assignee-picker decision). Verified: tsc clean + build passes.
- **3.4 Employees/Performance rebuild:** the old page already used real `/api/employees/*` data
  but via raw unauthenticated `fetch(API_URL)` with inline-defined sub-components and dark gray/blue
  styling. Rebuilt as a thin composer over a new `components/employees/` folder: `EmployeeSummaryCards`,
  Sunset `EmployeeBioCard` (compact + full), `RolePerformanceTable`, `RoleDistribution`,
  `EmployeeFilters` (grid/list toggle), `EmployeeListView`, a restyled `EmployeePerformanceChart`
  (line/bar/radar on the new palette + `ChartFrame`), and `Modal`-primitive `EmployeeFormModal` /
  `EmployeeDetailModal`. All fetches moved onto **`authFetch`** (per decision 2.7) since the routes now
  depend on `get_current_user`. Three overview/employees/analytics tabs preserved; clicking a role row
  jumps to the filtered employee list. Add-Employee gated behind `can_manage_employees`/`can_manage_users`.
  Form posts the same payload contract as before. **Removed the three now-orphaned top-level components**
  (`EmployeeBioCard`/`EmployeePerformanceChart`/`NewEmployeeModal`) — superseded and unreferenced; they
  shared names with the new ones. Verified: tsc clean + build passes.
- **3.4 Promotions/Pricing rebuild:** replaced the mock-heavy page (large `generateMock*`
  arrays + an inline dark-gray form) with a thin composer over a new `components/promotions/`
  folder fed by the real endpoints (`/summary`, `/active`, `/list`, `/categories`). Sunset gradient
  carousel for active promos, a `Tabs`+search promotions list, and a category-performance panel that
  now uses the endpoint's **real** shape (revenue + growth_rate + avg_discount) rather than the old
  page's wrong `active_promos/total_redemptions` assumption. Create flow moved off the inline form and
  the unused dark `NewPromotionModal` onto a `Modal`-primitive form with `Input`/`Select`/`Button`,
  with the store picker **scoped to the user's `accessible_stores`** (backend enforces too). Dropped
  the fabricated mock fallbacks in favour of honest empty states (the backend already merges
  DB + sales-derived promotions, so it rarely returns empty). Did **not** add `useToast` — the
  `ToastProvider` isn't mounted globally, so create feedback stays inline (error banner + refresh on
  success). New-Promotion button only renders with `can_manage_promotions`. Verified: tsc clean + build passes.
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

- ~~`data_sync.generate_alerts_from_sales` swallows query errors with `except: pass`,
  which poisons the asyncpg transaction and masks the real failure.~~ **Resolved (4.5):**
  each optional sub-query now runs inside a `begin_nested()` SAVEPOINT and logs on failure.

---

## Phase changelog

| Date | Commit | What landed |
|---|---|---|
| 2026-06-18 | _(HEAD)_ | feat(4.5): `data_sync.generate_alerts_from_sales` optional sub-queries wrapped in `begin_nested()` savepoints + logged — no more silent `except: pass` that poisoned the shared asyncpg transaction |
| 2026-06-18 | 32ccd89 | fix(seeder): bind `EmployeePerformance.period_type` + `EmployeeTransaction.transaction_type` to their PG enums (`create_type=False`, `values_callable`) — the d643b12 enum-cast fix had missed these two columns, so fresh-boot performance + transaction seeding crashed with `DatatypeMismatchError`. Verified clean re-seed: 30 employees / 180 performance / 4493 transactions |
| 2026-06-18 | ad29515 | feat(3.7/3.8): AA contrast audit (deepened gradients + ink-muted) and EN/AR with RTL on nav/home/inventory/alerts — completes Phase 3 |
| 2026-06-18 | 331334b | feat(3.5–3.7): states/microinteractions/a11y — ErrorState, SSE ConnectionBanner, reduced-motion AnimatedNumber + delta flash, focus-visible + aria-live |
| 2026-06-18 | 452d9ab | feat(3.4): rebuild Reports + Monitoring screens — completes 3.4; Reports relabelled units (not AED), Monitoring restyled health/stats/metrics console |
| 2026-06-18 | 73ad59c | feat(3.4): rebuild Admin screen — honest read-only console (dashboard + trend, users/stores tables, activity feed), super-admin gated |
| 2026-06-18 | f5f007c | feat(3.4): rebuild Employees/Performance screen — real `/api/employees/*` via authFetch, Sunset bio cards, restyled charts + modals, removed orphaned dupes |
| 2026-06-18 | 583f0f4 | feat(3.4): rebuild Promotions/Pricing screen — real summary/active/list/categories data, Sunset gradient cards, primitive-based create modal scoped to accessible stores |
| 2026-06-18 | bee4aae | feat(3.4): rebuild Analytics/Forecast screen — real `/api/analytics/*` data, Sunset-palette charts, Overview/Forecast tabs, interactive MAPE backtest |
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
