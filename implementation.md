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
- ✅ **Compose hygiene** — `container_name:` now `${PROJECT_PREFIX:-sales}_*` so parallel checkouts
  don't collide (the failure hit booting a second dir). Default keeps `sales_*` for existing scripts.
- ✅ **Smoke check in CI** — new `smoke` job in `.github/workflows/ci.yml`: `docker compose up --build`
  → poll `/health` → assert db+redis healthy → run the golden-number tests against the live stack.

## Phase 1 — Accuracy hardening ("tighten the screws") ✅ (mostly)
Goal: every insight/output is provably correct. Builds on the shipped units/AED separation.
- ✅ **Automated guards** — `backend/tests/test_accuracy_guards.py` (DB-free, in the unit suite):
  asserts analytics exposes no AED-bearing `total_sales` key, revenue derives via `unit_price_aed`,
  KPI volume fields are `int` & revenue fields `float`, a SINGLE `CATEGORY_COSTS` definition, and
  (frontend scan) `formatCurrency` is never bound to a units field.
- ✅ **Golden-number tests** — `backend/tests/test_golden_numbers.py` (integration; auto-skips if API
  down; runs in CI smoke): pins seed shape (913k rows / 10 stores / 50 items), asserts volume=int,
  revenue=float, and revenue/units sits in the seeded AED price band (catches units-as-AED regressions).
- ✅ **Rename the AED `total_sales` alias** → `total_revenue` in `analytics.py` (+ Pydantic models)
  and `admin.py` (`total_sales_30d`→`total_revenue_30d`); frontend types + 6 consumers updated, `tsc` clean.
- ✅ **Unify the price source** — `data_sync.CATEGORY_COSTS` is now DERIVED from `items.unit_price_aed`
  at startup (`refresh_category_costs()` in the lifespan); the hardcoded dict is only a cold-start
  fallback. promotions/procurement/inventory can no longer drift from the analytics revenue math.
- ❌ **Remaining smell** — per-tenant store names in `ai_assistant` (no hardcoded list); folded into
  Phase 2 (Sage rewrite supersedes the intent-stuffing assistant).

## Phase 2 — "Sage": NL→SQL diagnostic chatbot on Ollama ✅ (engine; LLM drops in last)
**Built & verified (provider-agnostic — works with zero LLM via rule-based fallback):**
- ✅ **Semantic layer** (`database/migrations/023_sage_semantic_views.sql`): seven curated
  `sage_*` views, each tenant-filtered by `WHERE tenant_id = current_tenant_id()` so isolation
  is baked into the view SQL (independent of RLS-through-view). Encodes units vs revenue_aed.
- ✅ **Least-privilege role** `sage_ro`: SELECT on the `sage_*` views ONLY (verified it CANNOT read
  `users`). Sage's executor connects as `sage_ro` + sets the `app.tenant_id` GUC + statement timeout.
  Verified tenant isolation end-to-end (tenant 1: 913k rows, tenant 2: 1.9k).
- ✅ **`services/nl2sql/`**: `schema.py` (allow-list + prompt), `guard.py` (single SELECT, no
  comments/`;`/DDL/DML, no pg_*/set_config/catalog, allow-list relations, hard LIMIT wrap),
  `executor.py` (sage_ro read-only), `prompt.py`, `pipeline.py` (NL→SQL→guard→exec→narrate, with a
  deterministic rows-only narration fallback). Fails closed at every step → rule-based fallback.
- ✅ **Integrated** into `ai_assistant.get_chat_response`/`stream_chat_response` (Sage first, then the
  existing path). **Renamed** chatbot → **Sage** (`settings.chatbot_name`, `brand.ts CHATBOT_NAME`,
  ChatBot/AIToggleButton, prompts/fallbacks).
- ✅ **Ollama** service added to `docker-compose.yml` (profile `ai`); `OLLAMA_URL` empty by default.
- ✅ **Tests**: `test_nl2sql_guard.py` (29, DB-free — injection/DDL/cross-table/GUC-tamper all
  rejected) + `test_nl2sql_pipeline.py` (5, integration — cross-table blocked, tenant isolation),
  wired into CI smoke.
- ⏳ **Last step (you):** add the LLM — set `OLLAMA_URL`/pull a model, or set `OPENAI_API_KEY`. The
  provider chain (`services/llm/`) picks it up; no code change. Until then Sage uses the fallback.

> **RLS gap found (Track B follow-up):** migration 021's `security_invoker` is NOT in effect on
> `sales_fact_view` (likely recreated after; an `ALTER VIEW` also blocks behind the live generator's
> read load). So app_rw querying that view bypasses RLS (runs as the superuser owner). Sage sidesteps
> this entirely (dedicated `sage_*` definer views with a baked tenant filter), but the app-wide
> `USE_RLS_ROLE` flip still needs this fixed first. Tracked for Track B / Phase 2 hardening.

## Phase 2 — (original notes) ❌
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
