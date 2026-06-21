# Implementation Plan

The **forward** roadmap — what's left to build. Completed work lives in git history and is no
longer tracked here. Strategic/product rationale lives in `docs/` (PRODUCT_STRATEGY, SAAS_PATH, ADR).

> **Where we are:** the product is a working **system of intelligence** (auth/RBAC, multi-tenancy
> + RLS, live sales pipeline, forecasting + Forecast Lab, procure-to-pay system of record, PaaS
> layer, PWA shell). The next milestone turns it into a **rock-solid, accuracy-first diagnostic
> SaaS** — tenant-generic so it serves either **B2B** retail or **B2G** oversight — that surfaces
> not just *what's going right* but *what's going wrong*, answers arbitrary business questions
> accurately via a local NL→SQL chatbot (**Sage**), and becomes **agentic** last, incrementally.

## Prototype constraints
- **No paid services.** Local **Ollama** for the LLM, **BullMQ on the existing Redis** for jobs,
  deterministic rules for diagnostics. Paid tiers (Stripe, hosted LLMs, Temporal, WorkOS, etc.)
  stay deferred until go-to-market.
- **Accuracy is the product.** Every number Sage or a panel shows must be derivable and correct.
  Convention: VOLUME metrics in **units**, VALUE metrics in **AED**, never mixed on one axis
  (reference: `backend/app/routes/kpis.py`).

## Status legend
✅ done · 🟡 in progress · ❌ not started · ⏭️ deferred

---

## Phase 0 — Reliability foundation (unblock the API) 🟡
Goal: the stack runs from the current build and the API actually responds under load.
- ✅ **Event-loop unblock** — the Forecast Lab trainer was running CPU-bound model work
  (pandas/sklearn/torch) on the asyncio loop, pinning all cores and starving the HTTP server.
  Heavy compute now runs in a worker thread via `asyncio.to_thread`
  (`routes/analytics.py::_compute_model_metrics_sync`), DB I/O stays on the loop, and the trainer
  is gated by `forecast_trainer_enabled` + a startup delay (`services/forecast_trainer.py`).
- 🟡 **Compose hygiene** — fixed `container_name:` collisions block parallel project dirs;
  document the single canonical project + ports.
- ❌ **Smoke check in CI** — `/health` + one authed `/api/kpis` after `docker compose up`, wired
  into `.github/workflows/ci.yml`.

## Phase 1 — Accuracy hardening ("tighten the screws") ❌
Goal: every insight/output is provably correct. Builds on the shipped units/AED separation.
- **Automated guards** — pytest asserting revenue endpoints derive AED (`SUM(sales*unit_price_aed)`)
  and KPI volume fields are integer units; a test that flags `formatCurrency` bound to a units field.
- **Golden-number tests** — from the seeded dataset, assert known KPI/analytics totals so any
  aggregation regression fails CI. Files: `backend/tests/` (+ `conftest.py`).
- **Resolve remaining smells** — per-tenant store names in `ai_assistant` (no hardcoded list); the
  `total_sales` alias that actually holds AED in `analytics.py`/`admin.py` → rename `total_revenue`;
  unify `promotions.CATEGORY_COSTS` vs `items.unit_price_aed` to a single price source.

## Phase 2 — "Sage": NL→SQL diagnostic chatbot on Ollama ❌
Goal: replace intent-stuffing with grounded NL→SQL so Sage answers arbitrary business questions
accurately, with **zero hallucination**.
- **Rename** the chatbot to **Sage** everywhere (`ai_assistant.py`, `routes/ai.py`, frontend
  `ChatBot.tsx`/`AIToggleButton.tsx`, add `CHATBOT_NAME` to `brand.ts`).
- **NL→SQL pipeline** (new `backend/app/services/nl2sql/`): Ollama gets a curated, tenant-scoped
  schema + few-shot examples → emits a single `SELECT` → **allow-list guard** (one statement,
  SELECT-only, whitelisted tables/views, mandatory `LIMIT`, no DDL/DML/`;`-stacking) → executed on
  a **read-only, tenant-scoped session** (reuse `app_rw` + RLS GUC) with a statement timeout → rows
  returned → Ollama narrates **strictly from the returned rows**. On failure/low confidence:
  clarify or fall back to the existing rule-based responder (`get_intelligent_fallback`).
- Reuse the provider chain (`services/llm/`, `OllamaProvider`) + existing `/chat` `/chat/stream` routes.
- Add an **`ollama`** service to `docker-compose.yml`; config `OLLAMA_URL` / `OLLAMA_MODEL`.
- Tests: golden NL→SQL pairs; injection/guard tests (DDL/DML/cross-tenant rejected).

## Phase 3 — Diagnostic intelligence + BullMQ worker ❌
Goal: a **system of diagnosis** that proactively finds problems, explains them, and recommends action.
- **Node BullMQ worker** (new `worker/`, added to compose) on the existing Redis. Scheduled jobs
  scan for: sales/margin drops, stockout risk, return spikes, forecast-vs-actual drift, anomalies —
  writing explainable **findings** rows (new migration) that the dashboard + Sage read.
- **Deterministic, explainable rules engine** (no paid ML), augmented by the existing forecasting
  engine for anticipation.
- **Insights/Diagnostics feed** (new frontend panel); findings are queryable by Sage.

## Phase 4 — Agentic layer (last, incremental) ❌
Goal: turn recommendations into proposed actions, slowly increasing autonomy.
- Findings → proposed actions reusing the procure-to-pay action layer (draft PO/alert),
  **human-approved** first; expand autonomy gradually. Explicitly deferred / slow.

---

## Deferred (needs external services / a decision)
- **Billing** — Stripe/Telr subscriptions + metering (maps onto `tenants.plan` + API-key metering).
- **Payments / B2B AP** — partner for money movement; never build KYC/AML/licensing.
- **Notifications** — WhatsApp/Slack/email (Twilio/Resend/Slack).
- **E-signature** — DocuSign / Dropbox Sign.
- **Enterprise infra** — Temporal/Camunda, WorkOS SSO/SAML/SCIM, PostHog+Sentry, Typesense/Meili,
  DuckDB/ClickHouse+dbt, Mapbox, embedded payments.
- **FORCE-RLS request-path enablement** — role + DB enforcement shipped & proven; flip
  `USE_RLS_ROLE=true` after the GUC-after-auth + cross-tenant public-API-key-lookup follow-ups
  (these also unblock Phase 2's read-only NL→SQL execution role).

## Run / deploy notes
- Dev: `docker compose up -d` (postgres :5432, redis :6379, backend :8000, frontend :3000).
- **Rebuild after dependency or backend changes**: `docker compose up -d --build backend`.
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in `schema_migrations`).
- Demo logins (password `Demo@2026!`): `atharva@retaildemo.app` (super_admin),
  `krishna@retaildemo.app` (regional_manager), `yash@retaildemo.app` (store_manager).
