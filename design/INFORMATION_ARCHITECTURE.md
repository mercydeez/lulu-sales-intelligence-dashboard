# Information Architecture

## 1. IA Objective

Transform Retail IQ from a flat route list into a domain-led enterprise product that is easier to learn, faster to act in, and cleaner to scale.

The IA must:

- reflect user jobs instead of implementation modules
- reduce top-level nav sprawl
- preserve existing route compatibility during transition
- remain truthful to backend permissions and route support
- separate business work from governance work

## 2. Canonical Domain Model

Retail IQ should use six product domains:

1. `Home`
2. `Workflows`
3. `Operations`
4. `Intelligence`
5. `Platform`
6. `Admin`

### 2.1 Home

Purpose:

- orient the user quickly
- establish daily priorities
- surface AI synthesis

Contains:

- Today
- Executive Briefing
- Sage Copilot

### 2.2 Workflows

Purpose:

- hold reviewable work and decision queues

Contains:

- Decisions
- Insights
- Alerts
- Approvals
- Action Drafts

### 2.3 Operations

Purpose:

- execute operating work

Contains:

- Inventory
- Procurement
- Promotions
- Workforce

Operational sub-objects surfaced inside the domain:

- suppliers
- purchase orders
- receiving
- invoice matching

### 2.4 Intelligence

Purpose:

- analyze and explain business movement

Contains:

- Analytics
- Forecast Lab
- Reports
- Value
- UAE Insights

### 2.5 Platform

Purpose:

- connect systems
- ingest data
- support developers
- monitor runtime health

Contains:

- Data Sources
- Imports
- Developer Portal
- Monitoring
- Public Status

### 2.6 Admin

Purpose:

- govern tenant, organization, billing, and trust

Contains:

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

## 3. Navigation Model

### 3.1 Global shell

The shell should use:

- left domain rail for the six domains only
- context rail for domain pages and tabs
- top utility bar for global actions

### 3.2 Top utility bar

Always-available utilities:

- command palette / search
- notifications
- scope chip
- language switcher
- account menu
- Sage launcher

### 3.3 What should not live in primary nav

These should be nested, utility-accessed, or contextual:

- profile
- preferences
- pricing details
- public status
- invoice print views
- modals such as API-key reveal or data-source test results

## 4. Placement Decisions That Resolve Current Drift

These are the canonical placements for the redesign:

- `Monitoring` belongs to `Platform`, not `Intelligence`
- `Security`, `Audit`, and `Trust` belong to `Admin`, not mixed with Platform or Analytics
- `Reports` belongs to `Intelligence`, not `Operations`
- `Billing`, `Pricing`, and `Outcome Pricing` belong to one `Billing and Plans` area under `Admin`
- `Profile` and `Preferences` belong in the account utility layer, not as prominent left-rail items
- `/today` is the canonical authenticated landing page; `/` is transitional compatibility, not the long-term IA anchor

## 5. Role-Based Nav Manifests

### 5.1 Executive / tenant owner

Primary domains:

- Home
- Workflows
- Intelligence
- Platform
- Admin

Default landing:

- Today or Executive Briefing

Visible pages:

- Today
- Executive Briefing
- Copilot
- Decisions
- Insights
- Analytics
- Reports
- Value
- Monitoring
- Billing and Plans
- Team
- Trust

### 5.2 Regional manager

Primary domains:

- Home
- Workflows
- Operations
- Intelligence

Default landing:

- Today

Visible pages:

- Today
- Decisions
- Insights
- Alerts
- Approvals
- Inventory
- Procurement
- Analytics
- Reports
- UAE Insights

### 5.3 Store manager

Primary domains:

- Home
- Workflows
- Operations

Default landing:

- Today

Visible pages:

- Today
- Alerts
- Approvals
- Decisions
- Inventory
- Procurement

### 5.4 Procurement / operations power user

Primary domains:

- Home
- Workflows
- Operations
- Intelligence

Visible pages:

- Today
- Approvals
- Decisions
- Procurement
- Inventory
- Value
- Reports

### 5.5 Tenant admin / platform operator

Primary domains:

- Platform
- Admin

Default landing:

- Monitoring or Admin Overview

Visible pages:

- Data Sources
- Imports
- Developer Portal
- Monitoring
- Company
- Billing and Plans
- Team
- Security
- Audit
- Trust

### 5.6 Developer / integrator

Primary domains:

- Platform

Default landing:

- Developer Portal

Visible pages:

- Developer Portal
- API Keys
- Webhooks
- Playground
- Embed Sage
- Monitoring

## 6. Content Taxonomy

### 6.1 Core objects

- Tenant
- User
- Role
- Region
- Store
- Item / SKU
- Alert
- Finding
- Decision
- Action Draft
- Supplier
- Purchase Order
- Invoice
- Import Job
- Data Source
- API Key
- Webhook

### 6.2 Canonical verbs

- Review
- Investigate
- Approve
- Dismiss
- Draft
- Resolve
- Connect
- Import
- Export
- Measure

Do not introduce casual synonyms for these verbs when the action model is the same.

## 7. Search And Command Palette

The command palette should index:

- destinations
- recent pages
- stores and regions
- decisions and findings
- purchase orders
- developer surfaces
- AI prompt starters

Suggested result groups:

- Navigate
- Review
- Operate
- Configure
- Ask Sage

## 8. Route Mapping

| Current Route | Future Domain | Future Placement |
|---|---|---|
| `/` | Home | Transitional redirect to Today |
| `/today` | Home | Today |
| `/briefing` | Home | Executive Briefing |
| `/copilot` | Home | Sage Copilot |
| `/decisions` | Workflows | Decisions |
| `/insights` | Workflows | Insights |
| `/alerts` | Workflows | Alerts |
| `/approvals` | Workflows | Approvals |
| `/action-drafts` | Workflows | Action Drafts |
| `/inventory` | Operations | Inventory |
| `/procurement` | Operations | Procurement |
| `/promotions` | Operations | Promotions |
| `/employees` | Operations | Workforce |
| `/analytics` | Intelligence | Analytics |
| `/forecast-lab` | Intelligence | Forecast Lab |
| `/reports` | Intelligence | Reports |
| `/value` | Intelligence | Value |
| `/uae-insights` | Intelligence | UAE Insights |
| `/data-sources` | Platform | Data Sources |
| `/imports` | Platform | Imports |
| `/developers` | Platform | Developer Portal |
| `/monitoring` | Platform | Monitoring |
| `/status` | Platform | Public Status |
| `/admin` | Admin | Admin Overview |
| `/admin/tenants` | Admin | Tenant Console |
| `/settings/company` | Admin | Company |
| `/settings/billing` | Admin | Billing and Plans |
| `/pricing` | Admin | Billing and Plans |
| `/outcome-pricing` | Admin | Outcome Pricing |
| `/settings/team` | Admin | Team |
| `/security` | Admin | Security |
| `/audit` | Admin | Audit |
| `/trust` | Admin | Trust |
| `/profile` | Admin utility | Account |
| `/settings` | Admin utility | Preferences |

## 9. IA Simplification Rules

- no more than six primary domains
- no more than seven visible child entries in a context rail before tabs/grouping
- public-facing and print routes should not inflate the primary nav
- monitoring, trust, billing, and developer flows should remain easy to find without dominating business-work pages

## 10. Future Enhancements

- `[Future Enhancement]` unified `My Work` route spanning decisions, approvals, alerts, and drafts
- `[Future Enhancement]` dedicated finance and category-manager navigation variants
- `[Future Enhancement]` supplier-facing portal with its own information architecture
