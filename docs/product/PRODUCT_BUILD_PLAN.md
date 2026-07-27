# Product Build Plan — MVP → SaaS → PaaS

> **Purpose.** The single reference for turning Retail IQ from a strong working system into a
> *real product you can sell.* It reconciles the engineering roadmap (`../../implementation.md`,
> Phases 0–4) with the commercial reality (`SAAS_PATH.md`, parts of which are now stale —
> multi-tenancy, RLS, ingestion, and self-serve signup have **shipped**). Read this as the
> current source of truth for sequencing; the older docs are context.
>
> **North star:** *Accuracy is the product.* Every number a panel, Sage, or a finding shows must
> be derivable and correct. VOLUME in **units**, VALUE in **AED**, never mixed on one axis
> (reference: `backend/app/routes/kpis.py`).

---

## 0. Honest current state (verified June 2026)

What's **real and running today** (booted & health-checked from this branch):

- Live pipeline (generator → Redis pub/sub → SSE), 913k seeded rows, units/AED separated in KPIs.
- JWT auth + region→store RBAC; **multi-tenancy + Postgres RLS shipped** (migrations 010–022),
  FORCE-RLS opt-in via `USE_RLS_ROLE` (currently **off**).
- Self-serve signup + tenant provisioning; per-tenant public API + `lsk_` API keys + webhooks (PaaS bones).
- Procure-to-pay system of record (POs, goods receipts, supplier invoices, approval rules).
- Forecasting engine + Forecast Lab; an `ai_assistant` (intent-match + rule-based fallback) with an
  Ollama/OpenAI provider chain coded; voice (Deepgram) endpoints.

What's **not real yet** (the gap to a sellable product):

1. **Accuracy isn't enforced** — dual price source, a mislabeled `total_sales:int` that holds AED,
   no guard/golden tests. (`implementation.md` Phase 1)
2. **No grounded NL answers** — the chatbot stuffs intents; can't answer arbitrary questions without
   hallucinating. (Phase 2 — Sage)
3. **No proactive diagnosis** — the system shows *what happened*, not *what's going wrong & why*.
   (Phase 3 — diagnostics + BullMQ)
4. **No agency** — it can't propose actions off its findings. (Phase 4)
5. **No commerce/ops** — no billing/metering, no notifications, no observability (Sentry/PostHog),
   thin legal/compliance + backup/residency story. (Commercial & Trust track below)

Points 1–4 are the **product engine**. Point 5 is what makes it a **business**. This plan runs both
tracks, engine first.

---

## Track A — The intelligence engine (do in order)

### A1. Accuracy hardening — *foundation, do first* ❌
**Goal:** every output provably correct; make "accuracy is the product" enforceable in CI.
- Collapse the **dual price source**: `data_sync.CATEGORY_COSTS` (used by `promotions.py`) vs
  `items.unit_price_aed` (used by `kpis`/`analytics`) → one source (`unit_price_aed`); demote the
  dict to a seed-only fallback or delete.
- Fix **mislabeled types**: `analytics.py` `total_sales:int` actually holds `SUM(sales*unit_price_aed)`
  (AED float) → rename `total_revenue`, retype. Audit `admin.py` for the same alias.
- **Guard tests**: assert revenue endpoints derive AED via the price join; assert KPI volume fields
  are integer units; flag `formatCurrency` bound to a unit field.
- **Golden-number tests**: pin known seed totals (e.g. `total_revenue_week ≈ AED 3.05M`,
  `total_sales_week ≈ 155,461 units`) so any aggregation regression fails CI. These double as the
  **oracle for validating Sage** (A2) and the **diagnostics math** (A3).
- **CI smoke test** (Phase 0 leftover): `docker compose up` → `/health` + one authed `/api/kpis`.
- **Compose hygiene** (Phase 0): the hardcoded `container_name: sales_db/redis/...` collide across
  sibling checkouts (hit this on boot). Parameterize via `COMPOSE_PROJECT_NAME`/`${...}` or drop the
  fixed names so parallel project dirs don't fight over container names.

*Acceptance:* a deliberately broken aggregation fails CI; one price source in the codebase.

### A2. Sage — NL→SQL diagnostic chatbot on Ollama ❌
**Goal:** answer arbitrary business questions accurately, **zero hallucination**.
- **Rename** chatbot → **Sage** everywhere; add `CHATBOT_NAME` to `brand.ts`.
- **Pipeline** (`backend/app/services/nl2sql/`): curated **semantic view layer** (not raw 50-table
  schema — expose `sales_fact_view`, items, stores, curated aggregates; encode the units/AED
  convention here) + few-shots → Ollama emits one `SELECT` → **allow-list guard** (single statement,
  SELECT-only, whitelisted tables/views, mandatory `LIMIT`, no DDL/DML, no `;`-stacking, no comments)
  → execute on a **read-only, tenant-scoped session with a statement timeout** → **narrate strictly
  from returned rows** (templated: "answer ONLY from these rows; else say you don't know"; cite row
  count + SQL). On low confidence: clarify or fall back to `get_intelligent_fallback`.
- **Reuse** `services/llm/` provider chain so Sage runs on local Ollama **or** a hosted key via one
  env switch (key to be provided later).
- **Compose:** add an `ollama` service; config `OLLAMA_URL`/`OLLAMA_MODEL`.
- **The RLS trigger (decided): flip `USE_RLS_ROLE=true` for Sage's read path.** Model-generated SQL
  cannot be trusted to app-layer scoping, so it must run as the non-owner `app_rw` role under FORCE
  RLS. This forces the two deferred follow-ups (GUC-after-auth, cross-tenant key lookup) — finishing
  them here also hardens the whole authenticated request path, not just Sage.
- **Tests:** golden NL→SQL pairs (reuse A1 numbers); injection/guard tests (DDL/DML/cross-tenant
  rejected at the SQL layer, not just the filter).

*Acceptance:* "revenue by store last week" returns A1's golden number; a cross-tenant or `DROP`
attempt is rejected and returns 0 rows / a refusal.

### A3. Diagnostic intelligence + BullMQ worker ❌
**Goal:** a system of *diagnosis* — proactively find problems, explain them, recommend.
- **Node `worker/`** (new service in compose) on the existing Redis via **BullMQ**. Own Dockerfile,
  read-only-ish DB access. Scheduled jobs scan for: sales/margin drops, stockout risk, return spikes,
  **forecast-vs-actual drift** (cheap, high-signal — diff the existing forecast vs `sales_fact_view`),
  anomalies.
- **Findings as first-class explainable rows** (new migration): rule id, evidence (the numbers),
  severity, tenant_id, a human sentence, dedupe key. Deterministic rules (no paid ML) so every
  finding is explainable. **Contract lives in SQL (the migration)**, shared by Python + Node.
- **Integration wins:** (a) Sage can query the findings table ("why did margin drop in Khalidiyah?");
  (b) findings reuse Sage's grounded-narration module; (c) decide up front whether findings *feed*
  `alert_service` or are a parallel stream — avoid double-notification noise.
- **Insights/Diagnostics frontend panel** (new screen).

*Acceptance:* a seeded margin drop produces a finding with its evidence; Sage can answer "what's
wrong this week?" by reading findings.

### A4. Agentic layer — *last, deliberately slow* ❌
**Goal:** findings → **proposed** actions, autonomy increasing gradually.
- Findings → draft PO / draft alert, reusing the existing procure-to-pay action layer +
  `approval_rules` as the human gate. Start at autonomy level 0 (suggest-only). Expand slowly.

---

## Track B — The commercial & trust layer (parallel; gates real customers)

Runs alongside Track A. Most "SaaS" infra already exists; these are the genuine remaining gaps.

### B1. Observability & ops (do early — you can't run a SaaS blind)
- Error tracking (Sentry) + product analytics (PostHog) — both deferred today.
- Per-tenant health/freshness already partly present (data_sources); surface uptime + a status page.
- Backups + restore drill; structured logs already exist (request_id) — ship log shipping.

### B2. Billing & metering (makes it a business)
- Model plans on the existing `tenants.plan` + API-key metering primitives.
- Stripe Billing + Customer Portal (or UAE gateway: Telr / PayTabs / Network Intl). Even if selling
  manually first, model tiers in schema now. Soft caps + upgrade prompts, not hard failures.

### B3. Notifications (Twilio/Resend/Slack)
- Findings (A3) and alerts are the natural triggers. Deferred today; needed for a real ops loop.

### B4. Ingestion polish (PaaS surface)
- The connector/adapter registry + mapping UI exist (`data_sources`, `source_adapters`). Finish:
  idempotent dedup on ingest (use `sales_stream_raw.event_id`), per-tenant freshness/error surface,
  CSV/Excel upload + scheduled DB pull as first-class onboarding.

### B5. Trust, compliance & legal (gates the first real data)
- Tenant isolation proof test (pairs with the A2 RLS flip).
- Data residency: UAE PDPL — region-capable host before real customer data.
- ToS / Privacy / DPA; tenant export + delete-on-request (offboarding).
- `SECURITY.md`; auth hardening (token storage path, refresh rotation, CSP tightening).

### B6. Brand/legal (cheap, do once)
- Product name is a placeholder (`settings.product_name` + `brand.ts`). Pick an ownable,
  trademark-clear brand before go-to-market. "Lulu" must not be used as borrowed branding.

---

## Sequencing & milestones

```
Engine:   A1 ─► A2 (Sage + RLS flip) ─► A3 (diagnostics+BullMQ) ─► A4 (agentic, slow)
Commerce:  B1 (observability) ──┐
                                ├─ run in parallel, B2/B3 lag A3 (need findings to be worth billing/notifying on)
           B4 (ingestion) ──────┘
Trust:     B5/B6 before any real customer data touches it
```

- **Milestone 1 — "provably correct"**: A1 done; CI green with golden tests.
- **Milestone 2 — "ask it anything"**: A2 Sage live, RLS flipped, isolation proven. *Flagship demo.*
- **Milestone 3 — "it tells you what's wrong"**: A3 diagnostics + Insights panel + B1 observability.
- **Milestone 4 — "sellable"**: B2 billing + B5 trust + B6 brand. First paid tenant possible.
- **Milestone 5 — "acts for you"**: A4 agentic, human-approved.

**Build the shared pieces once, early:** the *semantic view layer* and the *grounded-narration
module* are used by both Sage (A2) and diagnostics (A3). Don't build them twice.

---

## Cross-cutting decisions (locked)

- **RLS:** flip `USE_RLS_ROLE=true`, driven by Sage's untrusted SQL (see A2).
- **No paid services in the prototype:** local Ollama, BullMQ on existing Redis, deterministic rules.
  Stripe/hosted-LLM/Temporal/WorkOS stay deferred until go-to-market.
- **Findings contract in SQL**, not code (shared Python ↔ Node).
- **One price source** (`items.unit_price_aed`).

---

## Top risks / traps

- **Sage hallucination** → mitigated by guard + strict row-grounded narration + golden evals; the LLM
  may be wrong, the guard + RLS must not be.
- **Two-runtime repo** (Python + Node worker) → keep the contract in SQL; worker gets its own Dockerfile.
- **Findings ↔ alerts double-noise** → decide the relationship before shipping A3.
- **Compose container-name collisions** across sibling checkouts → fix in A1.
- **Stale local pytest** (`httpx≥0.28` breaks TestClient) → run in container or pinned venv.
```
