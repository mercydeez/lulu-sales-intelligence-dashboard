# Implementation Plan

The forward plan — **what's left to build**. Completed work has been trimmed out (it lives in git
history); only a compact "done so far" summary remains for orientation. Strategic/product rationale
lives in `docs/` (PRODUCT_STRATEGY, SAAS_PATH, ADR).

## Status legend
✅ done  ·  🟡 in progress  ·  ❌ not started  ·  ⏭️ deferred

---

## Done so far (summary)

- **Part I — Recovery → MVP → polish (Phases 0–5):** ✅ complete (auth/RBAC, revenue model, 3-tier
  sales unification, UI/UX redesign + a11y/RTL, production hardening, README/ADR/demo docs).
- **Part II — Live SaaS + ML/DL foundation:** multi-tenancy foundation (tenants + tenant-scoped
  `sales_fact_view`, tenant-scoped KPIs); the deterministic, backtest-selected forecasting engine +
  **Forecast Lab**.
- **B1 — Forecasting hardening & depth:** B1.1 offline trainer (read-only `/model-metrics`,
  `c7c4112`) · B1.2 N-BEATS/TCN/Transformer (`1ae5e04`) · B1.3 forecast-vs-actual + prediction bands
  (`d8dc95c`) · B1.4 accuracy-over-time (`c86832a`) · B1.5 classifier extras: ROC/PR, threshold
  tuning, `predict_proba` + scikit-learn (`9cc525d`) · B1.6 store×category heatmap + per-item
  drill-down (`39346ee`).

---

## Remaining work

### B1 — Forecasting hardening & depth (finish)
- **B1.7 — Wire forecasts across the product** ❌ — feed the forecasts into inventory reorder/expiry,
  promotion uplift baseline, the dashboard revenue projection, and AI-assistant answers (so the
  forecasting engine drives the rest of the app, not just the Lab).

### B2 — Multi-tenancy completion ❌
- Apply tenant scoping to **all** read endpoints (sales, analytics, history, inventory, promotions, reports).
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

---

## Part III — Action layer / procure-to-pay (future)

> Strategic reframe: today the product is a **system of intelligence** (tells you what's happening).
> The next rungs are a **system of action** (places/approves orders) and a **system of transaction**
> (money moves). Best started **after** B2 (tenant isolation) + B1 (forecasting) — treat as "Phase 3.5 / 6".

- **E. Procure-to-pay (highest leverage):** Forecast → reorder suggestion (days-of-cover < lead time)
  → auto-grouped draft PO per supplier → threshold-based approval → send → goods receipt → 3-way
  match → payment. Entities: Supplier, Product↔Supplier (price/MOQ/lead time), PurchaseOrder, POLine,
  Receipt, Invoice, Payment, ApprovalRule. *Build the "system of record" now; partner for money
  movement later (never build KYC/AML/licensing).*
- **F. Payments (two distinct):** (1) billing your retailer customers → B3; (2) customers paying
  their suppliers (B2B AP) → record status first, embed a partner later.
- **H. UI patterns to adopt:** command palette (Cmd-K), action cards ("Milk out in 3 days → [Create
  PO]"), approval inbox, audit timeline, WhatsApp/email/Slack notifications, mobile-first/PWA, PO/
  invoice PDF generation + e-signature.
- **I. Tech to bring in:** workflow/state machine (status enum → Temporal/Camunda), notifications
  (Novu/Knock + Twilio + Resend), enterprise auth (WorkOS SSO/SAML/SCIM), PostHog + Sentry, search
  (Typesense/Meilisearch), analytics scale (DuckDB/ClickHouse + dbt), Mapbox, embedded payments
  (Airwallex / Stripe Treasury / Lean).

---

## Production hardening & known issues (open)
- **Move the repo out of OneDrive** — it corrupts the git index and truncates files mid-write.
- **torch image size** — CPU wheel; keep the DL tier optional to keep images lean.
- **Theme cleanup** — remaining "Sunset" classes (coral borders, rounded-2xl, gradients) across shared
  primitives (Modal/Input/Select/Table).
- **Security/ops** — token hygiene, CSP tightening, RLS, UAE data residency, backups, monitoring, SLA.

## Run / deploy notes
- Dev: `docker compose up -d postgres redis backend` + `npm run dev` (frontend on :3000).
- **Rebuild the backend image after dependency changes** (lightgbm/torch/scikit-learn):
  `docker compose up -d --build backend`.
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in `schema_migrations`).
- Demo logins (password `Lulu@2026!`): atharva@lulu.ae (super_admin), krishna@lulu.ae
  (regional_manager), yash@lulu.ae (store_manager).
