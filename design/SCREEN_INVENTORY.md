# Screen Inventory

## 1. Scope

This inventory defines **70 production-relevant screens and states** for the redesigned experience.

It includes:

- core business screens
- role variants
- onboarding and account flows
- enterprise admin and platform surfaces
- loading, empty, error, search, and no-permission states

Status legend:

- `Existing` = backed by a current route or backend-supported UI surface
- `Reframe` = existing capability that needs a different information architecture or visual treatment
- `State` = required UI state for an existing surface
- `Future` = reserve only; do not present as current capability

## 2. Access And Activation

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| A01 | Login | `/login` | Existing | Primary authentication entry |
| A02 | MFA Verification | `/login` state | Existing | TOTP challenge flow |
| A03 | Sign Up Workspace | `/signup` | Existing | New workspace creation |
| A04 | Accept Invite | `/accept-invite` | Existing | Invite token acceptance |
| A05 | Verify Email | `/verify-email` | Existing | Verification completion |
| A06 | Reset Password | `/reset-password` | Existing | Password recovery completion |
| A07 | Welcome | `/welcome` | Reframe | First-run orientation surface |
| A08 | Onboarding Checklist | `/welcome` + `/api/auth/onboarding` | Reframe | Progress-driven activation hub |

## 3. Home

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| B01 | Today - Executive | `/today` | Existing | `super_admin` daily home |
| B02 | Today - Regional | `/today` | Existing | `regional_manager` daily home |
| B03 | Today - Store | `/today` | Existing | `store_manager` daily home |
| B04 | Today - Experience Fallback | `/today` state | State | Missing or degraded experience manifest |
| B05 | Executive Briefing | `/briefing` | Existing | Premium AI editorial brief |
| B06 | Briefing - Loading | `/briefing` state | State | Structured reading skeleton |
| B07 | Briefing - Empty | `/briefing` state | State | No reliable brief yet |
| B08 | Sage Copilot | `/copilot` | Existing | Proactive AI workspace |
| B09 | Global Sage Chat Panel | global AI surface | Reframe | Shared ask/explain layer across the app |

## 4. Workflows

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| C01 | Decisions - Triage | `/decisions` | Existing | Priority queue for review |
| C02 | Decisions - Outcomes | `/decisions` tab/filter | Existing | Measured post-decision state |
| C03 | Decision Detail Drawer | `/decisions` state | Reframe | In-context review without losing queue position |
| C04 | Insights - Open Findings | `/insights` | Existing | Diagnostic queue |
| C05 | Insights - Resolved / Outcomes | `/insights` filter | Existing | Findings that were measured or closed |
| C06 | Alerts Feed | `/alerts` | Existing | Cross-surface risk feed |
| C07 | Alert Resolution / Rule Modal | `/alerts` state | Existing | Resolve, suppress, or inspect rule behavior |
| C08 | Approval Inbox | `/approvals` | Existing | Review queue for approval-worthy actions |
| C09 | Action Drafts Queue | `/action-drafts` | Existing | Human-reviewed draft actions |

## 5. Operations

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| D01 | Inventory Overview | `/inventory` | Existing | Stock posture and operational entry point |
| D02 | Inventory Transfers | `/inventory` state | Existing | Cross-location transfer workflow |
| D03 | Inventory Batches And Expiry | `/inventory` state | Existing | Batch-level expiry and stock detail |
| D04 | Procurement Overview | `/procurement` | Existing | Reorder, approvals, and PO management |
| D05 | Supplier Directory | `/procurement` suppliers state | Existing | Supplier list and onboarding surface |
| D06 | Purchase Order Detail | `/procurement/po/[id]` | Existing | PO lifecycle and line detail |
| D07 | PO Receiving | `/procurement/po/[id]` receive state | Existing | Receiving confirmation and audit trail |
| D08 | Supplier Invoice Matching | `/procurement` invoices state | Existing | Match and review supplier invoices |
| D09 | Promotions Workspace | `/promotions` | Existing | Campaign and pricing management |
| D10 | Workforce Overview | `/employees` | Existing | Employee performance and staffing visibility |

## 6. Intelligence

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| E01 | Analytics Overview | `/analytics` | Existing | Primary business analysis surface |
| E02 | Analytics - Region / Store Compare | `/analytics` state | Reframe | Comparison-led variant for managers |
| E03 | Forecast Lab | `/forecast-lab` | Existing | Forecast diagnostics and accuracy |
| E04 | Forecast Lab - Insufficient Model Metrics | `/forecast-lab` state | State | Sparse or incomplete model state |
| E05 | Reports Workspace | `/reports` | Existing | Export and report browsing surface |
| E06 | Value / ROI | `/value` | Existing | Opportunity quantification in AED |
| E07 | UAE Insights | `/uae-insights` | Existing | Local seasonality and regional context |

## 7. Platform

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| F01 | Data Sources Overview | `/data-sources` | Existing | Registry of connected and staged sources |
| F02 | Add / Test Data Source | `/data-sources` state | Existing | Connection setup and test workflow |
| F03 | Imports - Analyze And Map | `/imports` | Existing | File analysis and field mapping |
| F04 | Imports - Validate And Commit | `/imports` state | Existing | Validation review and import commit |
| F05 | Imports History | `/imports` section/state | Existing | Past jobs and outcomes |
| F06 | Developer Portal Overview | `/developers` | Existing | Activation hub for technical users |
| F07 | API Keys Workspace | `/developers` tab | Existing | Create, reveal, and revoke key workflows |
| F08 | Webhooks And Deliveries | `/developers` tab | Existing | Endpoint config, test send, delivery history |
| F09 | Monitoring And Public Status | `/monitoring`, `/status` | Existing | Internal operational health and public status communication pair |

## 8. Admin

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| G01 | Admin Overview | `/admin` | Existing | Organization-level summary and controls |
| G02 | Tenant Console | `/admin/tenants` | Existing | Multi-tenant lifecycle management |
| G03 | Tenant Lifecycle Detail | `/admin/tenants` state | Existing | Status history, notes, and lifecycle events |
| G04 | Company Profile | `/settings/company` | Existing | Legal and organization details |
| G05 | Billing And Plans | `/settings/billing`, `/pricing` | Reframe | Subscription, plan context, and invoice access |
| G06 | Invoice Detail / Print | `/settings/billing` state | Existing | View, print, issue, and mark-paid paths |
| G07 | Outcome Pricing | `/outcome-pricing` | Existing | Savings-share pricing narrative/workflow |
| G08 | Team Management | `/settings/team` | Existing | Seats, invites, roles, status |
| G09 | Security Overview | `/security` | Existing | Security KPIs and event posture |
| G10 | Security Events / Export | `/security` state | Existing | Investigate and export security evidence |
| G11 | Audit Log | `/audit` | Existing | Exportable governance trail |
| G12 | Trust Center | `/trust` | Existing | Tenant isolation and governance explanation |
| G13 | Account And Preferences | `/profile`, `/settings` | Reframe | Utility-layer account and preference surfaces |

## 9. Global States And Utilities

| ID | Screen | Route | Status | Notes |
|---|---|---|---|---|
| H01 | Global Loading / Skeleton System | shared state | State | Page-structured loading, never generic spinner-only |
| H02 | Empty / First-Useful-State | shared state | State | Explain absence and offer one next step |
| H03 | Error / Degraded Live Connection | shared state | State | Includes stream reconnect and retry guidance |
| H04 | No-Permission State | shared state | State | Respect backend role boundaries clearly |
| H05 | Command Palette / Search Results | utility surface | Reframe | Search for pages, objects, and actions |

## 10. Priority Release Sequence

If implementation proceeds in phases, ship in this order:

1. B01-B09
2. C01-C09
3. D01-D08
4. F01-F09
5. G04-G13
6. E01-E07
7. H01-H05

## 11. Reserved Screens

These may be represented only when clearly labeled:

- `[Future]` Unified `My Work` inbox
- `[Future]` Supplier portal
- `[Future]` Dedicated SSO/SCIM setup console
- `[Future]` Category-manager workspace
- `[Future]` Autonomous low-risk execution center

