# Implementation Roadmap

> Historical note: this file captures the June 2026 audit or planning state. Some issues listed here were later fixed. Use [../../README.md](../../README.md) and [../README.md](../README.md) for the current project state.


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

---
---

# Part II — Live SaaS + ML/DL Build Log & Forward Plan (updated June 2026)

> This part supersedes Part I's framing: the project has moved from "fix the demo"
> to "build a multi-tenant, ML/DL-backed retail-ops SaaS." It records what is
> already built and the sequenced plan for everything still planned.

## A. Done (committed)

**Stabilization & correctness**
- Clean first-boot (init.sql `RAISE NOTICE` fix; init.sql ↔ migrations view consistency — tenant_id).
- SSE consolidated to one shared connection per channel (fixed live-feed reconnect storm).
- CORS dev-origin fix (localhost/127.0.0.1, any port); `logger` import in stream route.
- `ToastProvider` mounted (fixed data-sources crash).
- Admin: router double-prefix fix, KPI/user queries corrected to real columns, **create-user** flow.

**UI**
- "Operations console" retheme at the token level (tokens + StatCard/Button/Card); calm, flat, teal brand, tabular numbers. (Per-page Sunset-class cleanup still pending — see C.)

**Multi-tenancy (Phase 1 — foundation)**
- `tenants` table + default demo tenant; `tenant_id` on users/stores/items/sales tables (migration 010).
- `sales_fact_view` carries `tenant_id` (migration 011 + init.sql).
- `/api/tenants` (list/create, super-admin); tenant-aware auth (`current_user.tenant_id`).
- KPIs tenant-scoped end-to-end (query + cache key + warmer).

**Forecasting engine (deterministic, backtest-selected)**
- Feature engineering (lags/calendar/rolling), models behind one interface:
  classical (seasonal-naive, seasonal-trend), ML (LightGBM), DL (LSTM, GRU/RNN, CNN).
- Rolling-origin backtest scores every model (MAPE/WAPE) and auto-selects the winner.
- `/api/analytics/forecast` and `/api/analytics/model-metrics` (tenant-scoped, cached).
- **Forecast Lab** tab: executive view (accuracy, model-in-use, MAPE, leaderboard, per-store
  heatmap, plain-language takeaway, business-impact tiles) + technical view (model-comparison
  table, forecast chart, feature importance, stockout-risk **confusion matrix**).
- Business impact with explicit formulas (projected revenue = units × price; exposure caught
  = risk days caught × avg daily revenue).

## B. Forward roadmap (planned, in order)

### B1 — Forecasting hardening & depth  🔴 next
1. **Scheduled / offline training**: a background trainer retrains models on a cadence and
   caches forecasts + metrics; endpoints only READ. Fixes request-time slowness; the correct
   ML-serving pattern. *Acceptance:* Forecast Lab loads instantly; no training on the request path.
2. **More DL models**: N-BEATS, TCN, Transformer — added to the registry, compete in the backtest.
3. **Forecast-vs-actual overlay** + confidence/prediction bands (show held-out predicted vs real).
4. **Accuracy-over-time** (rolling backtest trend) — is the model improving?
5. **Classifier extras**: ROC + precision-recall curves, threshold tuning, `predict_proba`.
6. **Heatmap depth**: store × category; per-item drill-down.
7. **Wire forecasts across the product**: inventory reorder/expiry, promotion uplift baseline,
   dashboard revenue projection, AI assistant answers.

### B2 — Multi-tenancy completion (Phase 2)  🔴
- Apply tenant scoping to all read endpoints (sales, analytics, history, inventory, promotions, reports).
- Postgres **RLS** (dedicated non-owner role / FORCE RLS) as defense-in-depth under app-layer scoping.
- Tenant-aware caching everywhere; **isolation pytest**; tenant-aware user creation + a second
  seeded tenant for a visible two-tenant isolation demo.

### B3 — Billing & onboarding (Phase 3)  🟠
- Plans/tiers; Stripe subscriptions + customer portal (UAE alternatives: Telr / PayTabs / Network Intl);
  metering + usage limits; self-serve signup → create tenant → invite users → connect data.

### B4 — PaaS layer (Phase 4)  🟠
- Per-tenant **API keys** + public REST API; outbound **webhooks**; **white-label** theming per
  tenant; **developer portal** + live API docs.

### B5 — Chatbot / AI APIs (Phase 5)  🟡
- Tenant-scoped, API-key-authenticated AI assistant endpoints to embed the chatbot externally;
  free/local **Ollama** provider with rule-based fallback.

## C. Production hardening & known issues
- **Move the repo out of OneDrive** — it corrupts the git index and truncates files mid-write
  (root cause of several incidents this build). Highest-leverage stability fix.
- **torch image size** — CPU wheel; make the DL tier optional to keep images lean.
- **Request-time ML training → scheduled** (B1.1).
- **Theme cleanup** — remaining "Sunset" classes (coral borders, rounded-2xl, gradients) across
  pages and shared primitives (Modal/Input/Select/Table/etc.).
- **Date-shift historical data** so "today/this week" KPIs reflect a continuous timeline.
- **Security/ops** — token hygiene, CSP tightening, RLS, UAE data residency, backups, monitoring, SLA.

## D. Run / deploy notes
- Dev: `docker compose up -d postgres redis backend` + `npm run dev` (frontend on :3000).
- **Rebuild the backend image after dependency changes** (lightgbm/torch): `docker compose up -d --build backend`.
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in `schema_migrations`).
- Demo logins (password `Lulu@2026!`): atharva@lulu.ae (super_admin), krishna@lulu.ae (regional_manager), yash@lulu.ae (store_manager).

---
---

# Part III — Product Expansion: Action Layer, Procure-to-Pay & Payments (brainstorm, June 2026)

> Strategic reframe: the product today is a **system of intelligence** (it tells you what's
> happening). The next two rungs are a **system of action** (it does things — place/approve
> orders) and a **system of transaction** (money moves — pay suppliers). Each rung is a step-change
> in stickiness and price. This part captures the expansion ideas and the cross-vertical research.

## E. The action layer — Procure-to-Pay (highest-leverage expansion)

Turns "a dashboard that tells me" into "a system that runs my replenishment." It's the natural
payoff of the forecasting engine: forecast → suggested order → approve → done.

**Flow (procure-to-pay):**
Forecast → **reorder suggestion** (days-of-cover < lead time) → auto-grouped **draft PO** per
supplier → **approval workflow** (threshold-based: small POs auto-approve, large route to CEO) →
send (email / EDI / supplier portal) → supplier ack → **goods receipt** → **3-way match**
(PO = receipt = invoice) → payment.

**Entities:** Supplier, Product↔Supplier (price, MOQ, lead time), PurchaseOrder, POLine, Receipt,
Invoice, Payment, ApprovalRule. **Roles:** store/logistics mgr raises; regional mgr / CEO approve by
threshold; logistics receives; finance pays.

**Build split (important):**
- **Build now — "system of record":** suppliers, POs, approvals, receipts, invoices, payment
  *status*. ~90% of the value, almost none of the regulatory weight.
- **Embed later — money movement:** actually paying suppliers = KYC/AML + money-transmission
  licensing. Never build; partner (Airwallex / Stripe Treasury / MENA open-banking: Lean, Tarabut).

## F. Payments — two different things (do not conflate)

1. **Billing your customers** (retailers pay *you* the subscription): card/recurring. Light.
   Stripe Billing, or UAE-local Telr / PayTabs / Network International / Mamo / Ziina. → Phase 3.
2. **Customers pay their suppliers** (the procure-to-pay loop): B2B accounts-payable, large sums,
   net terms. Fintech-grade. Start by *recording* payment status (bank transfer outside the system),
   then embed a payments partner. → Part III.E, after the records layer.

*Note: UAE gateway availability/pricing/licensing change often — verify current options when chosen.*

## G. Cross-vertical "steal this" (research across SaaS/PaaS categories)

| Category (exemplars) | What they nail | Borrow for retail-ops |
|---|---|---|
| Finance/Spend (Stripe, Ramp, Brex, Mercury) | Money UI: approval chains, spend controls, ledgers, reconciliation, audit | Threshold PO approvals, "needs your sign-off" inbox, immutable audit timeline, precise money UI |
| Healthcare (Epic, Veeva) | Compliance, consent, role-scoped sensitive data, escalation | Data governance/residency (PDPL), alert→ack→escalate, reliability framing for enterprise |
| Restaurant (Toast, Square, MarketMan) | Recipe/BOM depletion, par-level one-tap reorder, vendor catalogs, waste, mobile floor | Par-level auto-reorder, vendor catalog → one-tap PO, waste/expiry, mobile ops |
| Hotels (Opera, Mews, Cloudbeds) | Multi-property rollups, task assignment, occupancy forecasting, dynamic pricing | Region→store rollups, task assignment + SLA, dynamic/markdown pricing (expiry) |
| Logistics (Flexport, project44, Blue Yonder) | "Control tower" exception views, transfers, ETA, lead-time modeling | Exception-first screen, store-to-store transfers, lead-time-aware reorder |
| E-commerce ops (Shopify, Brightpearl, Lightspeed) | PO modules, multi-location inventory, app marketplace | PO lifecycle, marketplace model (= Phase 4 PaaS) |
| Dev-tools/PaaS (Twilio, Vercel, Stripe) | API keys, metering, webhooks, dev portal, SDKs | Exactly the Phase 4 PaaS playbook |

## H. UI patterns to adopt (cross-cutting)

- **Command palette (Cmd-K)** — jump anywhere + run actions ("create PO", "go to Al Barsha").
- **Action cards** — every insight gets a button ("Milk out in 3 days → [Create PO]"). The bridge
  from intelligence to action.
- **Approval inbox** — one "needs you" queue.
- **Audit timeline** on every order/entity.
- **Notifications where people are** — in UAE/MENA that's **WhatsApp** (Business API) + email + Slack/Teams.
- **Mobile-first / PWA** for floor + logistics; desktop for HQ.
- **Document generation** (PO/invoice PDFs) + **e-signature** (DocuSign/Dropbox Sign) for supplier contracts.

## I. Technologies to bring in (mapped to need)

- **Workflow/state machine:** status enum first → Temporal/Camunda when approval flows get complex.
- **Notifications infra:** Novu or Knock (orchestrate email/WhatsApp/Slack) + Twilio + Resend/SendGrid.
- **Enterprise auth:** WorkOS (SSO/SAML/SCIM) — unlock for large-retailer sales.
- **Product analytics + errors:** PostHog + Sentry.
- **Search (as data grows):** Typesense/Meilisearch across SKUs/orders.
- **Analytics scale:** DuckDB/ClickHouse + dbt when per-tenant data gets heavy (request-time SQL won't scale forever).
- **Maps/routing:** Mapbox for transfers/deliveries.
- **Embedded payments (later):** Airwallex / Stripe Treasury / Lean (MENA open banking).

## J. Where this fits in the sequence

Action layer (E) is best started **after** Phase 2 (tenant isolation) and the forecasting hardening
(B1), since it depends on tenant-scoped data + reliable forecasts. Billing (F.1) stays Phase 3.
Supplier payments (F.2) come after the procure-to-pay *records* layer is solid. Treat E as
"Phase 3.5 / 6" — the move that re-prices the product from insight tool to operations system.


