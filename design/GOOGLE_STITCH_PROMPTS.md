# Google Stitch Prompts

## 1. Purpose

Use this file to generate consistent page concepts in Google Stitch for the redesigned Retail IQ product.

These prompts assume alignment with:

- `PRD.md`
- `INFORMATION_ARCHITECTURE.md`
- `DESIGN_SYSTEM.md`
- `COMPONENT_LIBRARY.md`
- `SCREEN_INVENTORY.md`
- `AI_EXPERIENCE.md`
- `VISUAL_LANGUAGE.md`

## 2. Non-Negotiable Product Constraints

Every Stitch prompt must respect these constraints:

- do not invent backend actions that do not exist in this repository
- do not imply autonomous AI execution beyond recommendation and draft creation
- do not imply real-time collaboration or WebSocket behavior beyond current SSE-backed live states
- do not mix units and AED in one KPI or chart without explicit separation
- do not surface hidden or privileged data across role boundaries
- do not make public or print routes look like primary navigation destinations

## 3. Required Prompt Input Block

Before generating any page, specify:

- page title
- route
- user role
- domain
- page purpose
- current backend constraints
- required components
- required states
- responsive note

Recommended input format:

> Product: Retail IQ. Domain: `Home`. Route: `/today`. User: `regional_manager`. Purpose: prioritize region-scoped work for today. Backend constraints: role-scoped experience manifest, SSE live status, decisions are recommendation objects, approvals are explicit user actions. Required components: hero verdict, metric strip, priority modules, workflow links, Sage summary band. Required states: loading, no-permission, degraded live state. Responsive note: preserve read and approve flows on tablet/mobile.

## 4. Shell Foundation Prompt

### S0 - Global Shell

Use this before any page-family prompt when generating a full page:

> Design the page inside a premium enterprise SaaS shell for Retail IQ. Use a left domain rail with exactly six top-level domains: Home, Workflows, Operations, Intelligence, Platform, Admin. Add a secondary context rail for pages inside the active domain. Add a top utility bar with command palette, notifications, scope chip, language switcher, account menu, and Sage launcher. The shell must feel bright, calm, and highly structured. This is a desktop-first Next.js + Tailwind + shadcn/ui product with WCAG AA requirements.

## 5. Master Product Prompt

### P0 - Retail IQ Foundation

Use at the top of every Stitch page prompt:

> Design a premium enterprise SaaS interface for Retail IQ, an AI-native retail operations platform for multi-store retailers in the UAE. The experience should combine Apple-quality visual finish, Stripe-like clarity, and Sprinto-like trust framing. Use a warm off-white canvas, white surfaces, deep charcoal text, teal as the primary brand color, violet only for AI accents, and coral only for destructive or risk states. The product is desktop-first, bright-theme, WCAG AA, and built for Next.js, Tailwind CSS, and shadcn/ui implementation. The interface should be decision-first, not dashboard-first. Emphasize clear hierarchy, restrained elegance, generous spacing, refined cards, consistent tables, and explicit state handling.

## 6. Page Family Prompts

### P1 - Access And Activation

Use for:

- A01-A08

Prompt:

> Create an enterprise access or onboarding page for Retail IQ. The layout should feel secure, calm, and premium rather than consumer-fintech. Use a split layout only when it improves focus. Prioritize clarity of the next step, strong field labels, careful validation states, and an intentional trust tone. For onboarding, use a structured checklist and progress framing rather than a long wizard.

### P2 - Home

Use for:

- B01-B09

Prompt:

> Design a Home-domain page for Retail IQ. This page should answer what matters now, what needs the user, and where to go next. Use a hero verdict or summary first, then a compact metric strip, then a small number of priority modules. Keep the page calm and decisive. This should not feel like a generic dashboard or analytics wall.

### P3 - Workflows

Use for:

- C01-C09

Prompt:

> Design a workflow-centered enterprise page for Retail IQ where the user reviews, investigates, approves, dismisses, or drafts actions. Use a page header, structured filters or tabs, a vertically scannable queue, and an in-context detail drawer. Decision cards, finding cards, alerts, approvals, and drafts should feel like one related family of objects. Prioritize explainability, confidence, evidence, and clear next actions.

### P4 - Operations

Use for:

- D01-D10

Prompt:

> Design an operations workspace for Retail IQ. This page should feel like a serious operational tool for inventory, procurement, suppliers, promotions, workforce, receiving, or invoice matching. Use a page header, filters, status strip where useful, and content built from tables, queue items, and review panels. Emphasize transaction clarity, status progression, and efficient decision-making rather than decorative analytics.

### P5 - Intelligence

Use for:

- E01-E07

Prompt:

> Design an intelligence page for Retail IQ that turns business data into a readable, premium analytics experience. Use a strong page header, disciplined KPI strip, clear filters, and high-clarity charts. The aesthetic should feel refined and calm. Use annotations and summaries to explain movement. Avoid flashy BI-dashboard tropes.

### P6 - Platform

Use for:

- F01-F09

Prompt:

> Design a platform page for Retail IQ covering data sources, imports, developer activation, monitoring, or public status. The page should feel precise, technical, and trustworthy. Borrow the clarity of Stripe’s technical surfaces without copying them literally. Use structured setup sections, code surfaces, split workspaces, status banners, and one-time secret reveal patterns where relevant.

### P7 - Admin

Use for:

- G01-G13

Prompt:

> Design an admin or governance page for Retail IQ. This includes company profile, billing, plans, outcome pricing, team, tenant console, security, audit, trust, and account settings. The experience should feel highly trustworthy, policy-aware, and enterprise-safe. Use strong sectioning, explicit labels, contextual banners, and structured forms or tables. Avoid consumer settings aesthetics.

### P8 - Global States And Utilities

Use for:

- H01-H05

Prompt:

> Design a shared state or utility surface for Retail IQ, such as loading, empty, error, no-permission, degraded-live, or command palette results. The surface must feel like part of the same premium system. Match the parent page structure, explain the state clearly, and provide one obvious next move. Never use generic sad-empty-state art.

## 7. Component Inclusion Rules

When generating a page, pull only from the approved component families in `COMPONENT_LIBRARY.md`.

Default composition rules:

- Home pages use `Hero Verdict`, `Metric Strip`, `AI Summary Band`, and 2-4 modules
- Workflows use `Page Header`, `Filter Bar`, `Workflow Queue Item` or card family, and `Detail Drawer`
- Operations use `Page Header`, `Filter Bar`, `Entity Table` or queue, and supporting status modules
- Intelligence pages use `Page Header`, `Metric Strip`, `Chart Frame`, and optional summary band
- Platform pages use `Split Workspace`, `Enterprise Form Section`, `Code Snippet`, `Status Banner`, and tables
- Admin pages use `Page Header`, structured sections, `Entity Table`, `Status Banner`, and trust copy modules

## 8. Role Modifiers

Append one of these to the page-family prompt.

### Executive modifier

> This page is for a senior executive. Lead with one key decision or business implication. Reduce noise. Show money impact clearly and avoid operational clutter.

### Regional manager modifier

> This page is for a regional manager. Emphasize comparison, prioritization, and routing attention across stores. Keep the page action-oriented.

### Store manager modifier

> This page is for a store manager. Prioritize immediate actions, stock clarity, alert recovery, and simple operational language.

### Procurement modifier

> This page is for an operations or procurement power user. Optimize for lifecycle clarity, status progression, line-item review, and transaction confidence.

### Tenant admin modifier

> This page is for an administrator responsible for governance and configuration. Increase policy clarity, status visibility, and change-safety cues.

### Developer modifier

> This page is for a technical integrator. Increase precision, code readability, request/response clarity, and setup transparency.

## 9. Domain-Specific Guardrails

### Home

- one hero only
- no more than 4 top-level modules before scrolling
- AI supports the page, but does not replace all structure

### Workflows

- prioritize queue scanning over charts
- use confidence and evidence consistently
- preserve context with drawer/detail patterns

### Operations

- prefer tables and structured review over large decorative cards
- make transaction state obvious
- keep primary actions close to affected data

### Intelligence

- fewer charts, better charts
- annotate the insight
- separate units and AED cleanly

### Platform

- use technical precision
- show setup steps clearly
- use secret-reveal and test-result patterns consistently

### Admin

- make destructive or risky changes visually cautious
- explain policy, ownership, and impact
- keep trust and governance easy to find

## 10. Screen-To-Prompt Mapping

| Screen IDs | Prompt Family |
|---|---|
| A01-A08 | P1 |
| B01-B09 | P2 |
| C01-C09 | P3 |
| D01-D10 | P4 |
| E01-E07 | P5 |
| F01-F09 | P6 |
| G01-G13 | P7 |
| H01-H05 | P8 |

## 11. High-Value Page Recipes

### Today - Executive

Use:

- `S0` + `P0` + `P2` + executive modifier

Add:

> Route: `/today`. Show a premium hero verdict, one focal decision, a compact money-and-risk strip, and supporting modules for decisions, insights, and trust-worthy freshness. Do not design this like a sprawling analytics dashboard.

### Decisions - Regional Manager

Use:

- `S0` + `P0` + `P3` + regional manager modifier

Add:

> Route: `/decisions`. Show priority lanes, severity, impact, confidence, evidence, and clear next actions. Include detail drawer behavior and outcome history state.

### Procurement Overview

Use:

- `S0` + `P0` + `P4` + procurement modifier

Add:

> Route: `/procurement`. Support reorder suggestions, purchase-order queue, supplier view, invoice matching entry points, and receiving state. Keep the page efficient and transaction-focused.

### Developer Portal Overview

Use:

- `S0` + `P0` + `P6` + developer modifier

Add:

> Route: `/developers`. Include API key setup, webhooks, playground, and embed guidance. Use calm technical hierarchy and clear one-time secret reveal behavior.

### Billing And Plans

Use:

- `S0` + `P0` + `P7` + tenant admin modifier

Add:

> Routes: `/settings/billing` and `/pricing`. Separate subscription overview, invoice list, invoice detail, and plan context into structured sections. This must feel like enterprise billing, not a SaaS marketing checkout.

### Trust Center

Use:

- `S0` + `P0` + `P7` + tenant admin modifier

Add:

> Route: `/trust`. Organize content into isolation, access, auditability, system operations, and commitments. Make it readable for both technical and non-technical stakeholders.

## 12. Anti-Patterns For Stitch

Do not generate:

- dark fintech dashboards
- purple-primary visual systems
- consumer app settings pages
- giant card mosaics with no hierarchy
- chatbot playground styling for Sage
- charts with rainbow palettes and no annotations
- dense tables without empty, loading, or error states

## 13. Recommended Workflow

1. Start with `S0`.
2. Add `P0`.
3. Add the page-family prompt.
4. Add one role modifier.
5. Add route, purpose, and backend constraints.
6. Add required components.
7. Add required states.
8. Review against `SCREEN_INVENTORY.md` and `DESIGN_SYSTEM.md` before accepting output.

## 14. Future Enhancements

- `[Future Enhancement]` prompt pack for supplier-facing portal screens
- `[Future Enhancement]` prompt pack for finance and category-manager roles
- `[Future Enhancement]` motion-only prompt addendum after implementation primitives are finalized

