# Privacy Notice — DRAFT (legal review required)

> **DRAFT — NOT LEGAL ADVICE.** This document is an engineering-authored starting
> point for a privacy notice. It must be reviewed and approved by qualified legal
> counsel before being published or relied upon. Nothing here is a compliance
> certification or a claim of regulatory conformance.

## 1. Who this covers

This notice describes how **Retail IQ** (the "Service") handles data for a
**pilot/demo deployment**. The current pilot runs on **synthetic / sample data**
unless a tenant has explicitly loaded their own data. Where a tenant loads its own
data, that tenant is the **data controller** and the Service operator is a
**data processor** acting on the tenant's instructions.

## 2. What data the Service holds

- **Account data**: user email, display name, role, tenant membership, hashed
  credentials and MFA secrets (never exported, never logged).
- **Tenant business data**: stores, items, sales records, forecasts, findings,
  procurement records — all stamped with a `tenant_id` and isolated per tenant.
- **Operational logs**: request IDs and, where safe, tenant/user identifiers for
  diagnostics. Logs are scrubbed of secrets.

## 3. How data is isolated

Every tenant's data is scoped by `tenant_id` at the application layer and, where
enabled, enforced by Postgres Row-Level Security as a backstop. A tenant can only
ever read, export, or request deletion of **its own** data.

## 4. Your rights (data-subject requests)

- **Access / portability** — a tenant admin can export their tenant's data at any
  time via the in-product export (`GET /api/data-rights/export`) or by filing a
  request.
- **Erasure ("delete on request")** — a tenant admin can file a deletion request.
  Deletions are **reviewed and executed by an operator** (human-approved) within a
  documented review window; they are not performed automatically. See the operator
  runbook `docs/runbooks/DATA_DELETION.md`.

## 5. Sub-processors / external AI

The Service does **not** send tenant data to any third-party LLM unless
`ENABLE_EXTERNAL_AI` is explicitly turned on for that deployment (off by default).
With it off, all AI runs locally or via a deterministic responder.

## 6. Retention

Backups are retained per the operator's documented RPO/RTO
(`docs/production/BACKUP_RESTORE.md`). A completed erasure also requires backup
expiry or targeted scrubbing per the deletion runbook.

## 7. Contact

Data requests should be directed to the operator's designated contact (to be
filled in by the deploying organisation).

---
*Open items for legal review:* lawful basis statements, jurisdiction-specific
rights (GDPR/CCPA/UAE PDPL), DPA template, breach-notification timelines,
sub-processor list, retention periods. The Service makes **no** claim of GDPR,
CCPA, PDPL, SOC 2, ISO 27001, or PCI compliance.
