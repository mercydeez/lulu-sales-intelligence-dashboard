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
| 2.7 | Single frontend API client (auth/refresh/user-aware cache) | ❓ to verify |
| 2.8 | Backend test expansion (RBAC, alerts, predictor) wired to CI | 🟡 tests added, CI wiring TBD |
| 2.9 | Seed pack so no demo screen is empty | 🟡 `seed_data.sql` started |
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
  table dropped (migration 007). Pending integration proof: clean-volume boot.

## Phase changelog
- Phase 2.2/2.3 backend committed (c69bb47); Phase 3 UI groundwork (b9502fa).
- Phase 2.1 sales-table unification — this branch.
