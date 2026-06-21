# Foresia — Implementation Plan

**Foresia** is an anticipatory retail-intelligence SaaS (B2B / B2G). It tells you what's going
right *and* what's going wrong across stores, inventory, and procurement — and its AI assistant,
**Sage**, answers any business question in natural language by querying the live database.

This is the forward plan. Completed foundation work lives in git history and the "Done so far"
summary below. Strategy/product rationale lives in `docs/` (PRODUCT_STRATEGY, SAAS_PATH, ADR).

## Status legend
✅ done · 🟡 in progress · ❌ not started · ⏭️ deferred

---

## Evolution phases (current effort)

> Target architecture: FastAPI (API/SSE) + **Node BullMQ worker** (durable jobs) + Postgres 15
> (RLS multi-tenancy) + Redis 7 (queues, pub/sub, cache) + Next.js 14 + Ollama (local LLM;
> OpenAI later via the existing provider chain). FastAPI enqueues jobs via the `bullmq` Python
> client; the Node worker processes them.

### Phase 0 — Rebrand to Foresia + dead-code purge ✅
- Product renamed **Retail IQ → Foresia** from the single source of truth (`settings.product_name`
  / `PRODUCT_NAME`, `frontend/src/lib/brand.ts` / `NEXT_PUBLIC_PRODUCT_NAME`) and across docs,
  compose, manifest, nginx, render. AI assistant named **Sage**. Demo tenant stays "Meridian".
- Removed stale archive planning docs (architecture plan, codebase map, redesign brief); kept the
  original audit (`GAP_ANALYSIS.md`). Verified the codebase is otherwise lean (no orphaned modules).

### Phase 1 — BullMQ worker service ✅
- New `worker/` Node 20 + TypeScript service (BullMQ + ioredis + pg), containerized + health-checked,
  sharing Redis. Queues: `webhook` (live), `risk-scan` (Phase 3), `report`/`digest` (scaffold).
- `backend/app/services/queue.py` — `bullmq` PyPI producer (pinned 2.14.x for redis<6 compat).
  `USE_QUEUE` flag (default true) with the in-process path as fallback.
- **Webhook delivery migrated** to the queue: `dispatch_event_background` enqueues a `dispatch`
  job → worker fans out one `deliver` job per subscribed endpoint → signed POST with per-endpoint
  exponential-backoff retries; HMAC signing/payload byte-identical to the Python implementation
  (cross-language signature verified). Proven end-to-end (Python producer → Node consumer → 200).
- **Forecast training stays in Python** (in-process trainer): the heavy ML (lightgbm/torch) is
  Python-bound, so the queue owns I/O-bound work (webhooks now, risk scans next) — the correct split.

### Phase 2 — Sage: true NL→SQL agent (Ollama) ✅
- `services/sage/`: curated tenant-safe **schema_catalog**, a hard **validator** (SELECT-only,
  single statement, allow-listed relations + CTE names, no system catalogs / write funcs / GUC
  tampering, LIMIT enforced), and an **executor** that runs the SELECT as the non-owner `app_rw`
  role in a READ ONLY transaction with the `app.tenant_id` GUC — so Postgres RLS scopes rows and
  rejects writes. Defense-in-depth, no fragile predicate injection.
- `nl2sql` orchestrates generate → validate → execute and infers a chart spec. `ai_assistant`
  uses it as the **primary data path**, falling back to the keyword-intent responder, then a
  general LLM answer. Wired into `/api/ai/chat` (+ structured `sage` in the done-event) and
  `/api/public/v1/ai/ask`. Frontend `ChatBot` renders the answer + collapsible SQL + result table;
  assistant rebranded to **Sage**.
- **Security fix found & fixed:** `init.sql` recreates `sales_fact_view` on every boot and was
  clearing `security_invoker` (set once by migration 021), so app_rw/RLS reads leaked across
  tenants through the view. Baked `WITH (security_invoker = true)` into the view definition
  (init.sql + migration 011). Verified: tenant 1 → 914,012 rows, tenant 2 → 1,920.
- Tested: 33 validator/helper unit tests + full suite **185 passing**; live NL→SQL verified with a
  local Ollama model (`qwen2.5:1.5b`) end-to-end (question → SQL → rows → narrated answer).

### Phase 3 — Proactive intelligence / Risk Radar ✅
- `services/intelligence/risk_scans.py`: four data-grounded detectors — **stockout risk**
  (forecast-driven, reuses `reorder_suggestions`), **demand drop** (7d vs prior-3wk per store),
  **return spike**, **dead stock** — severity-scored + deduped (`make_dedupe_key`), upserted into
  `risk_findings` (migration 023, RLS + FORCE). Stale findings auto-resolve; new high-severity
  emit `alerts:stream` SSE + signed webhooks (reusing the Phase 1 queue).
- The Node **BullMQ worker owns durable scheduling**: a repeatable `risk-scan` job triggers the
  Python all-tenant scan via an internal token-guarded endpoint (compute stays in Python).
- `GET /api/intelligence/risks` (tenant-scoped, ranked) + `POST /scan` (super_admin) +
  `/scan/internal` (worker). Dashboard **Risk Radar** card; Sage answers "what's going wrong?"
  from the findings.
- Verified live: scan produced 30 (t1) / 20 (t2) findings, tenant-isolated; worker repeatable job
  completed against the backend; +4 tests (full suite **189 passing**).

### Phase 4 — B2B/B2G hardening + polish ❌
- Finish FORCE-RLS request path (set `app.tenant_id` GUC after auth; special-case public-API key
  lookup; run `USE_RLS_ROLE=true`). CI smoke test + full pytest + `tsc` gate. Final dead-code
  sweep + docs (README/DEMO/ADR) refreshed for Foresia/queue/Sage.

---

## Done so far (foundation — shipped & verified live in Docker)

- **Part I — Recovery → MVP → polish:** auth/RBAC, AED revenue model (units vs currency), 3-tier
  sales unification (`sales_fact_view`), UI/UX redesign + a11y/RTL, production hardening, docs.
- **Part II — Live SaaS + ML/DL:** multi-tenancy (tenant-scoped reads + caches), Postgres RLS
  (FORCE RLS + non-owner `app_rw` role), deterministic backtest-selected forecasting engine +
  **Forecast Lab** (ML/DL tiers: LightGBM, LSTM, N-BEATS, TCN, Transformer; ROC/PR, threshold
  tuning, accuracy-over-time, store×category heatmap).
- **B1.7** — forecasts wired across the product (revenue projection, inventory reorder, promo
  uplift, AI answers).
- **B3** — self-serve onboarding (signup → isolated tenant + sample data + auto-login, invites,
  checklist). Billing deferred.
- **B4** — PaaS: per-tenant API keys, public REST API, embeddable AI, white-label branding,
  HMAC-signed webhooks on real domain events, in-app developer portal.
- **B5** — embeddable, tenant-scoped AI (Ollama → rule-based fallback, zero paid keys).
- **Part III-E** — procure-to-pay system of record: forecast → grouped MOQ draft PO →
  auto/manual approval → send → goods receipt → supplier invoice → 3-way match.
- **Part III-H** — PO PDF, approval inbox, dashboard action cards, Cmd-K palette, audit timeline,
  PWA installable offline shell.

---

## Deferred (needs external services or a go-to-market decision)
- **Billing** — Stripe/Telr subscriptions + metering. Maps onto `tenants.plan` + API-key metering.
- **Payments / B2B AP** — partner for money movement; never build KYC/AML/licensing.
- **Notifications** — WhatsApp/Slack/email (Twilio/Resend/Slack). Reuse `dispatch_event`.
- **E-signature** — DocuSign / Dropbox Sign.
- **Enterprise infra** — Temporal/Camunda, WorkOS SSO/SAML/SCIM, PostHog+Sentry,
  Typesense/Meili, DuckDB/ClickHouse+dbt, Mapbox, embedded payments.
- **OpenAI** — wired via the provider chain; stays disabled (Ollama-first) until a key is set.

## Run / deploy
- Dev: `docker compose up -d --build` (frontend :3000, backend :8000/docs, Postgres :5432,
  Redis :6379, worker). Migrations auto-apply on boot.
- Demo logins (password `Demo@2026!`): atharva@retaildemo.app (super_admin),
  krishna@retaildemo.app (regional_manager), yash@retaildemo.app (store_manager).
