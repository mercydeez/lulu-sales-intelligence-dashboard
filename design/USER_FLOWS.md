# User Flows

## 1. Flow Standards

Every production flow in this spec must:

- start from an existing backend-backed route or action
- end in a visible outcome, saved state, or next step
- make role scope obvious
- include unhappy-path handling
- avoid implying autonomy the backend does not support

## 2. Workspace Activation

### Actors

- new tenant owner

### Current support

- `/api/auth/signup`
- `/api/auth/onboarding`
- `/api/tenants/billing-profile`
- `/api/imports/*`
- `/api/team`

### Flow

1. User signs up and creates a workspace.
2. Product lands the user in `Welcome`.
3. `Onboarding Checklist` shows only the next 3-4 steps, not every possible setup task.
4. User completes company profile.
5. User chooses one data path:
   - connect a data source
   - import CSV
   - continue with seeded/demo data if already available
6. User invites at least one teammate.
7. Product routes the user to `Today` and optionally `Executive Briefing`.

### Unhappy paths

- invite later
- no data yet
- import validation errors

### UX requirement

Value should feel reachable in under ten minutes without making setup feel shallow.

## 3. Login And MFA

### Current support

- `/api/auth/login`
- `/api/auth/2fa/verify`
- `/api/auth/forgot-password`
- `/api/auth/reset-password`
- `/api/auth/verify-email`

### Flow

1. User submits credentials.
2. If MFA is enabled, system requests TOTP code.
3. User verifies the code.
4. Product routes to role-appropriate `Today`.

### Unhappy paths

- invalid credentials
- expired code
- unverified email
- locked or inactive account state

### UX requirement

Security should feel premium and reliable, not punitive.

## 4. Daily Start By Role

### Current support

- `/api/experience`
- `/today`
- `/api/briefing`
- `/api/decisions/triage`

### Flow

1. User lands on `Today`.
2. Page establishes role scope and freshness.
3. User sees one primary priority and 2-4 supporting modules.
4. User jumps into one of:
   - `Briefing`
   - `Decisions`
   - `Approvals`
   - `Inventory`

### UX requirement

`Today` should reduce, not expand, the number of choices a user has to parse first.

## 5. Executive Brief To Decision

### Current support

- `/api/briefing`
- `/api/decisions/triage`
- `/api/decisions`
- `/api/findings/*`

### Flow

1. Executive opens `Executive Briefing`.
2. Sage provides a verdict, one focal decision, and supporting evidence.
3. User opens the decision detail drawer without leaving the context of the brief.
4. User approves, dismisses, or routes attention.
5. Decision appears in `Outcomes` once measured.

### Unhappy paths

- no meaningful brief available
- low-confidence recommendation
- user lacks permission to take the recommended action

## 6. Findings To Drafted Action

### Current support

- `/api/findings`
- `/api/findings/{id}/accept-action`
- `/api/action-drafts/from-finding/{id}`
- `/api/action-drafts`

### Flow

1. User opens `Insights`.
2. User filters to a high-confidence finding.
3. User reviews evidence and recommendation.
4. User accepts the action or creates an action draft.
5. Draft appears in `Action Drafts`.
6. User approves or rejects the draft.

### UX requirement

This flow must stay explicitly human-in-the-loop at every step.

## 7. Approval Workflow

### Current support

- `/api/procurement/approvals`
- `/api/decisions/triage`
- `/approvals`

### Flow

1. User enters `Approval Inbox`.
2. Items are grouped by urgency and impact.
3. User reviews details in drawer or side panel.
4. User approves, defers, or rejects.
5. Product shows updated status and downstream effect.

### Unhappy paths

- permission mismatch
- stale approval state
- missing supporting context

## 8. Reorder To PO To Receive

### Current support

- `/api/inventory/reorder-suggestions`
- `/api/procurement/purchase-orders/generate`
- `/api/procurement/purchase-orders`
- `/api/procurement/purchase-orders/{id}`
- `/api/procurement/purchase-orders/{id}/status`
- `/api/procurement/purchase-orders/{id}/receive`

### Flow

1. User opens `Procurement`.
2. User generates draft purchase orders from reorder suggestions.
3. User reviews the queue and opens a PO detail.
4. User changes status through the approved lifecycle.
5. User receives the order.
6. Audit trail reflects each transition.

### UX requirement

The product should make lifecycle progress obvious without turning the page into ERP-style clutter.

## 9. Supplier Invoice Matching

### Current support

- `/api/procurement/invoices`
- `/api/procurement/purchase-orders/{po_id}/invoices`
- `/api/procurement/invoices/{invoice_id}/match`

### Flow

1. User opens invoice matching inside `Procurement`.
2. User reviews unmatched or pending supplier invoices.
3. User opens detail and compares invoice to PO.
4. User matches or resolves the invoice.
5. System records the outcome in the procurement history.

### UX requirement

This should feel like part of the procurement workflow, not a detached finance island.

## 10. Data Source Connection

### Current support

- `/api/data-sources`
- `/api/data-sources/test`
- `/api/data-sources/{id}/test`
- `/api/data-sources/{id}/activate`

### Flow

1. Admin opens `Data Sources`.
2. User creates a new source or re-tests an existing one.
3. Product validates the connection.
4. User reviews activation impact.
5. User activates the source.

### Unhappy paths

- failed test
- credential error
- source created but not activated

### `[Future Enhancement]`

Field-level mapping, sync scheduling, and transformation controls require more backend support.

## 11. CSV Import Wizard

### Current support

- `/api/imports/types`
- `/api/imports/sample/{type}`
- `/api/imports/analyze`
- `/api/imports/validate`
- `/api/imports/commit`
- `/api/imports`

### Flow

1. User selects import type.
2. User uploads a file.
3. System analyzes shape and proposes mappings.
4. User validates fields and errors.
5. User commits the import.
6. Import appears in history with outcome state.

### UX requirement

The wizard should feel safe, progressive, and recoverable.

## 12. Team And Access Management

### Current support

- `/api/team`
- `/api/team/seats`
- `/api/auth/invite`
- `/api/team/{user_id}/role`
- `/api/team/{user_id}/status`

### Flow

1. Admin opens `Team Management`.
2. User sees seat usage, role distribution, and invite state.
3. User invites a teammate or changes a role/status.
4. Product confirms impact and new state.
5. Invitee accepts the invite through the access flow.

### UX requirement

Role changes should be explicit and cautious, not buried inside row menus without context.

## 13. Billing, Plans, And Invoices

### Current support

- `/api/tenants/billing-profile`
- `/api/billing/plans`
- `/api/billing/subscription`
- `/api/billing/invoices`
- `/api/billing/invoices/{invoice_id}`
- `/api/billing/invoices/{invoice_id}/print`
- `/api/outcome-pricing/*`

### Flow

1. Admin opens `Billing And Plans`.
2. Product separates plan context, current subscription, and invoices.
3. User drills into an invoice detail or print view.
4. User reviews `Outcome Pricing` when relevant.

### UX requirement

Billing should feel like a trusted B2B admin flow, not like a consumer checkout.

## 14. Developer Activation

### Current support

- `/api/api-keys`
- `/api/webhooks`
- `/api/webhooks/{webhook_id}/deliveries`
- `/api/webhooks/test`
- `/api/public/v1/*`

### Flow

1. Developer opens `Developer Portal`.
2. User creates an API key and sees the one-time reveal pattern.
3. User tests a request in the playground.
4. User configures a webhook and sends a test delivery.
5. User reviews delivery history and copies embed guidance for Sage.

### UX requirement

This area should feel precise and trustworthy enough for developers while still matching the main product shell.

## 15. Security And Audit Investigation

### Current support

- `/api/security/summary`
- `/api/security/kpi`
- `/api/security/events`
- `/api/security/events/export`
- `/api/audit/*`

### Flow

1. Admin opens `Security Overview`.
2. Product shows top posture metrics and recent events.
3. User drills into the events view.
4. User filters and exports evidence.
5. User pivots to `Audit Log` if broader history is needed.

### UX requirement

Security and audit should feel related but not collapsed into one overloaded screen.

## 16. Monitoring And Public Status

### Current support

- `/api/monitoring/stats`
- `/api/monitoring/health/detailed`
- `/api/monitoring/public-status`
- `/api/monitoring/live`
- `/api/monitoring/ready`

### Flow

1. Operator opens `Monitoring Overview`.
2. Product shows internal health and operational signals.
3. User checks `Public Status` when external communication is needed.
4. Degraded live systems surface reconnect or retry guidance inside app states.

### UX requirement

Internal monitoring and public status should feel connected, but clearly different in audience and tone.

## 17. Trust Review

### Current support

- `/trust`
- tenant isolation and governance documentation-backed content

### Flow

1. Buyer, admin, or security stakeholder opens `Trust Center`.
2. Product explains isolation, access control, auditability, and operating commitments.
3. User can route to related pages:
   - Security
   - Audit
   - Public Status
   - Billing and Plans

### UX requirement

Trust should be understandable to non-technical stakeholders without losing technical credibility.

## 18. Future Enhancements

- `[Future Enhancement]` unified `My Work` object across alerts, findings, approvals, and drafts
- `[Future Enhancement]` native SSO/SCIM setup and lifecycle administration
- `[Future Enhancement]` supplier-facing collaboration workspace
