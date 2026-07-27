# Retail IQ — Known Limitations

> Honest statement of what this product is **not** and what is deferred. Read with
> `GO_NO_GO_DECISION.md`. The pilot is safe for **demo/sample data**; these limits
> bound that claim.

## Data

- **Synthetic / sample data by default.** The live dashboard runs on a Kaggle
  store-item demand dataset (10 stores × 50 items, **units** not currency) plus a
  synthetic generator. AED revenue is *derived* (`SUM(units × unit_price_aed)`).
  This is **not** real customer sales data. The UI labels demo data; AI answers
  carry a `data_disclosure` saying so.
- **No self-serve data import (Phase 7 — deferred).** A tenant cannot upload its
  own dataset through the product. Loading real data is a manual, operator-assisted
  step for the pilot.
- **No public ingestion API (Phase 8 — deferred).** There is no programmatic
  real-data write feed. The only Phase-8 work shipped is API-key **expiry**
  (`expires_at`), not ingestion.

## Scope of the product

- **Decision-support, not a system of record.** Forecasts, findings, and AI
  answers are advisory. The product is **not** a POS, not an accounting/financial
  system, and must not be relied on as the source of truth for money or stock.
- **AI is read-only.** The assistant answers questions over the tenant's own data
  (SELECT-only, allow-listed views). It takes **no autonomous action**; any
  operational step is a draft for a human.
- **External AI off by default.** Tenant data does not leave to a third-party LLM
  unless `ENABLE_EXTERNAL_AI` is explicitly enabled for that deployment.

## Compliance & legal

- **No compliance certification.** The product makes **no** claim of GDPR, CCPA,
  UAE PDPL, SOC 2, ISO 27001, or PCI conformance. The documents in `docs/legal/`
  are **drafts requiring legal review**.
- **Delete-on-request is human-approved**, not instant or automated; backups
  expire/scrub per the deletion runbook, not immediately.

## Operational

- **RLS enforcement** is on by default for the request path (`USE_RLS_ROLE`); app-
  layer tenant scoping remains the primary control with RLS as a backstop.
- **Single-region / single-node pilot topology.** No multi-region HA; RPO/RTO are
  documented targets for the pilot, not a contractual SLA.
- **Local test trap:** `requirements.txt` pins `httpx==0.26.0`; a newer global
  httpx breaks the TestClient suites locally. Run tests in the container or a
  pinned venv (CI/Docker are unaffected).
