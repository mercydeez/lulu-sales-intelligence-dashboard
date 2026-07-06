# Team Ownership

How three developers — **Atharva, Krishna, Yash** — own this codebase so they can
work in parallel with near-zero merge conflicts. Ownership is by **bounded context
and architectural module**, not by page.

> **Machine-enforced companion:** `.github/CODEOWNERS` maps these paths to GitHub
> reviewers so the right owner is auto-requested on every PR. This document is the
> human-readable rationale; CODEOWNERS is the source of truth for review routing.

## Ownership principles

1. **One primary owner per module.** Others may contribute, but the owner reviews
   and is accountable for the module's design.
2. **Bounded-context beats layer where they overlap.** Krishna owns the backend and
   Yash owns the frontend *as layers*, but Atharva owns the **AI/Experience vertical**
   (specific files in *both* layers). Where a file is in Atharva's context, Atharva
   owns it even though it lives in `backend/` or `frontend/`.
3. **Contracts, not implementations, are shared.** When two owners meet at a seam
   (e.g. an API response shape), the *contract* is co-owned and changed via a small,
   fast PR; the implementations on either side stay private to their owner.
4. **Shared hubs are stewarded, not co-edited.** Hub files (below) have a steward;
   changes go through small dedicated PRs that land fast so others can rebase.

---

## Owner summary

| Person | Bounded context | Layer reality |
|---|---|---|
| **Atharva** | AI, Sage, Decision Engine, Executive Briefing, Role Experience, Product Experience/UX, Product Vision | Vertical — spans backend + frontend + worker |
| **Krishna** | Backend Services, APIs, Database, Business Logic, Auth, Security, Integrations, Performance | Horizontal — all backend not in Atharva's vertical |
| **Yash** | Frontend, Components, Design System, Charts, Responsive UI, Accessibility, Animations, Page Composition | Horizontal — all frontend not in Atharva's AI pages |

---

## Atharva — Intelligence & Experience vertical

**Backend services:** `ai_assistant.py`, `llm/*`, `nl2sql/*`, `sage2/*`, `sage3/*`,
`rag/*`, `federation/*`, `voice_service.py`, `decision_center.py`, `action_drafting.py`,
`briefing.py`, `role_experience.py`, `roi.py`

**Backend routes:** `ai.py`, `decisions.py`, `briefing.py`, `experience.py`,
`findings.py`, `search.py`, `roi.py`

**Worker (diagnostics engine):** all of `worker/src/*` — *coordinate `rules.js` math
with Krishna's E6-1 "metrics into SQL views" work.*

**Frontend pages:** `app/decisions`, `app/briefing`, `app/today`, `app/action-drafts`,
`app/insights`, `app/forecast-lab`, `app/value`

**Frontend components:** `ChatBot.tsx`, `AIProvider.tsx`, `AIToggleButton.tsx`,
`CommandPalette.tsx`

**Contract seams Atharva owns:** the backend `role_experience._CONFIGS` and the
`/api/experience` payload (the *experience config / product intent*). Yash owns its
client rendering. Atharva builds AI pages **using Yash's `components/ui` design
system**; Yash reviews those pages for visual consistency.

## Krishna — Platform, Data & Services

**Infra / data hubs:** `database.py`, `migration_runner.py`, `cache.py`,
`cache_warmer.py`, `data_sync.py`, `redis_client.py`, `metrics.py`, `middleware.py`,
`models/*`, `config.py`, `main.py` (steward)

**Auth / security / tenancy:** `auth_service.py`, `totp.py`, `token_store.py`,
`tenant_provisioning.py`, `tenant_lifecycle.py`, `api_key_service.py`,
`security_events.py`, `security_notify.py`, `data_rights_service.py`, `plan_limits.py`,
`usage_metering.py`

**Forecasting engine** (ML/stats business logic — distinct from LLM-AI):
`predictor.py`, `forecast_service.py`, `forecast_trainer.py`, `forecasting/*`

**Domain / integrations:** `procurement_service.py`, `alert_service.py`,
`notifications.py`, `webhook_service.py`, `billing.py`, `outcome_pricing.py`,
`einvoicing.py`, `csv_import.py`, `data_sources.py`, `source_adapters.py`,
`uae_intelligence.py` / `uae_profile.py`, `data_generator.py`, `db_seeder.py`,
employee services

**Backend routes:** all not owned by Atharva — sales, history, kpis, analytics,
inventory, promotions, alerts, admin, reports, monitoring, employees, data_sources,
tenants, billing, notifications, imports, outcome_pricing, team, uae_intelligence,
api_keys, webhooks, procurement, security, data_rights, public_api, stream

**Also owns:** `database/migrations/*` (schema steward/reviewer),
`.github/workflows/ci.yml`, `docker-compose*.yml`, Alembic adoption.

**Contract seams Krishna owns:** `routes/kpis.py` (the **units/AED reference impl**,
ADR-002) and the `forecast_service.py` public API (`revenue_projection`,
`reorder_suggestions`, `forecast_narrative`) that Atharva's decision/briefing layer
consumes.

## Yash — Frontend Platform & Experience Rendering

**Design system (gatekeeper):** `components/ui/*` + `ui/index.ts`, `motion.tsx`,
`PageTransition`

**App shell:** `components/shell/*` (AppShell, Sidebar, Topbar) + **`config/nav.tsx`**

**Charts & feature components:** `components/{charts,analytics,inventory,admin,alerts,
promotions,employees,monitoring,reports,home,settings}`

**Frontend platform:** `app/layout.tsx`, `globals.css`, `tailwind.config.js`,
`next.config.js`, `lib/{api,apiClient,chart,cn,formatters,csv,pdfExport,brand}`,
`types/index.ts`, `contexts/{LanguageContext,AuthContext,ExperienceContext}` (client)

**Pages (the bulk):** everything except Atharva's 7 AI pages — inventory, analytics,
admin(+tenants), procurement(+`po/[id]`), approvals, promotions, alerts, security,
audit, monitoring, employees, reports, settings/*, profile, auth pages, pricing /
outcome-pricing / trust, data-sources, imports, developers, root dashboard

**Cross-cutting:** responsive/mobile, accessibility, animations, dark mode.

**Contract seams Yash owns:** `contexts/AuthContext` (client; auth *contract* shared
with Krishna), `ExperienceContext` rendering (config *contract* shared with Atharva),
`LanguageContext` *mechanism* (every owner appends their own translation keys).

---

## Shared / high-conflict files — rules

These are imported or appended-to by everyone. After the router-registry and
nav-config refactors, the two worst hubs are gone; the rest have append rules.

| File | Steward | Rule |
|---|---|---|
| `backend/app/routes/registry.py` | Krishna | Append `(router, prefix, [tags])` **in your owner block**; never reorder others' lines. This replaces editing `main.py` per route. |
| `frontend/src/config/nav.tsx` | Yash | Append one `navItems` entry near related routes; add the matching `tKey` to both `en`/`ar`. Replaces editing `Sidebar.tsx` per page. |
| `backend/app/config.py` | Krishna | Append settings in an owner-bannered block. |
| `frontend/src/contexts/LanguageContext.tsx` | Yash | Append keys under your `namespace.*` prefix in **both** dicts. *(Split into per-domain locale files is a planned Yash workstream.)* |
| `frontend/src/types/index.ts` | Yash | Append a per-domain section. *(Split into per-domain modules is a planned Yash workstream.)* |
| `backend/app/services/{database,redis_client,security_events,cache,data_sync}.py`, `routes/auth.py` | Krishna | Stable internal API — change via small dedicated PR + owner review; land fast. |
| `backend/app/services/{ai_assistant,llm,nl2sql}.py/*` | Atharva | Stable AI hub — same rule. |
| `frontend/src/lib/{api,apiClient}.ts`, `components/ui/index.ts` | Yash | Add via small isolated PRs; Yash reviews. |
| `database/migrations/NNN_*.sql` | Krishna (review) | `git pull` first, claim `max(existing)+1`, name `NNN_<owner>_<topic>.sql`. Additive only — never edit a prior migration. Lowest-conflict area. |

---

## Workstreams (independent, parallel-safe)

Derived from `docs/EXECUTION_BLUEPRINT_12M.md`. Each is scoped to a disjoint file set
so all three run at once. Columns: **Owner · Effort · Blocked-by · Files · Deliverables
· Acceptance**.

### WS-A — Atharva · AI / Diagnostics / Experience
| Field | Detail |
|---|---|
| Effort | Large (multi-sprint) |
| Blocked by | Coordinate E3-5 rules math with Krishna's E6-1 (SQL views) |
| Files | `worker/src/*`, AI services (`ai_assistant`, `llm`, `nl2sql`, `sage*`, `rag`, `federation`, `decision_center`, `briefing`, `role_experience`, `action_drafting`), AI routes, AI frontend pages |
| Deliverables | E3-3 store-health score · E3-4 laggard peer benchmarking · E3-5 diagnostics rules 6–12 · E3-6 per-tenant thresholds · E7 Forecasting-v2 narrative / hosted-LLM Sage tier / root-cause decomposition / reorder-point suggestions · Role Experience Engine Waves 2–3 |
| Acceptance | New findings/decisions appear with grounded numbers; role configs drive homepage/nav/persona; tests green in `test_decision_center`, `test_role_experience`, `test_sage*`, worker `npm test` |

### WS-B — Krishna · Platform / DB / Integrations / Performance
| Field | Detail |
|---|---|
| Effort | Large (multi-sprint) |
| Blocked by | **E6-2 (Alembic) is foundational — do first** |
| Files | Infra/data/auth services, most routes, `database/migrations/*`, `config.py`, CI, compose |
| Deliverables | E6-1 metrics→SQL views (kill JS revenue math) · E6-2 adopt Alembic · E6-3 partition `sales_stream_raw` · E6-4 statement timeouts · E6-5 load test · E6-6 API versioning · E0-2..E0-8 ops net · E2 POS connector + cost/margin model · E8a payments · E5 SSO/security |
| Acceptance | Migrations idempotent (CI `migrations` job green); revenue math computed in SQL and matches `routes/kpis.py` golden numbers; load test meets budget |

### WS-C — Yash · Frontend / Design System / Accessibility
| Field | Detail |
|---|---|
| Effort | Large (multi-sprint) |
| Blocked by | Nav-config extraction (done); i18n split precedes full-Arabic work |
| Files | `components/*`, `lib/*`, contexts, most pages, `globals.css`, `tailwind.config.js` |
| Deliverables | E4 finish Track 6 across ~18 routes · restore dark mode · mobile store-manager `/today` (content with Atharva) · full Arabic on 5 core screens (drives i18n split) · kill client-side PDF · a11y in CI · design-system hardening · `types/index.ts` split |
| Acceptance | `tsc --noEmit` + `npm run build` green; a11y checks pass in CI; RTL verified on 5 screens; every route uses `components/ui` primitives |

---

## Reviewers at a glance

- **AI / Sage / decisions / briefing / experience / worker** → Atharva
- **Backend services / DB / auth / security / migrations / CI / infra** → Krishna
- **Frontend / components / design system / pages / charts / i18n** → Yash
- **A file in Atharva's context but in `backend/` or `frontend/`** → still Atharva.

See `GIT_WORKFLOW.md` for how PRs and reviews are run, and `PROJECT_STRUCTURE.md` for
the subsystem map and dependency graph.
