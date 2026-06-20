# Implementation Plan

The forward plan — **what's left to build**. Completed work has been trimmed out (it lives in git
history); only a compact "done so far" summary remains for orientation. Strategic/product rationale
lives in `docs/` (PRODUCT_STRATEGY, SAAS_PATH, ADR).

## Status legend
✅ done  ·  🟡 in progress  ·  ❌ not started  ·  ⏭️ deferred

---

## Status snapshot — what's done, what's left, suggestions

### ✅ Done (shipped, tested, verified live in Docker)
- **B1.7** — forecasts wired across the product (dashboard revenue projection, inventory reorder, promo
  uplift baseline, AI answers).
- **B2** — multi-tenancy **complete**: app-layer `tenant_id` scoping on every read, tenant-aware caches,
  tenant-scoped AI assistant, Postgres **FORCE RLS + non-owner `app_rw` role** (proven at the DB level),
  `security_invoker` view, second seeded tenant (Northwind), isolation tests.
- **B3** — self-serve onboarding (signup → isolated tenant + sample data + auto-login, invites,
  checklist). Billing intentionally deferred.
- **B4** — PaaS **complete**: per-tenant API keys, public REST API, embeddable AI, white-label branding,
  HMAC-signed webhooks firing on real domain events, in-app developer portal.
- **B5** — embeddable, tenant-scoped AI (Ollama → rule-based fallback, zero paid keys).
- **Part III-E** — procure-to-pay **system of record complete**: forecast → grouped MOQ draft PO →
  manual/auto approval → send → goods receipt (partial/full) → supplier invoice → 3-way match; suppliers
  + catalog; RLS on all entities.
- **Part III-H** — PO PDF, approval inbox (+nav badge), dashboard action cards, Cmd-K command palette,
  audit timeline (procurement event log), **PWA installable offline shell**.
- **Live fixes** found & repaired: truncated `kpis.py`, migration-013 sequence collision, public-API
  kwarg 500, KPIs CORS preflight, view RLS leak, audit-log jsonb bind.
- Backend **150 tests pass** · frontend `tsc` clean · 22 migrations apply on boot.

### ⏭️ Remaining — deferred by you, or needs external services / a decision
- **Billing (B3 / Part III-F)** — Stripe/Telr subscriptions + metering. Deferred to go-to-market.
- **Payments / B2B AP (Part III-F)** — partner for money movement; never build KYC/AML/licensing.
- **Notifications (Part III-H)** — WhatsApp/Slack/email; needs Twilio/Resend/Slack credentials.
- **E-signature (Part III-H)** — needs a provider (DocuSign / Dropbox Sign).
- **Part III-I infra** — Temporal/Camunda, WorkOS SSO/SAML/SCIM, PostHog+Sentry, Typesense/Meili,
  DuckDB/ClickHouse+dbt, Mapbox, embedded payments. Future platform adoptions.
- **FORCE-RLS request-path enablement** — role + DB enforcement shipped & proven; flip `USE_RLS_ROLE=true`
  after two follow-ups (set the GUC after auth; cross-tenant public-API key lookup).

### 💡 Suggestions (highest leverage next)
1. **Notifications on existing events** — a free Slack incoming webhook (no SDK) on 3-way-match
   exceptions / low stock / PO approved is ~half a day and immediately useful; reuse `dispatch_event`.
2. **Finish FORCE-RLS enforcement** — set the GUC after auth (tiny middleware/dependency) + special-case
   the public-API key lookup, then run with `USE_RLS_ROLE=true` for true DB-enforced isolation.
3. **Sentry + PostHog** — cheapest observability/analytics credibility win before real users.
4. **Harden CI** — run the full backend suite (not just config/security), fail on `tsc` errors, and add a
   compose smoke test (`/health` + `/api/kpis`).
5. **Billing when ready** — Stripe Checkout maps cleanly onto the existing `tenants.plan` + API-key
   `request_count` metering hooks; small lift on top of the tenant model.
6. **UAE data residency + backups** — managed Postgres in a UAE region + nightly dumps before production.

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
- **B1.7 — Wire forecasts across the product** ✅ — shared `services/forecast_service.py` feeds the
  forecasting engine into: inventory reorder (`GET /api/inventory/reorder-suggestions`, days-of-cover
  < lead time → recommended order qty), promotion uplift baseline (`GET /api/promotions/uplift-baseline`),
  the dashboard revenue projection (`GET /api/kpis/projection`), and AI-assistant answers (forecast
  intent → engine-driven narrative + top reorder risks). Tested (`tests/test_forecast_service.py`).

### B2 — Multi-tenancy completion ✅
- App-layer tenant scoping across **all** DataSyncService read methods (inventory summary/items/
  categories, alerts, promotions, category-performance) — they filter `tenant_id`; routes pass it from
  the JWT and partition caches by tenant. Closes the super_admin all-stores leak; KPIs/analytics already
  scoped. Per-request tenant GUC (`tenant_context` + `apply_tenant_guc`).
- Postgres **RLS** (migration 012): `tenant_isolation` policies keyed off `app.tenant_id` GUC with a
  `current_tenant_id()` helper + demo fallback; ENABLEd (non-breaking under owner) with documented
  FORCE/non-owner hardening.
- **Isolation pytest** (`tests/test_tenant_isolation.py`: SQL-capture proof + tenant-partitioned cache
  keys + migration presence + DB-gated live disjointness). Second seeded tenant — **Northwind Foods**
  (migration 013): own stores/items/~120d sales + `owner@northwind.ae`.
- The in-app **AI assistant is now tenant-scoped** too: `tenant_id` added to the Sale/Store/Item models
  and threaded through every `ai_assistant` data function + the authenticated `/api/ai/chat` routes, so a
  tenant's chatbot only ever sees its own data (verified: Lulu 913k records vs Northwind 1.9k).
- **FORCE RLS + non-owner role** ✅ (migration 020): a dedicated, non-superuser `app_rw` role with
  `FORCE ROW LEVEL SECURITY` on all 16 tenant tables (+ parent-scoped policies on the line tables) and
  `security_invoker` on `sales_fact_view` (migration 021) so the view honours the caller's RLS. **Proven
  at the DB level**: `app_rw` with `app.tenant_id=1` sees only tenant 1, `=2` only tenant 2, while the
  superuser app account bypasses (by design). Opt-in app wiring (`USE_RLS_ROLE`, `services/database.py`
  app_rw engine) routes the authenticated request path through `app_rw`; off by default since app-layer
  scoping is the primary control. ⏭️ To turn RLS mode fully on for the request path: set the
  `app.tenant_id` GUC *after* auth (the JWT carries no tenant, so the per-request set must follow
  `get_current_user`) and special-case the public-API key lookup (the key determines the tenant, so it
  must read across tenants). Per-item `predictor` is implicitly scoped (store_ids are tenant-unique).

### B4 — PaaS layer ✅
- Per-tenant **API keys** ✅ (migration 014 `tenant_api_keys`, `services/api_key_service.py`, mgmt at
  `/api/api-keys`) + public REST API ✅ (`/api/public/v1/*`: kpis, projection, reorder, ai/ask). The key
  IS the tenant scope. **White-label** ✅ (per-tenant brand/logo/accent: public `/api/public/v1/branding`
  for embedded widgets + admin `PATCH /api/tenants/branding`). Outbound **webhooks** ✅ (migration 015
  `tenant_webhooks`, `services/webhook_service.py` with HMAC-SHA256-signed delivery + event-subscription
  matching, mgmt + test-ping at `/api/webhooks`; `dispatch_event[_background]` ready for producers).
  Developer guide: `docs/PUBLIC_API.md`. Webhooks **fire on real domain events** (procurement PO
  lifecycle, goods receipt, 3-way-match exceptions). **Developer portal** ✅ — in-app `/developers` page
  to create/revoke API keys, manage + test webhooks, browse the public API, and open Swagger.

### B5 — Chatbot / AI APIs ✅
- Free/local **Ollama** provider with rule-based fallback already wired (`services/llm/`); tenant-scoped,
  API-key-authenticated embeddable AI endpoint shipped at `POST /api/public/v1/ai/ask`.

### B3 — Onboarding ✅ / Billing ⏭️ (deferred until go-to-market)
- **Self-serve onboarding** ✅ (go-to-market viability, no billing): `POST /api/auth/signup` provisions an
  isolated tenant + owner (super_admin) and optionally pre-loads a sample dataset so the dashboard shows
  value on day one (`services/tenant_provisioning.py`); auto-login on success. Team **invites**
  (`POST /api/auth/invite`, admin → temp password + must-change) and an **onboarding checklist**
  (`GET /api/auth/onboarding`). Frontend **signup page** (`/signup`) + `signup()` in AuthContext, linked
  from login. Also fixed: super_admin `accessible_stores` is now tenant-scoped (was all-tenant).
- ⏭️ **Billing deferred** — Stripe/Telr subscriptions, metering, usage limits come last, when we go to
  market. Tenants run on a free `trial` plan until then.

---

## Part III — Action layer / procure-to-pay (future)

> Strategic reframe: today the product is a **system of intelligence** (tells you what's happening).
> The next rungs are a **system of action** (places/approves orders) and a **system of transaction**
> (money moves). Best started **after** B2 (tenant isolation) + B1 (forecasting) — treat as "Phase 3.5 / 6".

- **E. Procure-to-pay (highest leverage):** ✅ **full system of record shipped.** Forecast → reorder →
  **auto-grouped draft PO per supplier (MOQ-respected)** → **configurable auto-/manual approval** → send
  → **goods receipt (partial/full)** → **supplier invoice + 3-way match** (ordered vs received vs
  invoiced, qty + price variance flags). Entities live (migrations 016–019, all RLS + tenant-scoped):
  Supplier, Product↔Supplier, PurchaseOrder, POLine, GoodsReceipt(+lines), SupplierInvoice(+lines),
  ApprovalRule. Full PO lifecycle with transition validation + approval-threshold guard. API:
  `/api/procurement/*` (suppliers, `purchase-orders/generate`, list/detail, `/status`, `/receive`,
  `/invoices`, `/invoices/{id}/match`, `/approval-rule`). **Frontend** `/procurement` page (generate →
  approve → send → receive). Demo tenant seeded with 3 suppliers + 50-item catalog. Domain events emit
  **signed webhooks** (purchase_order.created/approved/sent/received, goods.received,
  invoice.match_exception). All tested + verified live in Docker. ⏭️ Remaining: Payment leg (partner for
  money movement — never build KYC/AML/licensing).
- **F. Payments (two distinct):** (1) billing your retailer customers → B3; (2) customers paying
  their suppliers (B2B AP) → record status first, embed a partner later.
- **H. UI patterns to adopt:** **PO document/PDF generation** ✅ (`/procurement/po/{id}`, print → PDF).
  **Approval inbox** ✅ (`/approvals` — pending POs with inline approve/reject + bulk approve, nav badge
  count, `GET /api/procurement/approvals`). **Action cards** ✅ (dashboard Action Center: forecast reorder
  needs, pending approvals, expiry risk → one-click to the right page). **Command palette** ✅ (Cmd/Ctrl-K
  global navigation + quick actions). **Audit timeline** ✅ — append-only `procurement_events` log
  (migration 022, RLS+FORCE) written atomically with each PO/receipt/invoice action and attributed to the
  actor; `GET /api/procurement/events`, shown as a global Activity feed on `/procurement` and a per-PO
  trail on the PO page. **PWA / installable offline shell** ✅ — web manifest + service worker
  (`public/sw.js`: network-first navigations → `/offline.html` fallback, cache-first static, API/SSE left
  untouched), generated icons, registered in production via `ServiceWorkerRegister`. ⏭️ Still roadmap
  (need external services): WhatsApp/email/Slack notifications, e-signature.
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
- **Security/ops** — token hygiene, CSP tightening, UAE data residency, backups, monitoring, SLA.
  (RLS: FORCE RLS + `app_rw` non-owner role shipped in migration 020; flip `USE_RLS_ROLE=true` to enforce
  on the request path once the two follow-ups above are wired.)

## Run / deploy notes
- Dev: `docker compose up -d postgres redis backend` + `npm run dev` (frontend on :3000).
- **Rebuild the backend image after dependency changes** (lightgbm/torch/scikit-learn):
  `docker compose up -d --build backend`.
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in `schema_migrations`).
- Demo logins (password `Lulu@2026!`): atharva@lulu.ae (super_admin), krishna@lulu.ae
  (regional_manager), yash@lulu.ae (store_manager).
