# Implementation Plan & Tracker

The **single source of truth** for this project's execution — both what's already shipped and what's
next. We work one item at a time, stop at boundaries for review, then commit.

> This file merges the former `docs/archive/IMPLEMENTATION_ROADMAP.md` (the forward plan, now
> **Part II / Part III** below) with the phase-by-phase build log (**Part I**). Strategic/product
> rationale lives in `docs/` (GAP_ANALYSIS, PRODUCT_STRATEGY, SAAS_PATH, ADR).

---

## What this project is (purpose)

A real-time retail sales-intelligence dashboard for a UAE supermarket chain ("Lulu"), built to
demonstrate full-stack + data engineering for a resume/portfolio, now extending toward a
multi-tenant, ML/DL-backed retail-ops SaaS.

- **Data pipeline:** a `DataGenerator` writes synthetic sales to Postgres every ~5–15s and publishes
  to Redis (`sales:stream`, `alerts:stream`, `inventory:stream`); SSE endpoints relay pub/sub to the
  browser via `EventSource`.
- **Security:** JWT auth + RBAC scoped by region→store, rate limiting, CSRF, security-header middleware.
- **Features:** live KPIs, sales analytics, seasonal + ML/DL forecasting (Forecast Lab),
  inventory/expiry, alerts→tasks, promotions, employees, and a free/local-first AI assistant
  (Ollama default, OpenAI optional, rule-based fallback).
- **Constraints:** free/local-first — no paid AI APIs without approval. Synthetic data. Student → MVP → SaaS.

Data caveat baked into the codebase: the Kaggle `sales` values are **units**, not currency; revenue is
derived via `unit_price_aed` (migration 005). Historical data is 2013–2017, date-shifted on load.

---

## Status legend
✅ done & committed  ·  🟡 in progress / uncommitted  ·  ❌ not started  ·  ⏭️ deferred

---

## Where we are now (snapshot)

- **Part I — Recovery → MVP → polish (Phases 0–5):** ✅ **complete** (build log below).
- **Part II — Live SaaS + ML/DL:** 🟡 in progress.
  - **B1 — Forecasting hardening & depth:** B1.1–B1.4 ✅, **B1.5 🟡 (uncommitted)**, B1.6–B1.7 ❌ next.
  - **B2–B5** (multi-tenancy completion, billing, PaaS, chatbot APIs): ❌ not started.
- **Part III — Action layer / procure-to-pay:** ❌ future (brainstorm captured below).

**Next up:** finish & commit **B1.5** (classifier extras), then **B1.6** (heatmap depth:
store × category, per-item drill-down).

---
---

# Part I — Recovery → MVP → polish (Phases 0–5) ✅ COMPLETE

**Phase 0 — recovery** ✅  git init, `init.sql` crash fixed, SSE import fixed, dev override, CI honesty.

**Phase 1 — critical fixes** ✅  auth on all data routers, server-side store/region scoping, revenue
model (mig 005), date-shift, token hygiene, migration runner.

**Phase 2 — MVP completion** ✅ all 9 items (sales unification, inventory/expiry, alerts→tasks,
seasonal forecast, AI provider chain, `useEventStream`, API client foundation, CI, seed pack).

### Phase 3 — UI/UX redesign ✅ *(3.1–3.8, following the redesign plan order)*

| # | Task | Status |
|---|---|---|
| 3.1 | Design tokens, fonts, light/dark CSS vars, Tailwind config | ✅ Sunset Pop palette (coral/teal/violet/amber) + Inter via `next/font`; legacy dark-slate overrides removed |
| 3.2 | `ui/` primitives + `/dev/components` gallery | ✅ Button, Card, StatCard, Badge, Toast, Modal, EmptyState, Skeleton, ChartFrame, LiveIndicator, PageHeader, Tabs, Select, Input, Table (757eb6d) |
| 3.3 | App shell: sidebar nav, slim top bar, role-shaped home | ✅ sidebar replacing top Navbar (775d4c7) |
| 3.4 | Rebuild screens: Home → Inventory → Alerts → Analytics/Forecast → Promotions → Employees → Admin → Reports/Monitoring | ✅ 8/8 — home (6404c0b), Inventory (9debab7), Alerts (819b9c4), Analytics/Forecast (bee4aae), Promotions (583f0f4), Employees (f5f007c), Admin (73ad59c), Reports + Monitoring. All on the Sunset design system with real data. |
| 3.5 | States pass: skeletons, empty states, error panels, SSE-degraded banner | ✅ `ui/ErrorState` + `ui/ConnectionBanner` SSE-degraded banner |
| 3.6 | Microinteractions: number tickers, delta flashes, live-row animations, reduced-motion | ✅ shared reduced-motion-aware `ui/AnimatedNumber` + `flashOnChange` delta flash; `useReducedMotion` + global guard |
| 3.7 | Mobile pass → accessibility pass (AA contrast, keyboard, aria-live) | ✅ mobile nav drawer; `:focus-visible` ring + `aria-live`; AA contrast audit (darkened `ink-muted`, deepened gradients to 700-level) |
| 3.8 | EN/AR with RTL on nav/home/inventory/alerts | ✅ `LanguageProvider` (EN/AR, persisted, sets `<html dir/lang>`); logical utilities so the shell flips in RTL |

### Phase 4 — production readiness ✅ *(4.1–4.6, verified against the live Docker stack)*

| # | Task | Status |
|---|---|---|
| 4.1 | Tighten CSP + enumerate CORS origins | ✅ CORS methods/headers enumerated + `expose_headers`/`max_age`; CSP `connect-src` env-driven, `object-src 'none'` + prod `upgrade-insecure-requests` |
| 4.2 | Structured logging (request-id threaded through) | ✅ `request_id` contextvar + `RequestIDLogFilter` on every record; opt-in `JsonLogFormatter` (`LOG_JSON=true`) |
| 4.3 | DB indexes on hot query columns | ✅ migration `008` covering index `sales_historical (date, store_id, item_id) INCLUDE (sales)`; hot aggregation → Index Only Scan (Heap Fetches 0) |
| 4.4 | Pagination on all unbounded list endpoints | ✅ audited every GET list; `GET /api/auth/users` now paginated (`{users,total,page,limit,pages}`) |
| 4.5 | Fix `except: pass` in `data_sync` → savepoints | ✅ optional sub-queries wrapped in `begin_nested()` SAVEPOINTs + logged |
| 4.6 | Dead-code cleanup (`alembic/`, unused routes) | ✅ removed unused `alembic` dep + empty dir; audit found no other dead code |

### Phase 5 — resume/demo polish ✅ *(5.1–5.4)*

| # | Task | Status |
|---|---|---|
| 5.1 | Honest README rewrite (what works, what's synthetic) | ✅ added **Data & Honesty Notes**, corrected stale claims, linked the docs |
| 5.2 | Demo script (walk-through order) | ✅ `docs/product/DEMO_SCRIPT.md` — ~8-min guided walkthrough |
| 5.3 | Architecture decisions log (ADR format) | ✅ `docs/architecture/ADR.md` — 9 ADRs |
| 5.4 | Pitch one-pager | ✅ `docs/product/PITCH.md` |

---
---

# Part II — Live SaaS + ML/DL Build Log & Forward Plan

> The project has moved from "fix the demo" to "build a multi-tenant, ML/DL-backed retail-ops SaaS."

## A. Done (committed)

**Stabilization & correctness**
- Clean first-boot (init.sql `RAISE NOTICE` fix; init.sql ↔ migrations view consistency — tenant_id).
- SSE consolidated to one shared connection per channel; CORS dev-origin fix; `ToastProvider` mounted.
- Admin: router double-prefix fix, KPI/user queries corrected, create-user flow.
- Sales source-of-truth unified: migration 007 drops/recreates `sales_fact_view` cleanly (7d9cc60).

**Multi-tenancy (Phase 1 — foundation)**
- `tenants` table + default demo tenant; `tenant_id` on users/stores/items/sales (migration 010).
- `sales_fact_view` carries `tenant_id` (migration 011 + init.sql); `/api/tenants`; tenant-aware auth.
- KPIs tenant-scoped end-to-end (query + cache key + warmer).

**Forecasting engine (deterministic, backtest-selected)**
- Feature engineering (lags/calendar/rolling); models behind one interface: classical
  (seasonal-naive, seasonal-trend), ML (LightGBM), DL (LSTM, GRU/RNN, CNN).
- Rolling-origin backtest scores every model (MAPE/WAPE) and auto-selects the winner.
- `/api/analytics/forecast` + `/api/analytics/model-metrics` (tenant-scoped, cached).
- **Forecast Lab** tab: executive + technical views (accuracy, leaderboard, per-store heatmap,
  business-impact tiles, model-comparison, feature importance, stockout-risk confusion matrix).

## B. Forward roadmap (in order)

### B1 — Forecasting hardening & depth 🟡

1. **Scheduled / offline training** ✅ (c7c4112) — background trainer retrains on a cadence + on boot
   and caches the Forecast Lab payload; `/model-metrics` is read-only (returns `warming` on a cold
   scope, never trains on the request path). `services/forecast_trainer.py`.
2. **More DL models** ✅ (1ae5e04) — N-BEATS, TCN, Transformer added to the registry; all six DL
   models compete in the backtest. `services/forecasting/deep.py`.
3. **Forecast-vs-actual overlay + confidence/prediction bands** ✅ (d8dc95c) — held-out predicted vs
   real overlay; 80% interval (from backtest residuals) shaded around the forward forecast.
4. **Accuracy-over-time (rolling backtest trend)** ✅ (c86832a) — the selected winner scored across
   the last 6 non-overlapping windows + improving/declining/stable badge.
5. **Classifier extras** 🟡 *(implemented, uncommitted)* — ROC + precision-recall curves, AUC/AP,
   F1-tuned threshold, real `predict_proba`. Added **scikit-learn** to requirements, which also
   revives the LightGBM regressor (leaderboard) + feature-importance chart (both silently broken
   before, same root cause). *Finish: run tests, verify live, commit + push.*
6. **Heatmap depth** ❌ — store × category; per-item drill-down. *(next)*
7. **Wire forecasts across the product** ❌ — inventory reorder/expiry, promotion uplift baseline,
   dashboard revenue projection, AI assistant answers.

> Remaining B1 stretch: more DL (already done beyond plan), classifier ROC/PR (B1.5), heatmap depth
> (B1.6), product wiring (B1.7).

### B2 — Multi-tenancy completion ❌
- Apply tenant scoping to all read endpoints (sales, analytics, history, inventory, promotions, reports).
- Postgres **RLS** (dedicated non-owner role / FORCE RLS) as defense-in-depth under app-layer scoping.
- Tenant-aware caching everywhere; **isolation pytest**; a second seeded tenant for a visible
  two-tenant isolation demo.

### B3 — Billing & onboarding ❌
- Plans/tiers; Stripe subscriptions + customer portal (UAE: Telr / PayTabs / Network Intl); metering +
  usage limits; self-serve signup → create tenant → invite users → connect data.

### B4 — PaaS layer ❌
- Per-tenant **API keys** + public REST API; outbound **webhooks**; **white-label** theming per tenant;
  **developer portal** + live API docs.

### B5 — Chatbot / AI APIs ❌
- Tenant-scoped, API-key-authenticated AI assistant endpoints to embed the chatbot externally;
  free/local **Ollama** provider with rule-based fallback.

## C. Production hardening & known issues
- **Move the repo out of OneDrive** — it corrupts the git index and truncates files mid-write.
- **torch image size** — CPU wheel; keep the DL tier optional to keep images lean.
- **Theme cleanup** — remaining "Sunset" classes (coral borders, rounded-2xl, gradients) across
  shared primitives (Modal/Input/Select/Table).
- **Date-shift historical data** so "today/this week" KPIs reflect a continuous timeline.
- **Security/ops** — token hygiene, CSP tightening, RLS, UAE data residency, backups, monitoring, SLA.

## D. Run / deploy notes
- Dev: `docker compose up -d postgres redis backend` + `npm run dev` (frontend on :3000).
- **Rebuild the backend image after dependency changes** (lightgbm/torch/scikit-learn):
  `docker compose up -d --build backend`.
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in `schema_migrations`).
- Demo logins (password `Lulu@2026!`): atharva@lulu.ae (super_admin), krishna@lulu.ae
  (regional_manager), yash@lulu.ae (store_manager).

---
---

# Part III — Product Expansion: Action Layer, Procure-to-Pay & Payments (brainstorm)

> Strategic reframe: today the product is a **system of intelligence** (tells you what's happening).
> The next rungs are a **system of action** (places/approves orders) and a **system of transaction**
> (money moves). Each is a step-change in stickiness and price.

## E. The action layer — Procure-to-Pay (highest-leverage expansion)
The payoff of the forecasting engine: forecast → suggested order → approve → done.

**Flow:** Forecast → **reorder suggestion** (days-of-cover < lead time) → auto-grouped **draft PO** per
supplier → **approval workflow** (threshold-based) → send (email / EDI / portal) → supplier ack →
**goods receipt** → **3-way match** (PO = receipt = invoice) → payment.

**Entities:** Supplier, Product↔Supplier (price, MOQ, lead time), PurchaseOrder, POLine, Receipt,
Invoice, Payment, ApprovalRule.

**Build split:** *Build now* the "system of record" (suppliers, POs, approvals, receipts, invoices,
payment **status**). *Embed later* money movement (KYC/AML/licensing — partner, never build).

## F. Payments — two distinct things
1. **Billing your customers** (retailers pay you the subscription): card/recurring → Phase B3.
2. **Customers pay their suppliers** (procure-to-pay loop): B2B AP, large sums, net terms — start by
   *recording* status, then embed a payments partner. → after Part III.E records layer.

## G. Cross-vertical "steal this"
Finance/spend (approval chains, ledgers, audit) · healthcare (compliance, escalation) · restaurant
(par-level one-tap reorder, vendor catalogs, waste) · hotels (multi-property rollups, task SLAs) ·
logistics ("control tower" exception views, transfers, lead-time modeling) · e-commerce ops (PO
lifecycle, multi-location) · dev-tools/PaaS (API keys, metering, webhooks, dev portal).

## H. UI patterns to adopt
Command palette (Cmd-K) · action cards ("Milk out in 3 days → [Create PO]") · approval inbox · audit
timeline on every entity · notifications where people are (WhatsApp Business API + email + Slack) ·
mobile-first/PWA for floor/logistics · document generation (PO/invoice PDFs) + e-signature.

## I. Technologies to bring in (mapped to need)
Workflow/state machine (status enum → Temporal/Camunda) · notifications (Novu/Knock + Twilio +
Resend) · enterprise auth (WorkOS SSO/SAML/SCIM) · product analytics + errors (PostHog + Sentry) ·
search (Typesense/Meilisearch) · analytics scale (DuckDB/ClickHouse + dbt) · maps (Mapbox) · embedded
payments later (Airwallex / Stripe Treasury / Lean).

## J. Where this fits
Start the action layer (E) **after** B2 (tenant isolation) and B1 (forecasting hardening) — it depends
on tenant-scoped data + reliable forecasts. Billing (F.1) is B3. Supplier payments (F.2) come after the
procure-to-pay *records* layer. Treat E as "Phase 3.5 / 6" — the move that re-prices the product from
insight tool to operations system.

---
---

## Decision log (Part I highlights)

- **3.7 AA contrast + 3.8 EN/AR RTL:** measured WCAG ratios; `ink-muted` #8b8699→#6b6680 (3.52→5.47),
  sunset gradients + `btn-sunset` deepened to 700-level stops (white text clears AA); `LanguageProvider`
  with logical utilities so the shell mirrors under `dir=rtl` (scoped to nav + home/inventory/alerts).
- **3.5–3.7 states/microinteractions/a11y:** built cross-cutting primitives (`ErrorState`,
  `ConnectionBanner`, `AnimatedNumber` with reduced-motion + delta flash, `useReducedMotion`).
- **3.4 honesty fixes:** Reports relabelled **units** (not AED) — `/api/reports/sales` has no price
  column; Admin/Promotions/Employees rebuilt as honest read-only or scoped flows over real endpoints,
  dropping mock fallbacks; analytics PDF export dropped fabricated transactions.
- **2.7 API client:** `lib/apiClient.ts` (auth, 401→refresh single-flight→retry, user-aware cache,
  error-envelope parsing); scattered raw `fetch()` migrated opportunistically during Phase 3.
- **2.1 sales storage:** 3-tier design — `sales_stream_raw` (live) + `sales_historical` (CSV) +
  `sales_fact_view` (union readers query); streaming ids offset by 1e9; legacy `sales` dropped (mig 007).
- **2.5 AI providers:** Ollama is the zero-cost default; OpenAI opt-in; both fall through to a
  rule-based responder that always answers with live DB data. No paid key for the demo.

## Decision log (Part II highlights)

- **B1.1 offline training:** the correct ML-serving split — train in a background task, serve from
  cache. The endpoint never trains; a cold scope returns `status: "warming"` and schedules a guarded
  background warm. `MODEL_METRICS_TTL` served stale-but-warm.
- **B1.4 accuracy-over-time:** tracks the *current winner* across rolling windows (~1 fit/window,
  cheap) rather than re-selecting per window — reads as "is our production model holding up?".
- **B1.5 scikit-learn:** adding it was the single root-cause fix for the whole degraded ML tier
  (classifier `predict_proba`, LightGBM regressor in the leaderboard, feature-importance chart).

## Open findings
- ~~`data_sync.generate_alerts_from_sales` swallows query errors with `except: pass`~~ **Resolved (4.5)**
  — each optional sub-query now runs inside a `begin_nested()` SAVEPOINT and logs on failure.
- ~~LightGBM missing from the leaderboard / feature importance empty~~ **Being resolved (B1.5)** —
  scikit-learn was not installed; added in B1.5.

---

## Phase changelog

### Part II — Live SaaS + ML/DL

| Date | Commit | What landed |
|---|---|---|
| 2026-06-20 | _(uncommitted)_ | B1.5: classifier extras — ROC/PR curves, AUC/AP, F1-tuned threshold, `predict_proba`; added scikit-learn (revives LightGBM regressor + feature importance) |
| 2026-06-20 | c86832a | B1.4: accuracy-over-time rolling backtest trend + improving/declining badge |
| 2026-06-20 | d8dc95c | B1.3: forecast-vs-actual overlay + 80% prediction bands |
| 2026-06-20 | 1ae5e04 | B1.2: N-BEATS, TCN, Transformer added to the DL tier |
| 2026-06-20 | c7c4112 | B1.1: offline forecast trainer; `/model-metrics` read-only (warming on cold cache) |
| 2026-06-20 | 7d9cc60 | fix(db): migration 007 drops+recreates `sales_fact_view` without premature `tenant_id` |

### Part I — Recovery → MVP → polish

| Date | Commit | What landed |
|---|---|---|
| 2026-06-18 | _(Phase 5)_ | docs(5.1–5.4): honest README, DEMO_SCRIPT, ADR (9), PITCH — completes Phase 5 |
| 2026-06-18 | 687b392 | chore(4.6): drop unused `alembic` dependency + empty dir — completes Phase 4 |
| 2026-06-18 | 0061cb4 | feat(4.4): paginate `GET /api/auth/users` |
| 2026-06-18 | 6ab48de | feat(4.3): migration 008 covering index → index-only scan |
| 2026-06-18 | 9b20332 | feat(4.1/4.2): CORS enumeration + env-driven CSP + request-id logging |
| 2026-06-18 | 260d57a | feat(4.5): `data_sync` savepoints (no more silent `except: pass`) |
| 2026-06-18 | ad29515 | feat(3.7/3.8): AA contrast audit + EN/AR RTL — completes Phase 3 |
| 2026-06-18 | 331334b | feat(3.5–3.7): states/microinteractions/a11y |
| 2026-06-18 | 452d9ab | feat(3.4): rebuild Reports + Monitoring — completes 3.4 |
| 2026-06-18 | 73ad59c | feat(3.4): rebuild Admin (honest read-only console) |
| 2026-06-18 | f5f007c | feat(3.4): rebuild Employees/Performance |
| 2026-06-18 | 583f0f4 | feat(3.4): rebuild Promotions/Pricing |
| 2026-06-18 | bee4aae | feat(3.4): rebuild Analytics/Forecast (MAPE backtest) |
| 2026-06-18 | 819b9c4 | feat(3.4): rebuild Alerts/Tasks (ack/resolve/my-tasks) |
| 2026-06-17 | 9debab7 | feat(3.4): rebuild Inventory/Procurement |
| 2026-06-17 | 6404c0b | feat(3.4): rebuild Live Operations home |
| 2026-06-17 | 775d4c7 | feat(3.3): sidebar app shell |
| 2026-06-17 | 757eb6d | feat(3.2): ui/ primitives gallery |
| 2026-06-17 | cefbef1 | feat(2.5): LLM provider chain |
| 2026-06-17 | eed2632 | feat(2.7): frontend API client foundation |
| 2026-06-17 | 2ca2414 | feat(2.1): 3-tier sales unification + migration 007 |
| earlier | b14ad81 | feat(2.4): seasonal forecast + MAPE backtest |
| earlier | c69bb47 | feat(2.2/2.3): alerts-tasks workflow + inventory batches |
| earlier | f429529 | feat(1.5): token hygiene — refresh rotation, remember_me, jti |
