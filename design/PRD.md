# Retail IQ Experience Redesign PRD

## 1. Objective

Redesign Retail IQ from a feature-rich engineering demo into a production-quality enterprise SaaS experience without overstating what the current backend can do.

This PRD defines the target product experience, information model, and UX constraints for the current repository. It does not authorize frontend implementation changes by itself.

## 2. Repository Truths

### 2.1 Capabilities that already exist

Retail IQ already provides:

- authenticated multi-tenant web application flows
- JWT auth, invite acceptance, email verification, password reset, and TOTP MFA
- tenant-aware server scoping with optional Postgres RLS enforcement
- role-adaptive experience support for `super_admin`, `regional_manager`, and `store_manager`
- real product modules for inventory, procurement, promotions, employees, reports, billing, security, audit, monitoring, data imports, and developer access
- SSE-backed live updates from the synthetic sales pipeline
- AI surfaces for briefing, decisions, findings, copilot/chat, and public AI embedding
- API keys, webhooks, and public API routes for tenant developers

### 2.2 Constraints the redesign must honor

- units and AED are different truths and must never be visually or verbally conflated
- AI must remain grounded in tenant-scoped data and existing backend actions
- role scope is enforced by the backend and cannot be treated as cosmetic UI hiding
- SSE is the live delivery mechanism; do not imply WebSocket-style collaboration or presence
- some admin/platform surfaces are read-heavy today; UX must not imply unsupported write authority
- route availability is broader than current UX quality; redesign should consolidate and clarify, not fabricate

### 2.3 Current roles with meaningful product implications

- executive / tenant owner
- regional manager
- store manager
- procurement / operations power user
- tenant admin / platform operator
- developer / integrator

## 3. Product Problems To Solve

The current product has backend credibility but a fragmented experience model.

### 3.1 Navigation mirrors implementation instead of user jobs

Users see a flat list of routes instead of a domain-led operating system.

### 3.2 Home does not establish a clear daily contract

The product should immediately answer:

1. what changed
2. what matters
3. what needs a decision
4. what AI recommends
5. what can be trusted

### 3.3 AI is powerful but fragmented

Briefing, copilot, decisions, findings, and chat behave like separate features instead of one coherent product layer.

### 3.4 Enterprise trust surfaces are present but under-framed

Billing, team, audit, security, tenant lifecycle, and developer tools exist, but they do not yet feel like first-class enterprise workflows.

### 3.5 States and transitions are under-specified

Loading, empty, error, permission, degraded-stream, and first-run states need a consistent grammar across the app.

## 4. Product Thesis

Retail IQ should feel like the daily operating system for a multi-store retailer.

It is not primarily a dashboard.
It is a decision and operating environment built on:

- role-aware daily orientation
- evidence-backed workflow queues
- operational execution workspaces
- explainable intelligence
- visible platform trust and governance

## 5. Experience Outcomes

The redesign succeeds when the product feels:

- visually premium and calm
- simpler to understand than the current route map
- faster to act in than a traditional analytics dashboard
- safer and more trustworthy for enterprise buyers
- consistent enough that AI-generated and hand-built pages look like one system

## 6. Canonical Product Model

The experience should be organized into six product domains:

1. `Home`
2. `Workflows`
3. `Operations`
4. `Intelligence`
5. `Platform`
6. `Admin`

### 6.1 Home

Purpose:

- establish daily orientation
- summarize business state by role
- provide a short path to the next important action

Primary surfaces:

- Today
- Executive Briefing
- Sage Copilot

### 6.2 Workflows

Purpose:

- collect decision-ready work
- keep approval, findings, alerts, and drafts in one operating grammar

Primary surfaces:

- Decisions
- Insights
- Alerts
- Approvals
- Action Drafts

### 6.3 Operations

Purpose:

- execute business work
- manage stock, orders, promotions, and workforce surfaces

Primary surfaces:

- Inventory
- Procurement
- Suppliers
- Purchase Orders
- Promotions
- Workforce

### 6.4 Intelligence

Purpose:

- explore business movement
- compare trends
- explain forecast and value

Primary surfaces:

- Analytics
- Forecast Lab
- Reports
- Value
- UAE Insights

### 6.5 Platform

Purpose:

- connect, ingest, monitor, and expose the system

Primary surfaces:

- Data Sources
- Imports
- Developer Portal
- Monitoring
- Public Status

### 6.6 Admin

Purpose:

- govern the tenant, organization, billing, and trust posture

Primary surfaces:

- Admin Overview
- Tenant Console
- Company
- Billing and Plans
- Outcome Pricing
- Team
- Security
- Audit
- Trust
- Account and Preferences

## 7. Core UX Decisions

### 7.1 Make `Today` the canonical post-login landing surface

`/today` should become the primary in-app landing experience.
`/` may remain as a compatibility route during transition, but the information architecture should treat `Today` as the real home.

### 7.2 Move from route list to layered navigation

- primary left rail for domains only
- secondary context rail for domain pages
- top utility bar for search, notifications, scope, language, and account

### 7.3 Reduce top-level clutter

Do not treat profile, preferences, pricing, and public status as peer-level primary navigation items.

They should be nested or utility-accessed.

### 7.4 Treat AI as a system layer, not a standalone novelty

Sage should have one interaction grammar across:

- proactive reading
- conversational asking
- recommendation
- draft creation
- outcome measurement

### 7.5 Use workflow objects consistently

Users should not have to relearn the interface between findings, decisions, approvals, alerts, and drafts.

Shared behaviors should include:

- severity
- impact
- confidence
- scope
- evidence
- primary action
- measured outcome

## 8. Primary Personas And Jobs

### 8.1 Executive / tenant owner

Needs:

- business clarity in under five minutes
- explicit money impact
- confidence in AI recommendations
- fast review of strategic exceptions

### 8.2 Regional manager

Needs:

- store and region comparison
- prioritized operating risks
- approvals and delegation
- fast jump from signal to supporting detail

### 8.3 Store manager

Needs:

- immediate action language
- stock and alert recovery workflows
- low-friction approvals and replenishment steps
- minimal page complexity

### 8.4 Procurement / operations manager

Needs:

- reorder to PO workflow continuity
- supplier context
- receiving and invoice matching visibility
- measurable savings and stock impact

### 8.5 Tenant admin / platform operator

Needs:

- lifecycle, billing, team, and policy control
- trustworthy monitoring and auditability
- clean data ingestion and system health workflows

### 8.6 Developer / integrator

Needs:

- predictable API/auth setup
- key and webhook lifecycle clarity
- copyable examples
- clear tenant-scoped contract understanding

## 9. UX Quality Bar

The redesign must meet these standards:

- Apple-level finish and restraint
- Stripe-level clarity and technical confidence
- Sprinto-level trust framing for governance surfaces
- WCAG AA contrast and keyboard usability
- desktop-first layouts with strong responsive fallbacks
- consistent empty, error, loading, and no-permission design

## 10. Explicit Non-Goals

- redefining backend permissions or tenancy rules
- inventing unsupported write operations
- introducing autonomous AI execution beyond current draft/recommend patterns
- designing a separate mobile-first product
- dark mode in this phase

## 11. Future-Dependent Areas

The following may be designed as reserved space only when clearly labeled:

- `[Future Enhancement]` full SSO/SCIM setup and lifecycle UX
- `[Future Enhancement]` supplier-facing portal
- `[Future Enhancement]` broader role catalog beyond the current production roles
- `[Future Enhancement]` deeper automation execution after policy hardening
- `[Future Enhancement]` richer sync scheduling and transformation controls for data sources

## 12. Success Metrics

### 12.1 Product outcomes

- time from login to first meaningful action
- time from insight to decision
- time from recommendation to approved execution step
- weekly active use of `Today`, `Briefing`, and `Decisions`
- API key creation to first successful request conversion
- invite creation to teammate activation conversion

### 12.2 Experience outcomes

- fewer top-level nav choices exposed at one time
- lower confusion between operational and governance surfaces
- fewer units/AED labeling mistakes
- better discoverability of trust, billing, and developer workflows
- greater reuse of one coherent AI interaction pattern

## 13. Delivery Guidance

Recommended implementation sequence:

1. Home
2. Workflows
3. Operations
4. Platform
5. Intelligence
6. Admin

Reason:

- Home and Workflows define the daily product contract
- Operations proves business usefulness
- Platform and Admin raise enterprise trust
- Intelligence can then be simplified using the established system
