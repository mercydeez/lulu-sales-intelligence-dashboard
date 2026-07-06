# Development Contract

This is the **operating agreement** for the three developers who build this product with
AI assistance (Claude Code / Opus / Codex): **Atharva** (@mercydeez), **Krishna**
(@krish2105), and **Yash** (@Yashpetkar7). It codifies the shared principles, the
AI-coding discipline, the module boundaries, and the product philosophy that let us work
in parallel for months without stepping on each other or eroding product quality.

It is **not** new technical spec. Every rule here traces to an artifact already in the
repo — the ownership model, the ADRs, the execution and role blueprints. Where this
document and a machine-enforced rule disagree, **the machine wins**: `.github/CODEOWNERS`
is the source of truth for review routing, and the CI checks are the source of truth for
"done." This file is the human agreement that explains *why* those rules exist and how to
live by them day to day.

> **Read alongside:** `TEAM_OWNERSHIP.md` (who owns what), `PROJECT_STRUCTURE.md`
> (subsystem map + dependency graph), `GIT_WORKFLOW.md` (branching/PRs), `CONTRIBUTING.md`
> (run/test/build), `docs/architecture/ADR.md` (the *why*), `docs/EXECUTION_BLUEPRINT_12M.md`
> (the product spine), and `docs/product/ROLE_EXPERIENCE_BLUEPRINT.md` (the role model).

---

## 1. Engineering Principles

These are not generic best practices; each maps to a concrete convention already enforced
somewhere in this repo.

1. **One source of truth per fact.** A business fact is computed in exactly one place and
   read everywhere else.
   - Revenue is derived only via the SQL view / `backend/app/routes/kpis.py` (the
     reference implementation) — never recomputed in JS or in another reader.
   - Product/brand naming lives in `frontend/src/lib/brand.ts` and
     `settings.product_name`, not in scattered string literals.
   - Role behavior lives in `role_experience._CONFIGS` (one record per role), not in
     per-role branches across the codebase.

2. **Never duplicate business logic.** Prefer a SQL view over re-deriving numbers in the
   client (blueprint E6-1). If two panels need the same number, they call the same
   endpoint; they do not each do the arithmetic.

3. **Configuration over duplication — "one engine, twenty experiences."** Behavior that
   varies by role/tenant/market is *data*, not code. Adding a role means adding a config
   record to `_CONFIGS`, not adding screens or code paths
   (`docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`).

4. **Preserve workflow continuity.** Close the loop —
   *detect → diagnose → recommend → accept → measure → price-on-outcome*
   (`docs/EXECUTION_BLUEPRINT_12M.md`: "the loop is the company"). Don't decorate around a
   broken step; a feature that adds a chart but doesn't advance the loop is not progress.

5. **Never fabricate data.** Honor the honesty contract
   (`docs/product/DEMO_VS_REAL_DATA.md`): synthetic ≠ real, units ≠ AED, derived ≠
   captured, and the disclosure travels with the answer. No mocked numbers presented as
   real, ever.

6. **One business question = one business number.** If two surfaces answer the same
   question, they must show the same value. Contradictory KPIs are a correctness bug, not
   a styling difference.

7. **Every workflow ends in a measurable outcome.** A recommendation that can't be
   measured after the fact isn't finished — the *measure* step (worker `measure.js`,
   outcome pricing) is part of the feature, not a follow-up.

8. **Backward compatibility first.** New AI capability lands behind a flag with a
   deterministic fallback. `use_sage_v3` defaults to `False` in `config.py`; the
   rule-based path must produce a correct answer with **zero LLM** before the LLM tier is
   turned on.

---

## 2. Ownership Rules

Ownership is by **bounded context**, not by layer. See `TEAM_OWNERSHIP.md` for the full
map; the summary:

| Dev | Branch prefix | GitHub | Bounded context |
|---|---|---|---|
| Atharva | `atharva/` | @mercydeez | AI / Sage / Decision / Briefing / Role-Experience **vertical** (backend + frontend + `worker/`) |
| Krishna | `krishna/` | @krish2105 | Backend / platform / data / auth / security / integrations **horizontal** |
| Yash | `yash/` | @Yashpetkar7 | Frontend / design-system / pages / i18n / a11y **horizontal** |

**Bounded-context beats layer.** A file in Atharva's context but living under `backend/`
or `frontend/` is still Atharva's — `.github/CODEOWNERS` encodes this with "last matching
pattern wins" (the layer defaults come first, the AI/Experience vertical overrides them).

**The "may I edit another owner's module?" ladder:**

1. **Inside your own context:** edit freely.
2. **Small cross-owner change:** keep it minimal and let CODEOWNERS auto-request the
   owner's review. You don't need permission to *propose*; you do need their review to
   *merge*.
3. **A hub or a contract seam (§5):** **discuss first.** Open the conversation before you
   write the change — these files are stewarded, not co-edited.

**Cross-module coordination:** when two owners touch a shared file or a seam, the smaller
PR lands first (the shared-file steward's PR is small and fast by design), and the other
rebases onto it. Contracts are co-owned; implementations on either side stay private to
their owner.

---

## 3. AI Coding Rules

We build with Claude Code / Opus / Codex. These rules keep the AI an accelerator, not a
liability.

1. **No whole-subsystem rewrites.** Never ask the AI to "rewrite the X engine." Scope
   prompts to a file or a function. Big-bang AI rewrites destroy the review trail and the
   ownership boundaries.
2. **Stay in your context.** Never let the AI edit files outside your owned modules
   without the owner's approval — the same rule that binds you binds the AI acting on your
   behalf.
3. **Explanation before implementation.** Have the AI explain the change and the approach
   *before* it writes code. Plan, then apply — the same plan-then-apply discipline used to
   produce the plans in `plans/`.
4. **Small prompts → small commits.** A focused prompt yields a focused diff yields a
   single logically-scoped commit. Don't batch unrelated changes because the AI offered
   them.
5. **Read and understand every generated diff before committing.** You are accountable for
   the code, not the tool.
6. **Never commit code you can't explain.** If you can't defend a line in review, it
   doesn't ship.
7. **The AI respects the same invariants you do:** units ≠ AED (ADR-002), read-only data
   scope for AI features, additive/idempotent migrations (ADR-005), hub append-only rules
   (add endpoints via `routes/registry.py`, pages via `config/nav.tsx`).
8. **Keep the co-author trailer.** AI-assisted commits carry
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` — honest attribution is part
   of the honesty contract.

---

## 4. Git Rules

Condensed from `GIT_WORKFLOW.md` — read it for the full detail.

- **Branch:** `<owner>/<epic-id>-<slug>` (e.g. `atharva/E3-2-decision-inbox`), 1–3 day
  lifespan. Long-lived branches drift and conflict.
- **Commits:** Conventional Commits, small and logically-scoped. **Don't mix a refactor
  with a feature** in one commit.
- **PRs:** one workstream each, target ~≤400 lines, squash-merge, delete the branch after.
- **Rebase, never merge** onto `main`; rebase daily; push with `--force-with-lease`.
- **Shared hubs first:** a PR that touches a hub or seam lands fast and small so everyone
  else can rebase onto it.
- **Migrations:** numbered `max+1`, additive and idempotent; never edit a merged
  migration.
- **Bad merged change:** revert it (a new commit), don't rewrite published history.

Cross-link, don't restate: if a rule here and `GIT_WORKFLOW.md` ever diverge, the workflow
doc is authoritative.

---

## 5. Module Boundaries

The abstract "engines" map to real code as follows. Each subsystem lists **allowed
dependencies**, **forbidden dependencies**, and a concrete **bad-coupling example**.
Ground every edge in the dependency tiers in `PROJECT_STRUCTURE.md`.

**Hubs** (stable-contract, review-gated, never casually edited): `database.py`,
`redis_client.py`, `auth_service.py`, `security_events.py`, `cache.py`, `data_sync.py`,
`llm/*`, `nl2sql/*`; frontend `components/ui/index.ts`, `apiClient.ts`, Auth/Experience
contexts, `config/nav.tsx`, `LanguageContext.tsx`, `types/index.ts`.

**Contract seams** (cross-owner, change via small fast PR): `forecast_service.py` public
API (Krishna → Atharva's briefing/decisions); the role_experience nav-manifest shape
(Atharva config → Yash rendering); `routes/kpis.py` units/AED reference impl.

### AI / Sage
`services/{llm,nl2sql,sage2,sage3,rag,federation}`, `routes/ai.py`, `routes/search.py`.
"Sage" is the product name of the NL→SQL assistant, not a separate module.
- **Allowed:** `federation`/`sage2` orchestrator → `llm`, `nl2sql`; read via existing
  data readers and the SQL views.
- **Forbidden:** widening tenant/store scope beyond the caller's; issuing DDL/DML; querying
  non-`sage_*` relations; presenting output without its disclosure.
- **Bad coupling:** an AI node that rewrites its SQL to drop the `tenant_id` filter to
  "get more context." The NL→SQL guard rejects DDL/DML and non-`sage_*` relations, and the
  deterministic fallback must answer with zero LLM (`docs/production/AI_SAFETY.md`,
  `docs/SAGE_V3_MASTER_PROMPT.md` HARD INVARIANTS).

### Backend
FastAPI routers + services (`PROJECT_STRUCTURE.md` layer subsystem).
- **Allowed mid-tier edges:** `forecast_service` → `cache`, `data_sync`, `predictor`;
  `decision_center` → `forecast_service`.
- **Forbidden:** a new endpoint wired directly into `main.py`; casually editing a hub
  (`database.py`, `auth_service.py`, …) instead of extending behind its contract.
- **Bad coupling:** a reader computing revenue as `SUM(sales)` in Python instead of the
  derived `SUM(units × unit_price_aed)` from the `kpis.py` reference — that silently mixes
  units and AED.

### Frontend
Pages under `src/app/*/page.tsx`, feature components, `lib/api.ts` facade over
`lib/apiClient.ts`.
- **Allowed:** pages → `lib/api.ts` → backend; shared primitives from
  `components/ui/index.ts`.
- **Forbidden:** one feature importing another feature's internal components/state; a page
  bypassing `lib/api.ts` to hit endpoints ad hoc.
- **Bad coupling:** the `briefing` page importing a component out of the `decisions`
  feature folder instead of going through the API/shared-UI seam (violates ADR-007's thin
  composers + feature folders).

### Worker
Node BullMQ diagnostics engine `worker/src/*` (the "Findings" engine): `scan.js`,
`rules.js`, `findings.js`, `measure.js`, `outcome.js`, etc.
- **Allowed:** its own deps (`bullmq`/`ioredis`/`pg`); the shared Redis + Postgres; writes
  `findings` rows the backend/Sage read.
- **Forbidden:** importing Python backend code — it is a **separate service by design**,
  with no shared code.
- **Bad coupling:** the worker `import`-ing a Python service or reaching into backend
  internals for a helper, instead of talking to Postgres/Redis. Duplicate the small helper
  in JS; keep the services decoupled.

### Database
`database/init.sql`, `database/migrations/00*.sql`, the migration runner.
- **Allowed:** additive migrations numbered `max+1`, idempotent, forward-only.
- **Forbidden:** editing a merged migration; non-idempotent DDL; a migration the runner
  can't wrap in a transaction (e.g. `CREATE INDEX CONCURRENTLY` — ADR-005/009).
- **Bad coupling:** amending `007` to "fix" it rather than adding `05x` — breaks every
  already-migrated environment.

### Security
`auth_service.py`, `security_events.py`, the middleware stack, RLS migrations.
- **Allowed:** app-layer `tenant_id` filtering as the primary control; Postgres RLS as the
  backstop.
- **Forbidden:** a data path that trusts client-supplied tenant/store; disabling RLS
  casually (`allow_insecure_no_rls` is a dangerous override, not a convenience).
- **Bad coupling:** a router that reads a `tenant_id` from the request body instead of the
  authenticated user (ADR-006 — scope is server-side).

### Design System
`components/ui/*` + `ui/index.ts`, `motion.tsx`; tokens in `lib/brand.ts` / `globals.css`
/ `tailwind.config.js` (**Yash-gatekept**).
- **Allowed:** features consume primitives from `components/ui/index.ts` and tokens from
  `brand.ts`.
- **Forbidden:** hard-coding colors/spacing/typography that duplicate a token; forking a
  primitive into a feature folder.
- **Bad coupling:** a page defining its own `Button` with inline styles instead of
  importing the shared one and, if it needs a variant, requesting the change in the design
  system.

### Decision Engine
`services/decision_center.py` + `services/action_drafting.py`, `routes/decisions.py` +
`routes/action_drafts.py`. **Read-only by design.** Action Drafts are autonomy **L1** —
the system drafts, a human approves; nothing auto-executes.
- **Allowed:** `decision_center` → `forecast_service`.
- **Forbidden:** any code path that executes an action without human approval; write-backs
  from a "decision."
- **Bad coupling:** an action draft that, on generation, mutates inventory/pricing instead
  of queuing a human-approvable draft.

### Experience / Role Engine (one subsystem)
The **Experience Engine and the Role Engine are the same thing** — the **Role Experience
Engine**: `services/role_experience.py` (`_CONFIGS` = data, one record per role),
`routes/experience.py`, frontend `contexts/ExperienceContext.tsx`, `app/today/page.tsx`,
nav manifest resolved via `config/nav.tsx`'s `NAV_ICONS`.
- **Allowed:** role/tenant variation expressed as `_CONFIGS` records; frontend renders the
  manifest the backend emits.
- **Forbidden:** role-specific `if role == …` code paths outside `_CONFIGS`; the frontend
  hard-coding per-role screens.
- **Bad coupling:** adding a role by copying `today/page.tsx` into a role-specific page
  instead of adding a config record — that is exactly the duplication "one engine, twenty
  experiences" exists to prevent.

---

## 6. Adding Features

Before building **anything**, answer the gate (the Role Blueprint's "Five Questions").
If these can't be answered, **don't build it.**

1. **Who is the user?** (which role, from `_CONFIGS`)
2. **Which workflow does this change?** (where in detect → … → measure does it sit?)
3. **Which module owns it?** (bounded context → owner → CODEOWNERS)
4. **Which role sees it?** (role config + RBAC, not a bespoke screen)
5. **What business problem does it solve, and how is success measured?** (the measure step
   must exist)

**Sequence honestly** (blueprint rec #12): Wave 1 = configs → Wave 2 = surfaces → Wave 3 =
new data. Don't ship a surface for data the backend can't yet produce (ADR-008). Respect
the blueprint's **kill/pivot criteria** — if a feature can't demonstrate its outcome, it's
a candidate to cut, not to polish.

---

## 7. Pull Request Checklist

This **complements** `.github/pull_request_template.md` and the `CONTRIBUTING.md`
checklist — it does not replace them. In addition to the template's items (branch naming,
tests, units/AED, registry/nav routing, additive migrations, staying in-context,
Conventional Commit title), confirm the contract-specific items:

- [ ] **No duplicated business logic** — the number is computed once (SQL view / `kpis.py`)
      and read, not re-derived.
- [ ] **No contradictory KPIs** — the same business question yields the same number
      everywhere it appears.
- [ ] **No broken workflows** — the detect → … → measure loop still completes end-to-end.
- [ ] **No UI or security regressions** — auth/tenant scope intact; shared UI unbroken.
- [ ] **Docs updated** — if behavior or structure changed, the relevant doc changed too.
- [ ] **Ownership respected** — changes stay in your context, or the owner's review is
      requested for anything outside it.

---

## 8. Definition of Done

A change is done when **all** of these are true:

1. **Implementation complete** — the feature does what the gate (§6) said it would.
2. **Tests green** — `pytest tests/`, `tsc --noEmit`, `npm run build`, and (for worker
   changes) `npm test` (`node --test src/*.test.js`) all pass.
3. **Docs updated** — structure/behavior changes are reflected in the relevant doc.
4. **Workflow completes end-to-end** — a user can go from detect to measured outcome
   without a dead end.
5. **Sage can speak to it** — the AI assistant can answer questions about the feature, or
   it's grounded so it doesn't hallucinate around it.
6. **Role permissions correct** — RBAC (server-side scope) *and* role config both allow the
   right people and only them.
7. **User completes the task without confusion** — the surface answers "what do I do next?"
8. **Observability present where appropriate** — logging and `request_id` propagation on
   new server paths.

---

## 9. Product Philosophy

Reinforcing (not reinventing) what the blueprints already commit us to:

- **We build workflows and decisions, not dashboards and charts.** The Decision Center is
  "an inbox of decisions, not a dashboard" (E3-2). A chart that doesn't drive a decision is
  decoration.
- **Preserve context; measure outcomes.** "The loop is the company"; "the outcome loop is
  the brand" (`docs/EXECUTION_BLUEPRINT_12M.md`). Every recommendation is measured after
  the fact.
- **AI should reduce work, not create work.** If a feature makes the user do *more* to feed
  the AI, it's backwards.
- **Enterprise users should never wonder what to do next.** The Five Questions are the
  homepage grammar (`docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`).
- **Trust > feature count.** "Honesty is the brand" — synthetic labeled synthetic, units
  never shown as AED, derived never shown as captured. We would rather ship fewer, honest
  surfaces than many that mislead.

---

## References

| Document | What it grounds here |
|---|---|
| [`TEAM_OWNERSHIP.md`](TEAM_OWNERSHIP.md) | §2 ownership map, bounded-context rule |
| [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) | §5 subsystem map, dependency tiers, hubs/seams |
| [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) | §4 branching, PRs, rebase, migration numbering |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | §7 PR checklist, run/test/build commands |
| [`.github/CODEOWNERS`](.github/CODEOWNERS) | machine-enforced review routing (source of truth) |
| [`docs/architecture/ADR.md`](docs/architecture/ADR.md) | §1/§5 invariants: ADR-002 units/AED, ADR-005 migrations, ADR-006 RBAC scope, ADR-007/008 thin composers + build-what-backend-supports |
| [`docs/EXECUTION_BLUEPRINT_12M.md`](docs/EXECUTION_BLUEPRINT_12M.md) | §1/§6/§9 the loop, depth over surface, honest sequencing, kill/pivot |
| [`docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`](docs/product/ROLE_EXPERIENCE_BLUEPRINT.md) | §1/§5/§6/§9 one engine many configs, the Five Questions |
| [`docs/product/DEMO_VS_REAL_DATA.md`](docs/product/DEMO_VS_REAL_DATA.md) | §1/§9 honesty contract |
| [`docs/production/AI_SAFETY.md`](docs/production/AI_SAFETY.md) | §5 AI read-only scope, NL→SQL guard |
