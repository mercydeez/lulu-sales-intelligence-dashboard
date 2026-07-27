# Project Structure

Architecture, subsystem map, dependency graph, and the ownership overlay. Pairs with
`TEAM_OWNERSHIP.md` (who owns what) and `docs/architecture/ADR.md` (why it's built
this way).

## Scale (July 2026)

- **Backend:** 35 route modules, ~60 service modules, 49 backend test files.
- **Database:** 49 numbered SQL migrations + `init.sql` baseline (no Alembic yet).
- **Frontend:** 34 App-Router pages, a `components/ui` design system, thin `'use
  client'` page composers.
- **Worker:** a Node BullMQ diagnostics service (`worker/`).

## Stack & runtime

FastAPI (async SQLAlchemy 2 + asyncpg, Python 3.11) · PostgreSQL 15 · Redis 7 ·
Next.js 14 App Router (TS/Tailwind/Recharts) · Node BullMQ worker · Docker Compose
(NGINX only in `docker-compose.production.yml`).

**Core = live-data pipeline.** A `DataGenerator` asyncio task writes a synthetic sale
every ~5–15s to Postgres and publishes JSON to Redis channels (`sales:stream`,
`alerts:stream`, `inventory:stream`); SSE endpoints under `/stream/*` relay pub/sub to
the browser via `EventSource` (authenticated with short-lived stream tickets).

**Sales source of truth** (ADR-001): `sales_historical` (immutable CSV) +
`sales_stream_raw` (append-only live) unified by `sales_fact_view`. All readers query
the view. Revenue is **derived** as `SUM(units × unit_price_aed)` — see the units/AED
discipline below.

## Repository layout

```
backend/app/
  main.py            # app assembly, lifespan/background tasks, health, middleware order
  config.py          # pydantic-settings; every feature flag/env var
  middleware.py      # 6 middleware classes (order set in main.py)
  models/            # SQLAlchemy Base + ORM models
  routes/
    registry.py      # ← central router list (add endpoints HERE, not main.py)
    <domain>.py      # 35 route modules
  services/          # ~60 service modules (see subsystem map)
    llm/ nl2sql/ sage2/ sage3/ rag/ federation/   # the AI/Sage stack
    forecasting/                                    # the forecasting engine
  commands/          # one-shot CLIs (seed, migrate, generator, cache_warmer)
  tests/             # 49 test files

frontend/src/
  app/               # 34 pages (each a 'use client' composer) + layout.tsx, globals.css
  components/
    ui/              # design system (primitives, StatCard, ChartFrame, motion…)
    shell/           # AppShell, Sidebar, Topbar
    <feature>/       # analytics, inventory, admin, alerts, charts, …
  config/
    nav.tsx          # ← central nav list + icon map (add pages HERE, not Sidebar)
  contexts/          # Auth, Language (i18n), Experience (Role Experience Engine)
  hooks/useEventStream.ts   # centralized SSE (one connection per channel)
  lib/               # api.ts (facade) / apiClient.ts (engine), formatters, chart, brand…
  types/             # domain type barrel

worker/src/          # Node BullMQ diagnostics: scan → findings → measure → outcome
database/
  init.sql           # fresh-volume baseline (CSV bulk load + demo users)
  migrations/        # 001..049 numbered SQL, auto-applied on boot / via commands.migrate
docs/                # architecture, product, production, runbooks, security, legal
.github/
  workflows/ci.yml   # backend tests · frontend build · docker · smoke · migrations · backup · security
  CODEOWNERS         # path → reviewer routing
```

## Subsystem map (with primary owner)

| Subsystem | Key modules | Owner |
|---|---|---|
| **AI / Sage** | `services/{ai_assistant,llm/*,nl2sql/*,sage2/*,sage3/*,rag/*,federation/*,voice_service}`, `routes/{ai,search}` | Atharva |
| **Decision engine** | `services/{decision_center,action_drafting}`, `routes/decisions` | Atharva |
| **Executive briefing** | `services/briefing`, `routes/briefing` | Atharva |
| **Role / Experience engine** | `services/role_experience`, `routes/experience`; frontend `contexts/ExperienceContext` (rendering → Yash) | Atharva |
| **ROI / Value** | `services/roi`, `routes/roi` | Atharva |
| **Diagnostics (worker)** | `worker/src/*`, `routes/findings` | Atharva |
| **Forecasting engine** | `services/{predictor,forecast_service,forecast_trainer,forecasting/*}` | Krishna |
| **Sales / KPIs / analytics** | `routes/{sales,history,kpis,analytics,reports}` | Krishna |
| **Inventory / procurement / alerts / promotions** | `services/{procurement_service,alert_service,data_sync}`, matching routes | Krishna |
| **Auth / security / tenancy** | `services/{auth_service,totp,token_store,tenant_*,api_key_service,security_events,data_rights_service,plan_limits,usage_metering}`, `routes/{auth,admin,tenants,security,data_rights,team,api_keys}` | Krishna |
| **Integrations / billing** | `services/{billing,outcome_pricing,einvoicing,webhook_service,csv_import,data_sources,source_adapters,uae_*,notifications}` | Krishna |
| **Platform / data plane** | `services/{database,redis_client,cache,cache_warmer,migration_runner,metrics}`, `main.py`, `config.py`, `middleware.py`, migrations, CI | Krishna |
| **Live pipeline / SSE** | `services/{data_generator,redis_client}`, `routes/stream`, frontend `hooks/useEventStream` | Krishna (backend) / Yash (client) |
| **Design system & shell** | `components/ui/*`, `components/shell/*`, `config/nav.tsx` | Yash |
| **Frontend platform** | `app/layout.tsx`, `globals.css`, `lib/*`, `types/*`, `contexts/*` (client) | Yash |
| **Feature pages** | most `app/*/page.tsx` + `components/<feature>/*` | Yash (AI pages → Atharva) |

## Dependency graph (internal edges)

**Leaf / near-leaf** (safe to own & change independently — few/no internal dependents):
`roi.py`, `role_experience.py`, `uae_intelligence.py`/`uae_profile.py`, `predictor.py`,
`csv_import.py`, `outcome_pricing.py`, `einvoicing.py`, `notifications.py`,
`webhook_service.py`, `token_store.py`, `totp.py`, and **`database/migrations/050+.sql`**
(additive — near-zero conflict).

**Mid-tier** (own a subsystem; depend on a couple of leaves):
- `forecast_service` → `cache`, `data_sync`, `predictor`
- `procurement_service` → `forecast_service`, `webhook_service`
- `decision_center` → `forecast_service`
- `briefing` → `roi`, `forecast_service`, `uae_intelligence` *(aggregator across 3)*
- `alert_service` → `data_sync`, `redis_client`
- `billing` → `plan_limits`, `usage_metering`
- `federation/orchestrator`, `sage2/orchestrator` → `llm`, `nl2sql/*`

**Hubs** (many dependents — stable-contract, review-gated):
`database.py`, `redis_client.py`, `auth_service.py`, `security_events.py`, `cache.py`,
`data_sync.py`, `llm/*`, `nl2sql/*` (backend); `components/ui/index.ts`, `apiClient.ts`,
`Auth`/`Experience` contexts, `config/nav.tsx`, `LanguageContext.tsx`, `types/index.ts`
(frontend).

**Cross-layer edges to watch:**
- `cache_warmer.py` & `forecast_trainer.py` import from `services/kpi_service.py` &
  `services/forecast_lab.py` (the compute layer extracted from the kpis/analytics routes
  in July 2026 — services no longer import route modules; guarded by
  `tests/test_dependency_direction.py`).
- `briefing` (Atharva) depends on `roi` + `forecast_service` + `uae_intelligence`.
- Frontend `Sidebar` renders the server `role_experience` nav manifest — the config is
  Atharva's, the rendering is Yash's; the manifest shape is the shared contract.

## How to extend (without touching hubs)

- **Add a backend endpoint:** create/extend a `routes/<domain>.py`, then append one
  tuple to `backend/app/routes/registry.py`. `main.py` does not change.
- **Add a frontend page:** create `app/<route>/page.tsx`, then append one entry to
  `frontend/src/config/nav.tsx` and the matching `tKey` to `LanguageContext` (en+ar).
  `Sidebar.tsx` does not change.
- **Add a DB change:** add `database/migrations/<next>_<owner>_<topic>.sql` (never edit
  an existing migration). See the migration-numbering rule in `GIT_WORKFLOW.md`.
- **Add a background task:** register it in `main.py`'s lifespan behind a config flag
  (rare — coordinate with Krishna).

## Non-negotiable conventions

- **Units vs AED (ADR-002):** raw `sales` are **units**; AED is derived
  (`SUM(units × unit_price_aed)`). VOLUME in units, VALUE in AED, **never mixed on one
  axis**. `services/kpi_service.py` is the reference implementation (re-exported by `routes/kpis.py`).
- **Only build UI the backend supports** (ADR-007/008). No mock-backed surfaces in prod.
- **Migrations are additive & idempotent** (ADR-005). No down-migrations.
- **Middleware order** (main.py): SecurityHeaders → CSRF → BodySizeLimit →
  SessionInvalidation → RateLimit → RequestID → CORS.
