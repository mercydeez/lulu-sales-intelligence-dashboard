# Retail IQ — Security & Data Protection (one-pager)

> For a buyer's IT / procurement / security review. Every claim below maps to a
> mechanism in the product. Legal/compliance statements are **draft and require
> review by a qualified UAE legal/tax professional before contractual use.**

## Where your data lives
- **One tenant, one boundary.** Every customer is a separate tenant. Application
  queries are tenant-scoped, and **PostgreSQL Row-Level Security (RLS)** enforces it
  at the database layer (FORCE RLS, non-owner app role) — so even an application bug
  cannot return another tenant's rows. Isolation is proven by an automated test
  (`tests/test_tenant_isolation.py`) and documented in `docs/security/TENANT_ISOLATION_PROOF.md`.
- **Data residency.** The platform is region-portable; for UAE customers it should
  be deployed in an in-region environment. *(Confirm the hosting region in the
  contract — draft.)*

## Who can see what
- **Authentication:** JWT access/refresh tokens (Bearer or httpOnly cookie),
  optional **TOTP two-factor** with backup codes, server-side session revocation.
- **Authorization (RBAC):** roles scope access down to region → store. Enforced
  **server-side** on every data endpoint — never trusted from the client.
- **AI safety:** the Sage assistant is read-only, RBAC- and tenant-scoped, resists
  prompt injection, and falls back to deterministic answers if the local model is
  unavailable. It can never see or return data outside the caller's scope.

## Auditability & privacy (UAE PDPL readiness)
- **Audit log:** sensitive actions (lifecycle, billing, invoices, profile changes,
  data imports, access events) are recorded per tenant and **exportable as CSV/JSON**
  for compliance evidence (in-app **Audit** screen). No secrets, tokens, full API
  keys, or payment details are ever logged.
- **Data subject rights:** a tenant can **export** all of its data (portability) and
  **request deletion** (erasure); deletion is human-approved and audited
  (`/api/data-rights/*`). Supports UAE PDPL data-subject expectations. *(Draft —
  legal review required.)*
- **Trust documents:** Terms, Privacy and a DPA exist in draft (`docs/legal/`) and
  require professional review before signature.

## Operations & resilience
- **Backups & restore:** documented backup/restore procedure and runbooks
  (`docs/production/BACKUP_RESTORE.md`, `docs/runbooks/`).
- **Observability:** health/readiness checks, structured logs with request IDs,
  per-request tenant/user context (numeric ids only).
- **Secrets:** application secrets are environment-injected; the app refuses to boot
  in production with default secrets.

## What we do NOT do
- We never sell or share customer data.
- We never auto-execute money movement or supplier orders — recommended actions are
  **drafted and require human approval** (autonomy level 1).
- We never log passwords, tokens, full API keys, or full payment details.

## Subprocessors
- The prototype runs with **no mandatory third-party data processors**. Any future
  processor (payment gateway, e-invoicing provider, email) is opt-in, configured per
  deployment, and will be disclosed in an updated subprocessor list.

---
*Draft — security posture is implemented and testable; legal/compliance wording
requires review by a qualified UAE legal/tax professional before customer/contractual use.*
