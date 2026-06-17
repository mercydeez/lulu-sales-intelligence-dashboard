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

## Where we are now (snapshot)

**Phase 0 — recovery** ✅  git init, `init.sql` crash fixed, SSE import fixed, dev override, CI honesty.
**Phase 1 — critical fixes** ✅  auth on all data routers, server-side store/region scoping, revenue
model (mig 005), date-shift, token hygiene, migration runner.
**Phase 2 — MVP completion** 🟡 *(active phase)*
| # | Task | Status |
|---|---|---|
| 2.1 | Unify 3 sales tables → one source of truth | ✅ view is single read source; generator→stream_raw; legacy `sales` dropped (mig 007) |
| 2.2 | Inventory batches + expiry (mig 006) | 🟡 migration present, wiring uncommitted |
| 2.3 | Alerts → tasks (acknowledge/assign/resolve) | 🟡 `alert_service.py` uncommitted |
| 2.4 | Seasonal forecast + MAPE backtest | ✅ |
| 2.5 | AI provider abstraction (`services/llm/`) | 🟡 providers added, integration uncommitted |
| 2.6 | Single `useEventStream` hook | ✅ |
| 2.7 | Single frontend API client (auth/refresh/user-aware cache) | ❌ 3 dup auth-fetch impls + 22 raw fetch sites |
| 2.8 | Backend test expansion (RBAC, alerts, predictor) wired to CI | ✅ ci.yml runs full pytest + strict tsc + docker builds (verified) |
| 2.9 | Seed pack so no demo screen is empty | ✅ every page populates (fixed inventory/items bug); low-stock empty by design |
**Phase 3 — UI/UX redesign** ❌ design tokens, `ui/` primitives, app shell, screen rebuilds.
**Phase 4 — production readiness** ❌ CSP/CORS tightening, logging, indexes, dead-code cleanup.
**Phase 5 — resume/demo polish** ❌ honest README, demo script, decisions log, pitch one-pager.

---

## Criticality ranking (what to do next, most → least critical)

1. 🔴 **Finish & commit Phase 2 in-progress work** (2.2/2.3/2.5) — half-done features in the working
   tree are the biggest risk; they must compile, pass tests, and land as clean commits.
2. 🔴 **2.1 unify sales tables** — schema dishonesty; every later feature must pick a table.
3. 🟠 **2.7 / 2.8 / 2.9** — single API client, test+CI wiring, seed pack (no empty demo screens).
4. 🟡 **Phase 3 UI/UX** — the visual "wow" for a portfolio; largest effort.
5. 🟡 **Phase 4 production hardening** — CSP/CORS/logging/indexes.
6. 🟢 **Phase 5 polish** — README, demo script, pitch.

---

## Decision log
- **2.1 sales storage:** adopted the 3-tier design (over collapsing to one table).
  `sales_stream_raw` = live events, `sales_historical` = CSV, `sales_fact_view` = the
  union every reader queries. View is shaped as a drop-in for the old `sales` columns;
  streaming ids offset by 1e9 to keep the ORM identity map correct. Legacy `sales`
  table dropped (migration 007). **Verified via clean-volume `docker compose` boot:**
  migrations 001–007 apply, legacy `sales` gone, view total = historical + stream,
  inventory/alerts/materialized-views seed from the view, KPIs/analytics/sales serve
  real data, RBAC scoping holds (store-manager sees only their store), unauth → 401.

## Open findings (surfaced by the clean boot)
- ✅ **Employee seeding fixed:** the `Employee` ORM model mismatched the DB on two
  columns — attribute `reports_to_id` mapped to no column (DB has `reports_to`), and
  `department`/`status` were typed `String` while the DB uses PG enums. Mapped the
  attribute to the real column and bound the two enum columns (`values_callable`).
  30 employees now seed on boot; `/api/employees/employees` populated. Model-only fix.
- ✅ **inventory/items empty fixed:** store filter used `s.store_id` where `s`
  aliases the `stores` table (key `id`); errored for every scoped request and was
  caught into an empty list. Filter on `s.id`. Pre-existing; surfaced verifying 2.9.
- `data_sync.generate_alerts_from_sales` swallows query errors with `except: pass`,
  which poisons the transaction and masks the real failure (made 2.1 alert debugging
  hard). Consider savepoints/rollback per sub-query. Pre-existing design issue.

## Phase changelog
- Phase 2.2/2.3 backend committed (c69bb47); Phase 3 UI groundwork (b9502fa).
- Phase 2.1 sales-table unification (2ca2414) + boot-test fixes — this branch.
