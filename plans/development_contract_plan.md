# Plan: Add `DEVELOPMENT_CONTRACT.md` — the team operating agreement

## Context

The repo already has the *mechanical* governance layer for three AI-assisted developers
(Atharva/@mercydeez, Krishna/@krish2105, Yash/@Yashpetkar7) working in parallel:
`TEAM_OWNERSHIP.md` (who owns what), `PROJECT_STRUCTURE.md` (subsystem map + dependency
graph), `GIT_WORKFLOW.md` (trunk-based branching/PRs), `CONTRIBUTING.md` (run/test/build),
`.github/CODEOWNERS` (path→reviewer), and the two conflict hubs refactored out
(`routes/registry.py`, `config/nav.tsx`).

What's missing is the **human operating agreement** that sits above those: the shared
principles, the AI-coding discipline, and the product philosophy that let three people
using Claude Code / Opus / Codex work for months without stepping on each other or
eroding product quality. This document, `DEVELOPMENT_CONTRACT.md`, is that handbook. It
is **not** new technical spec — it codifies and cross-links what already exists so the
rules are enforceable and teachable. Every rule must trace to an artifact already in the
repo (ownership model, ADRs, execution blueprint, role-experience blueprint), not to
generic software-engineering advice.

Outcome: a permanent engineering handbook, cross-referenced from `README.md` and
`TEAM_OWNERSHIP.md`, committed and pushed to the current branch
(`prototype-evolution-accuracy-bullmq`) as a single docs commit.

## Grounding facts (verified in this repo — cite these, don't invent)

**People (consistent across all governance docs):**
| Dev | branch prefix | GitHub | Bounded context |
|---|---|---|---|
| Atharva | `atharva/` | @mercydeez | AI/Sage/Decision/Briefing/Role-Experience **vertical** (backend + frontend + `worker/`) |
| Krishna | `krishna/` | @krish2105 | Backend/platform/data/auth/security/integrations **horizontal** |
| Yash | `yash/` | @Yashpetkar7 | Frontend/design-system/pages/i18n/a11y **horizontal** |

Rule: *bounded-context beats layer* — a file in Atharva's context but under `backend/`
or `frontend/` is still Atharva's (CODEOWNERS "last matching pattern wins").

**The abstract "engine" names → real code** (needed for §5 Module Boundaries):
- **AI / Sage** = `services/{llm,nl2sql,sage2,sage3,rag,federation}`, `routes/ai.py`,
  `routes/search.py`. "Sage" is the product name of the NL→SQL assistant, not a separate module.
- **Decision Engine** = `services/decision_center.py` + `services/action_drafting.py`,
  `routes/decisions.py` + `routes/action_drafts.py`. Read-only by design; Action Drafts
  are autonomy **L1** (system drafts, human approves; nothing auto-executes).
- **Experience Engine and Role Engine are the same thing** — the **Role Experience
  Engine**: `services/role_experience.py` (`_CONFIGS` = data, one record per role),
  `routes/experience.py`, frontend `contexts/ExperienceContext.tsx`, `app/today/page.tsx`,
  nav manifest resolved via `config/nav.tsx`'s `NAV_ICONS`. §5 will treat them as one
  subsystem with a note.
- **Worker** = Node BullMQ diagnostics engine `worker/src/*` (the "Findings" engine).
  Self-contained (`bullmq`/`ioredis`/`pg`, no shared code with Python), reuses the
  existing Redis + Postgres, writes `findings` rows the backend/Sage read.
- **Design System** = `components/ui/*` + `ui/index.ts`, `motion.tsx`, tokens in
  `lib/brand.ts` / `globals.css` / `tailwind.config.js` (Yash-gatekept).
- **Backend / Frontend / Database / Security** = the layer subsystems in `PROJECT_STRUCTURE.md`.

**Dependency tiers (from `PROJECT_STRUCTURE.md`) → allowed/forbidden edges for §5:**
- *Leaf* (change freely): `roi`, `role_experience`, `uae_intelligence`, `predictor`,
  `csv_import`, `outcome_pricing`, `token_store`, `totp`, `database/migrations/050+.sql`.
- *Mid-tier allowed edges*: `forecast_service`→`cache,data_sync,predictor`;
  `briefing`→`roi,forecast_service,uae_intelligence`; `decision_center`→`forecast_service`;
  `federation/sage2 orchestrator`→`llm,nl2sql`.
- *Hubs* (stable-contract, review-gated, never casually edited): `database.py`,
  `redis_client.py`, `auth_service.py`, `security_events.py`, `cache.py`, `data_sync.py`,
  `llm/*`, `nl2sql/*`; frontend `components/ui/index.ts`, `apiClient.ts`, Auth/Experience
  contexts, `config/nav.tsx`, `LanguageContext.tsx`, `types/index.ts`.
- *Cross-owner contract seams*: `forecast_service.py` public API (Krishna→Atharva's
  briefing/decisions); the role_experience nav-manifest shape (Atharva config → Yash
  rendering); `routes/kpis.py` units/AED reference impl.

**Non-negotiable invariants (ADRs / blueprints) — the backbone of §1, §5, §9:**
- Units≠AED (ADR-002): raw `sales` = units; AED derived `SUM(units × unit_price_aed)`;
  VOLUME in units, VALUE in AED, never mixed on one axis; `routes/kpis.py` is reference.
- Additive & idempotent migrations, forward-only, never edit a merged migration (ADR-005).
- Build only what the backend supports — no mock-backed prod UI (ADR-007/008).
- AI is read-only by construction; cannot widen data scope; deterministic rule-based
  fallback must work with **zero LLM**; NL→SQL guard rejects DDL/DML/non-`sage_*` relations
  (`docs/production/AI_SAFETY.md`, `docs/SAGE_V3_MASTER_PROMPT.md` HARD INVARIANTS).
- Tenant isolation is layered: app-layer `tenant_id` filter primary, Postgres RLS backstop.
- Honesty contract (`docs/product/DEMO_VS_REAL_DATA.md`): synthetic≠real, units≠AED,
  derived≠captured, disclosure travels with the answer.
- Product spine (`docs/EXECUTION_BLUEPRINT_12M.md`): "The loop is the company" —
  detect→diagnose→recommend→accept→measure→price-on-outcome; "depth over surface";
  "honesty is the brand". Role model (`docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`):
  "one engine, twenty experiences"; adding a role = adding a config, not screens.

## Deliverable: `DEVELOPMENT_CONTRACT.md` (repo root)

Single Markdown file. Opens with a one-paragraph purpose + a pointer that CODEOWNERS is
the machine-enforced source of truth and this is the human agreement. Then the nine
sections below, each grounded in the artifacts above (cite file names inline).

1. **Engineering Principles** — expand the given list into repo-specific principles:
   *One source of truth* (`routes/kpis.py` for revenue, `lib/brand.ts` for naming,
   `role_experience._CONFIGS` for role behavior); *Never duplicate business logic* (SQL
   views over JS math — E6-1); *Configuration over duplication* ("one engine, many
   configs"); *Preserve workflow continuity* (close the detect→…→measure loop, don't
   decorate around it); *Never fabricate data* (honesty contract, units≠AED); *One
   business question = one business number*; *Every workflow ends in a measurable outcome*
   (the measure engine); *Backward compatibility first* (new AI tiers gated behind flags
   e.g. `USE_SAGE_V3` default false, deterministic fallback always works).

2. **Ownership Rules** — restate bounded-context ownership + the "may edit another's
   module when…" ladder: freely inside your context; minimal + owner review for a small
   cross-owner change (CODEOWNERS auto-requests); *discussion required* before touching a
   hub or a contract seam. Cross-module work coordinated via the smaller PR landing first
   (shared-file steward). Point to `TEAM_OWNERSHIP.md` for the full map.

3. **AI Coding Rules** — strict rules for Claude Code / Opus / Codex: never ask AI to
   rewrite a whole subsystem; never let AI edit files outside your owned context without
   the owner's approval; explanation-before-implementation; small focused prompts → small
   focused commits; read and understand every generated diff before committing; never
   commit code you can't explain; AI must respect the same invariants (units≠AED,
   read-only data scope, additive migrations, hub append-rules); keep the AI co-author
   trailer. Tie to the plan-then-apply discipline already used in this repo.

4. **Git Rules** — condense `GIT_WORKFLOW.md`: branch `<owner>/<epic-id>-<slug>`,
   1–3 day lifespan; Conventional Commits, small logically-scoped, don't mix refactor +
   feature; PRs one-workstream/<~400 lines, squash-merge, delete branch; rebase never
   merge, `--force-with-lease`, rebase daily; merge shared-hub PRs first/fast; migrations
   `max+1` additive; revert (not edit) a bad merged change; squash on merge. Cross-link,
   don't duplicate wholesale.

5. **Module Boundaries** — one subsection per subsystem (AI, Backend, Frontend, Worker,
   Database, Security, Design System, Decision Engine, Experience/Role Engine — noting
   they're one). Each states: **allowed dependencies**, **forbidden dependencies**, and a
   concrete **bad-coupling example**. Ground every edge in the dependency tiers above.
   Examples of forbidden coupling to include: frontend importing another feature's
   internals instead of going through `lib/api.ts`; a reader computing revenue in JS
   instead of via the SQL view / `kpis.py`; the worker importing Python backend code
   (it's a separate service by design); an AI node widening tenant/store scope; a page
   rendering data no endpoint supports; `role_experience` engine embedding role-specific
   code paths outside `_CONFIGS`.

6. **Adding Features** — the mandatory gate (who's the user / which workflow changes /
   which module owns it / which role sees it / what business problem / how success is
   measured). Ground in the Role Blueprint's "Five Questions" and rec #12 "sequence
   honestly" (Wave 1 configs → Wave 2 surfaces → Wave 3 new data), and the blueprint's
   kill/pivot criteria. State: if these can't be answered, don't build it.

7. **Pull Request Checklist** — mirror `.github/pull_request_template.md` +
   `CONTRIBUTING.md` checklist, adding the contract-specific items (no duplicated business
   logic, no contradictory KPIs, no broken workflows/UI/security regressions, docs
   updated, ownership respected). Note this complements, not replaces, the PR template.

8. **Definition of Done** — the given DoD list, made concrete: implementation done; tests
   green (`pytest tests/`, `tsc --noEmit`, `npm run build`, worker `npm test`); docs
   updated; workflow completes end-to-end; AI (Sage) can answer about it / it's grounded;
   role permissions correct (RBAC + role config); user completes the task without
   confusion; logging/`request_id` present where appropriate.

9. **Product Philosophy** — reinforce (not reinvent) the established principles with
   verbatim anchors: "we build workflows/decisions, not dashboards/charts" (E3-2 Decision
   Center = "an inbox of decisions, not a dashboard"); "preserve context / measure
   outcomes" (the loop is the company; "the outcome loop is the brand"); "AI should reduce
   work, not create work"; "enterprise users should never wonder what to do next" (the
   Five Questions homepage grammar); "trust > feature count" ("honesty is the brand").

Close with a **References** table linking every source doc (TEAM_OWNERSHIP,
PROJECT_STRUCTURE, GIT_WORKFLOW, CONTRIBUTING, CODEOWNERS, ADR.md,
EXECUTION_BLUEPRINT_12M, ROLE_EXPERIENCE_BLUEPRINT, DEMO_VS_REAL_DATA, AI_SAFETY).

## Cross-references to add (part of the same commit)

- **`README.md`** — in the "Further Reading" → "Contributing & team" bullet, add
  `DEVELOPMENT_CONTRACT.md` alongside the four existing governance docs.
- **`TEAM_OWNERSHIP.md`** — add a top-of-file/near-footer pointer to
  `DEVELOPMENT_CONTRACT.md` as the operating agreement above the ownership map (the file
  currently cross-links `GIT_WORKFLOW.md` and `PROJECT_STRUCTURE.md`; add the contract).
- **`docs/README.md`** — add one line under "Team & parallel development" (consistent with
  how the other four governance docs are indexed there).
- **`.github/CODEOWNERS`** — add `/DEVELOPMENT_CONTRACT.md` to the "Governance docs — all
  three review" block, matching the existing convention for the other governance docs.

## Commit & push

Single commit containing the new file + the four cross-reference edits:

```
docs: add development contract for AI-assisted team workflow

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

Then `git push` to the current branch `prototype-evolution-accuracy-bullmq` (not `main`;
no PR requested). Confirm the push succeeded.

## Verification

- `git status` clean after commit; `git show --stat` lists the 5 files (1 new + 4 edits).
- Grep that `DEVELOPMENT_CONTRACT.md` now appears in `README.md`, `TEAM_OWNERSHIP.md`,
  `docs/README.md`, `.github/CODEOWNERS`.
- Sanity-read the new file: every section present (1–9 + References), no invented
  file paths (spot-check a few cited paths exist), Atharva/Krishna/Yash + GitHub handles
  correct, commit message matches exactly.
- `git log --oneline -1` shows the new commit; `git push` output confirms the branch updated.
