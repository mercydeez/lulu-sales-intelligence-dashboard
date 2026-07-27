# Design System

## 1. Purpose

This system defines the implementation-ready rules for the redesigned Retail IQ experience.

It must produce:

- one coherent visual and interaction language
- reusable patterns for Home, Workflows, Operations, Intelligence, Platform, and Admin
- WCAG AA-compliant behavior
- a clean bridge from the current Tailwind-based frontend to a more disciplined shadcn/ui-style system

## 2. Implementation Stance

Use:

- Next.js 14 App Router
- Tailwind CSS tokens and utilities
- shadcn/ui-style primitives and composition patterns
- existing custom components only when wrapped into the new system grammar

Do not:

- rewrite the entire app at once
- create page-specific one-off component families
- allow visual drift between AI, admin, and operational surfaces

## 3. Core Tokens

### 3.1 Color tokens

Foundation:

- `--canvas`
- `--surface`
- `--surface-elevated`
- `--surface-tint`
- `--line`
- `--ink`
- `--ink-soft`
- `--ink-muted`

Brand:

- `--brand-50`
- `--brand-100`
- `--brand-600`
- `--brand-700`

Semantic:

- `--success-50`, `--success-600`
- `--warning-50`, `--warning-700`
- `--danger-50`, `--danger-600`
- `--info-50`, `--info-600`
- `--ai-50`, `--ai-600`

Utility:

- `--focus-ring`
- `--overlay-scrim`
- `--live-pulse`
- `--chart-grid`

### 3.2 Spacing scale

Base scale is 8px with specific named steps:

- `4` micro gap
- `8` tight gap
- `12` form gap
- `16` component gap
- `24` card padding
- `32` section gap
- `48` page gap
- `64` hero gap

### 3.3 Radius scale

- `12` controls
- `16` inputs and tables
- `20` standard cards
- `24` hero and focal modules
- `9999` pills and status chips

### 3.4 Elevation scale

- `level-1` default cards
- `level-2` drawers and sticky bars
- `level-3` modals and key overlays

### 3.5 Motion scale

- `120ms` micro feedback
- `180ms` hover/focus state
- `220ms` modal, drawer, and panel transitions
- `250ms` max perceived page-entry motion

## 4. Typography System

### 4.1 Font families

- UI and display: `Manrope`
- Arabic UI companion: `IBM Plex Sans Arabic` or `Noto Sans Arabic`
- Mono and tabular numerals: `IBM Plex Mono`

### 4.2 Hierarchy

- display: hero verdicts and major numbers only
- h1: page title
- h2: section owner
- h3: module title
- label: metadata and table headers
- body: operational copy
- mono: code, IDs, values that benefit from tabular reading

### 4.3 Rules

- use sentence case for almost everything
- keep headings short and specific
- use tabular numerals for KPIs, tables, invoices, and code-adjacent values
- attach unit labels close to the number

## 5. Shell Specifications

### 5.1 Primary domain rail

Desktop variants:

- collapsed icon rail
- expanded rail with domain labels

Rules:

- max six domains visible
- show role-allowed domains only
- active domain gets a clear, high-contrast indicator

### 5.2 Context rail

Purpose:

- expose child pages, domain sections, and contextual tabs

Rules:

- group long lists into labeled sections
- preserve location context while deep-linking into detail pages
- never duplicate the entire primary rail

### 5.3 Top utility bar

Contains:

- command palette entry
- notifications
- scope chip
- language switcher
- account menu
- Sage launcher

Rules:

- utility controls remain consistent across all domains
- account and preferences live here, not in the main rail

## 6. Page Templates

### 6.1 Home template

Structure:

- hero verdict or summary
- compact metric strip
- 2-4 priority modules
- supporting AI or workflow module

Use for:

- Today
- Executive Briefing
- Sage Copilot

### 6.2 Workflow template

Structure:

- page header
- list filters or tabs
- priority queue
- detail drawer or side panel

Use for:

- Decisions
- Insights
- Alerts
- Approvals
- Action Drafts

### 6.3 Operations workspace template

Structure:

- page header
- status strip or KPI band when useful
- filters
- table or queue
- detail surface for transaction review

Use for:

- Inventory
- Procurement
- Promotions
- Workforce

### 6.4 Intelligence template

Structure:

- page header
- filters
- KPI strip
- 2-4 disciplined chart frames
- supporting notes or summary band

Use for:

- Analytics
- Forecast Lab
- Reports
- Value
- UAE Insights

### 6.5 Platform / Admin template

Structure:

- page header
- explanatory trust or system banner when needed
- primary table or structured sections
- optional detail pane, code block, or form sections

Use for:

- Data Sources
- Imports
- Developers
- Monitoring
- Billing
- Team
- Security
- Audit

## 7. Density Modes

Two supported density modes:

- `comfortable` for Home, Workflows, Trust, and Briefing
- `compact` for admin tables, developer tools, imports, and monitoring

Do not create page-specific density experiments outside these modes.

## 8. Tables, Lists, And Data Display

### 8.1 Tables

Required behavior:

- sticky headers where lists scroll
- sortable headers only when backend semantics are clear
- right-aligned numeric columns
- action column aligned consistently on the right
- empty and loading states inside the table frame

### 8.2 Charts

Required behavior:

- title, subtitle, and scope
- readable axes
- annotation-led storytelling
- no more than one dominant series per frame unless comparison is the point
- legends or direct labels beyond color alone

### 8.3 KPI strips

Rules:

- 3-6 items maximum
- use for orientation, not exhaustive measurement
- never mix units and AED without clear separation

## 9. Forms, Dialogs, And Destructive Actions

### 9.1 Forms

Rules:

- split long forms into titled sections
- put helper text near the field it explains
- reserve inline validation for field-specific issues
- use summary banners for cross-form problems

### 9.2 Dialogs and drawers

Use drawers for:

- reviewing list items without losing queue context
- transaction details
- edit-in-place workflows

Use dialogs for:

- confirmations
- one-time secret reveal
- destructive actions
- short focused forms

### 9.3 Destructive actions

Rules:

- isolate visually
- require explicit language
- never style destructive actions like primary success CTAs

## 10. State System

Every major surface must specify:

- loading
- empty
- error
- degraded connection where relevant
- no permission
- success or completion confirmation where relevant

Rules:

- loading mirrors final layout
- empty states explain why content is absent
- error states preserve context and offer retry
- no-permission states explain the boundary without leaking hidden data

## 11. Accessibility Requirements

Required product-wide behavior:

- visible focus ring on every interactive element
- keyboard traversal for nav, tables, drawers, dialogs, and chat
- semantic landmarks for shell and page sections
- chart alternatives via labels, notes, or accessible data views
- screen-reader-safe live regions for SSE and AI streaming
- 44px minimum touch target in responsive layouts
- reduced motion support for page and component transitions
- logical-property-ready spacing and alignment for RTL

## 12. Responsive Rules

The product is desktop-first, but must remain workable on smaller screens.

### 12.1 Desktop

- full domain rail
- context rail or secondary nav visible
- split panes where useful

### 12.2 Tablet

- domain rail may collapse
- context rail can become tab row or drawer
- two-column home modules can stack to one-column where needed

### 12.3 Mobile support

- prioritize read, approve, inspect, and quick-operate tasks
- keep transactions concise
- avoid multi-pane mental models
- preserve `Today`, `Briefing`, approvals, and key inventory actions first

## 13. Adoption Plan

### Phase 1

- unify taxonomy and page templates
- introduce shell, token, and state system

### Phase 2

- rebuild Home and Workflows with the new primitives
- standardize tables, drawers, and AI answer blocks

### Phase 3

- migrate Operations and Platform surfaces
- align Admin and Trust flows

### Phase 4

- refine Intelligence pages
- tune density, accessibility, and responsive behaviors

## 14. Future Enhancements

- `[Future Enhancement]` analyst-grade dense data-grid mode
- `[Future Enhancement]` collaborative comments and mentions
- `[Future Enhancement]` advanced chart annotations for board/reporting workflows
