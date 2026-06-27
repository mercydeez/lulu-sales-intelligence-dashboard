# Documentation Guide

The documentation is organized by how you should use it, not by when it was written.

## Start here

- [`../README.md`](../README.md) - setup, architecture, working features, and the current source of truth.
- [`../implementation.md`](../implementation.md) - the single living implementation plan & tracker (what's shipped + what's next).
- [`FRONTEND_OVERHAUL_PLAN.md`](FRONTEND_OVERHAUL_PLAN.md) - **contributor playbook**: phase-by-phase guide to take the frontend from basic → Awwwards-level (start here for UI work).
- [`architecture/ADR.md`](architecture/ADR.md) - the important engineering decisions and tradeoffs.
- [`product/DEMO_SCRIPT.md`](product/DEMO_SCRIPT.md) - the fastest way to walk someone through the project.
- [`product/PITCH.md`](product/PITCH.md) - the one-page narrative for recruiters, interviewers, or stakeholders.

## Current docs

### `architecture/`
- [`architecture/ADR.md`](architecture/ADR.md) - concise architecture decision records for the current implementation.

### `PUBLIC_API.md`
- [`PUBLIC_API.md`](PUBLIC_API.md) - per-tenant public REST API + embeddable AI assistant (B4/B5): auth, endpoints, isolation.

### `production/` — operations & deployment hardening
The production-readiness program (turning the MVP into a deployable, recoverable, tenant-isolated pilot). Start with the audit, then the gap analysis.
- [`production/BASELINE_AUDIT.md`](production/BASELINE_AUDIT.md) - current-state facts: what is production-grade, MVP-only, demo-only, or risky.
- [`production/PRODUCTION_GAP_ANALYSIS.md`](production/PRODUCTION_GAP_ANALYSIS.md) - recommendations mapped to hardening phases.
- [`production/RISK_REGISTER.md`](production/RISK_REGISTER.md) - top 30 risks ranked by severity, with mitigations.
- [`production/READINESS_CHECKLIST.md`](production/READINESS_CHECKLIST.md) - the GO/NO-GO checklist.

### `product/`
- [`product/DEMO_VS_REAL_DATA.md`](product/DEMO_VS_REAL_DATA.md) - **honesty contract**: demo/sample vs real vs derived-AED vs raw-unit data.
- [`product/DEMO_SCRIPT.md`](product/DEMO_SCRIPT.md) - guided demo flow with talking points.
- [`product/PITCH.md`](product/PITCH.md) - short pitch covering the problem, solution, and quality signals.
- [`product/PRODUCT_STRATEGY.md`](product/PRODUCT_STRATEGY.md) - positioning and feature strategy for the retail operations MVP.
- [`product/SAAS_PATH.md`](product/SAAS_PATH.md) - what it would take to turn the project into a sellable SaaS product.

## Historical docs

### `archive/`
These files are worth keeping because they show the original audit, redesign thinking, and execution plan. They are historical context, not the current source of truth.

- [`archive/GAP_ANALYSIS.md`](archive/GAP_ANALYSIS.md) - the original audit of problems and credibility gaps.
- [`archive/UI_UX_REDESIGN_PLAN.md`](archive/UI_UX_REDESIGN_PLAN.md) - the redesign brief for the frontend overhaul.
- [`archive/ARCHITECTURE_PLAN.md`](archive/ARCHITECTURE_PLAN.md) - the earlier architectural target shape.
- [`archive/CODEBASE_MAP.md`](archive/CODEBASE_MAP.md) - the June 2026 inspection snapshot of the repo before later fixes landed.
