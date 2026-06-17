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

**Phase 2 — MVP completion** ✅ *(all items committed on `phase-2-mvp-completion`)*

| # | Task | Status |
|---|---|---|
| 2.1 | Unify 3 sales tables → one source of truth | ✅ `sales_fact_view` is single read source; generator→`sales_stream_raw`; legacy `sales` dropped (mig 007); clean-boot verified |
| 2.2 | Inventory batches + expiry (mig 006) | ✅ migration + wiring committed (c69bb47) |
| 2.3 | Alerts → tasks (acknowledge/assign/resolve) | ✅ `alert_service.py` committed (c69bb47) |
| 2.4 | Seasonal forecast + MAPE backtest | ✅ committed (b14ad81) |
| 2.5 | AI provider abstraction (`services/llm/`) | ✅ Ollama→OpenAI→rule-based chain wired; `LLMError` exported (cefbef1) |
| 2.6 | Single `useEventStream` hook | ✅ committed |
| 2.7 | Single frontend API client (auth/refresh/user-aware cache) | ✅ `lib/apiClient.ts` + `api.ts` + `AuthContext` wired (eed2632); 22 legacy call sites migrate opportunistically in Phase 3 |
| 2.8 | Backend tests wired to CI | ✅ `ci.yml` runs full `pytest` + strict `tsc` + docker builds |
| 2.9 | Seed pack — no empty demo screens | ✅ fixed inventory/items bug; every nav page populates |

---

**Phase 3 — UI/UX redesign** 🟡 *(active phase)*

| # | Task | Status |
|---|---|---|
| 3.1 | Design tokens + `globals.css` reset | 🟡 groundwork in b9502fa — needs finalising (color palette, spacing scale, typography) |
| 3.2 | `src/components/ui/` primitive library | ❌ Button, Card, Badge, Input, Select, Table, Modal, Skeleton |
| 3.3 | App shell & Navbar rebuild | ❌ responsive sidebar, role-aware nav links, user avatar/logout |
| 3.4 | Login page rebuild | 🟡 WIP in b9502fa — needs error states, loading UX, redirect-after-login |
| 3.5 | Dashboard / KPI cards rebuild | 🟡 WIP in b9502fa — needs Skeleton loaders, SSE-wired live numbers |
| 3.6 | Sales analytics screen | ❌ trend chart, store/item filters, date range picker |
| 3.7 | Inventory & expiry screen | ❌ table with batch rows, expiry countdown badges, low-stock highlight |
| 3.8 | Alerts → tasks screen | ❌ kanban or list view, acknowledge/assign/resolve actions |
| 3.9 | Employees screen | ❌ org-chart or table, department filter |
| 3.10 | Promotions screen | ❌ active/scheduled/expired tabs |
| 3.11 | AI chatbot panel | ❌ streaming response render, session reset, copy button |
| 3.12 | Migrate 22 raw `fetch()` call sites → `apiClient` | ❌ opportunistic during each screen rebuild above |

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

1. 🔴 **3.1–3.5** — design tokens + primitive library + app shell + login + KPIs: the "first impression" screens every reviewer sees in 30 seconds.
2. 🟠 **3.6–3.11** — screen-by-screen rebuilds (migrate call sites as each screen is touched).
3. 🟡 **Phase 4** — production hardening (can run in parallel with late Phase 3).
4. 🟢 **Phase 5** — polish/demo (last, once everything looks and works right).

---

## Decision log

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
