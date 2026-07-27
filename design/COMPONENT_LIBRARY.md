# Component Library

## 1. Purpose

This library defines the reusable building blocks required to make the redesigned product feel coherent across all domains.

Every component should specify:

- purpose
- required parts
- variants
- states
- accessibility notes

## 2. Shell Components

### 2.1 App Shell

Purpose:

- stable frame for all authenticated work

Required parts:

- domain rail
- context rail
- top utility bar
- main content region
- global overlays

### 2.2 Domain Rail

Required parts:

- domain icon
- label in expanded mode
- active indicator

Variants:

- expanded
- collapsed
- mobile drawer

### 2.3 Context Rail

Purpose:

- list domain pages and grouped sections

Required parts:

- section label
- page item
- active state
- optional badge count

### 2.4 Top Utility Bar

Required parts:

- command palette trigger
- notifications trigger
- scope chip
- language control
- account menu
- Sage launcher

## 3. Navigation And Context Components

### 3.1 Scope Chip

Purpose:

- show current tenant / region / store scope clearly

Rules:

- must never be ambiguous
- must be readable in narrow widths

### 3.2 Command Palette

Required parts:

- search input
- grouped results
- keyboard hint
- no-results state

### 3.3 Notification Tray

Purpose:

- lightweight global awareness, not a second workflow center

## 4. Page Structure Components

### 4.1 Page Header

Required parts:

- title
- supporting description
- primary action
- optional secondary actions

### 4.2 Section Header

Required parts:

- section title
- short context line
- optional action or filter summary

### 4.3 Hero Verdict

Use for:

- Today
- Executive Briefing
- Copilot
- Public Status

Required parts:

- summary sentence
- role or system identity
- key CTA
- supporting chips or evidence

### 4.4 Metric Strip

Purpose:

- orient quickly beneath a page header or hero

Rules:

- 3-6 items
- shared alignment and formatting

## 5. Data Display Components

### 5.1 KPI Card

Variants:

- standard
- focal
- compact
- status

### 5.2 Chart Frame

Required parts:

- title
- subtitle
- chart body
- annotation or note
- optional live badge

### 5.3 Entity Table

Purpose:

- reusable structured table for admin, developer, inventory, and billing surfaces

Required parts:

- header row
- empty state slot
- loading slot
- row action slot

### 5.4 Status Pill

Purpose:

- communicate state consistently across workflows

Variants:

- success
- warning
- danger
- info
- neutral

## 6. Workflow Components

### 6.1 Workflow Queue Item

Purpose:

- shared scaffold for decisions, findings, approvals, and drafts

Required parts:

- severity or status
- title
- scope
- impact
- evidence summary
- primary action

### 6.2 Decision Card

Required parts:

- recommendation
- confidence
- evidence
- expected impact
- approve / dismiss / review actions

Variants:

- executive
- operational
- compact queue
- measured outcome

### 6.3 Finding Card

Required parts:

- issue summary
- category
- evidence
- suggested next step
- outcome block when closed or measured

### 6.4 Approval Card

Required parts:

- object name
- affected scope
- value or risk summary
- approver actions

### 6.5 Draft Card

Required parts:

- generated action type
- preview
- source object
- approve / reject controls

### 6.6 Outcome Block

Purpose:

- show whether an accepted action improved, worsened, or has not yet changed the metric

## 7. Operational Workspace Components

### 7.1 Filter Bar

Required parts:

- search
- tabs or segmented control
- filters
- optional date range

### 7.2 Detail Drawer

Purpose:

- preserve list context while reviewing detail

### 7.3 Split Workspace

Use for:

- imports
- developers
- tenant console
- procurement detail-heavy tasks

### 7.4 Timeline / Audit Trail

Use for:

- purchase orders
- tenant lifecycle
- audit logs
- webhook deliveries

### 7.5 Invoice Match Panel

Purpose:

- compare invoice, purchase order, and matching state without jumping pages

## 8. Form And Setup Components

### 8.1 Enterprise Form Section

Required parts:

- section title
- short guidance
- grouped fields
- validation area

### 8.2 Stepper

Use for:

- onboarding
- imports
- connection setup

### 8.3 Connection Test Result

Required parts:

- success or failure state
- diagnostic message
- next action

### 8.4 Secret Reveal Dialog

Purpose:

- one-time reveal of API keys or secrets

Required parts:

- reveal value
- copy action
- warning text
- dismissal action

## 9. AI Components

### 9.1 AI Summary Band

Purpose:

- concise inline synthesis on non-AI-first pages

### 9.2 AI Answer Block

Required parts:

- verdict
- evidence
- confidence
- scope or freshness note
- next step

### 9.3 Chat Panel

Required parts:

- persona header
- transcript
- suggested prompts
- input
- streaming answer state
- evidence area

### 9.4 Copilot Feed Widget

Widget families:

- business health
- risk
- opportunity
- recommendation

## 10. System State Components

### 10.1 Status Banner

Variants:

- info
- success
- warning
- degraded
- error

### 10.2 Empty State

Required parts:

- title
- explanation
- one next action

### 10.3 Error State

Required parts:

- what failed
- what to do next
- retry or escape route

### 10.4 No-Permission State

Required parts:

- clear boundary statement
- next step or who can help

### 10.5 Loading Skeleton

Rules:

- match final structure
- avoid spinner-only pages except for tiny actions

## 11. Accessibility Notes

Required across components:

- semantic labels for icon-only controls
- keyboard operability for drawers and menus
- sufficient contrast in status pills and banners
- screen-reader-friendly live regions for AI and live updates
- focus return after closing modal or drawer

## 12. Future Enhancements

- `[Future Enhancement]` unified work-object component across alerts, decisions, approvals, and drafts
- `[Future Enhancement]` collaboration comments and mentions
- `[Future Enhancement]` supplier-facing component set
