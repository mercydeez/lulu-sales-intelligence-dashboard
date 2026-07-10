# Documentation Guide

The documentation is organized by how you should use it, not by when it was written.

## Start here

- [`../README.md`](../README.md) - setup, architecture, working features, and the current source of truth.
- [`../implementation.md`](../implementation.md) - the single living implementation plan & tracker (what's shipped + what's next).
- [`EXECUTION_BLUEPRINT_12M.md`](EXECUTION_BLUEPRINT_12M.md) - the audit-derived **12-month execution plan** (epics, milestones, GTM, hiring, investor gates). E0-1 (backups + rehearsed restore) is done.
- [`runbooks/`](runbooks/) - incident + operations runbooks. Start with [`runbooks/BACKUP_AND_RESTORE.md`](runbooks/BACKUP_AND_RESTORE.md) for disaster recovery.
- [`FRONTEND_OVERHAUL_PLAN.md`](FRONTEND_OVERHAUL_PLAN.md) - **contributor playbook**: phase-by-phase guide to take the frontend from basic → Awwwards-level (start here for UI work).
- [`architecture/ADR.md`](architecture/ADR.md) - the important engineering decisions and tradeoffs.
- [`product/DEMO_SCRIPT.md`](product/DEMO_SCRIPT.md) - the fastest way to walk someone through the project.
- [`product/PITCH.md`](product/PITCH.md) - the one-page narrative for recruiters, interviewers, or stakeholders.

## Team & parallel development

For the three-developer engineering organization (root-level docs):
- [`../DEVELOPMENT_CONTRACT.md`](../DEVELOPMENT_CONTRACT.md) - the operating agreement: engineering principles, AI-coding rules, module boundaries, and product philosophy above the ownership map.
- [`../TEAM_OWNERSHIP.md`](../TEAM_OWNERSHIP.md) - module ownership (bounded-context), shared-file rules, and the parallel workstreams.
- [`../PROJECT_STRUCTURE.md`](../PROJECT_STRUCTURE.md) - architecture, subsystem map, dependency graph, ownership overlay.
- [`../GIT_WORKFLOW.md`](../GIT_WORKFLOW.md) - trunk-based branching, PRs, reviews, migration numbering, conflict resolution.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) - run/test/build commands, traps, and how to extend without touching hub files.
- [`../.github/CODEOWNERS`](../.github/CODEOWNERS) - machine-enforced path→reviewer routing.

## Current docs

### `architecture/`
- [`architecture/ADR.md`](architecture/ADR.md) - concise architecture decision records for the current implementation.

### `PUBLIC_API.md`
- [`PUBLIC_API.md`](PUBLIC_API.md) - per-tenant public REST API + embeddable AI assistant (B4/B5): auth, endpoints, isolation.
- [`api/VERSIONING.md`](api/VERSIONING.md) - the `/api/public/v1` version contract (E6-6): what may change inside a version, the deprecation → sunset → `410` lifecycle, and why `/api/<domain>` is explicitly *not* a supported surface.

### `production/` — operations & deployment hardening
The production-readiness program (turning the MVP into a deployable, recoverable, tenant-isolated pilot). Start with the audit, then the gap analysis.
- [`production/BASELINE_AUDIT.md`](production/BASELINE_AUDIT.md) - current-state facts: what is production-grade, MVP-only, demo-only, or risky.
- [`production/LOAD_TEST_BASELINE.md`](production/LOAD_TEST_BASELINE.md) - measured k6 + SSE baseline (E6-5), and the finding it produced: the API runs on a single uvicorn worker, and the singleton background tasks must move out before it can be scaled.
- [`production/PRODUCTION_GAP_ANALYSIS.md`](production/PRODUCTION_GAP_ANALYSIS.md) - recommendations mapped to hardening phases.
- [`production/RISK_REGISTER.md`](production/RISK_REGISTER.md) - top 30 risks ranked by severity, with mitigations.
- [`production/READINESS_CHECKLIST.md`](production/READINESS_CHECKLIST.md) - the GO/NO-GO checklist.

### `product/`
- [`product/ROLE_EXPERIENCE_BLUEPRINT.md`](product/ROLE_EXPERIENCE_BLUEPRINT.md) - **the UX north star**: AI-first, role-based product experience design — 20 role playbooks (mission, homepage, Sage persona, decisions, KPIs, notifications, device), the decision-ownership AED ladder, collaboration workflows, and the one-engine/many-configs architecture.
- [`product/DEMO_VS_REAL_DATA.md`](product/DEMO_VS_REAL_DATA.md) - **honesty contract**: demo/sample vs real vs derived-AED vs raw-unit data.
- [`product/DEMO_SCRIPT.md`](product/DEMO_SCRIPT.md) - guided demo flow with talking points.
- [`product/PITCH.md`](product/PITCH.md) - short pitch covering the problem, solution, and quality signals.
- [`product/PRODUCT_STRATEGY.md`](product/PRODUCT_STRATEGY.md) - positioning and feature strategy for the retail operations MVP.
- [`product/SAAS_PATH.md`](product/SAAS_PATH.md) - what it would take to turn the project into a sellable SaaS product.
- [`product/PLATFORM_CONSOLE.md`](product/PLATFORM_CONSOLE.md) - internal operator console: the per-tenant customization catalog, bespoke-request ledger, Atelier advisor, and the platform-developer access boundary (who gets in, and why `super_admin` can't).
- [`product/IMPROVEMENT_ROADMAP.md`](product/IMPROVEMENT_ROADMAP.md) - prioritized Now/Next/Later roadmap of SaaS improvements, each grounded in code that already exists.

## Historical docs

### `archive/`
These files are worth keeping because they show the original audit, redesign thinking, and execution plan. They are historical context, not the current source of truth.

- [`archive/GAP_ANALYSIS.md`](archive/GAP_ANALYSIS.md) - the original audit of problems and credibility gaps.
- [`archive/UI_UX_REDESIGN_PLAN.md`](archive/UI_UX_REDESIGN_PLAN.md) - the redesign brief for the frontend overhaul.
- [`archive/ARCHITECTURE_PLAN.md`](archive/ARCHITECTURE_PLAN.md) - the earlier architectural target shape.
- [`archive/CODEBASE_MAP.md`](archive/CODEBASE_MAP.md) - the June 2026 inspection snapshot of the repo before later fixes landed.
