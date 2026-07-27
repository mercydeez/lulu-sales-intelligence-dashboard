# E-invoicing: what is built, and what accreditation would take (E10-4)

**Status:** submission lifecycle built; **no real clearance is possible**.
**Implementation:** `backend/app/services/einvoicing.py`, schema from migration 044.

> **This is not tax advice and not a compliance guarantee.** UAE e-invoicing
> format, accreditation and submission rules require review by a qualified UAE tax
> professional before any production or customer use.

---

## The honest state

| Provider | Recognised | Key configurable | **Can clear an invoice** |
|---|---|---|---|
| `mock` | yes | n/a | yes — locally, tagged `MOCK-` |
| `zatca` | yes | `ZATCA_API_KEY` | **no** |
| `uae_fta` | yes | `UAE_FTA_API_KEY` | **no** |

`submit_einvoice` **refuses** a real gateway even when its API key is set. It
returns an error rather than an `accepted` clearance.

This is deliberate, and it is the whole point of the design. A tax invoice marked
`accepted` with a clearance reference that no clearing house ever issued is a
**fabricated compliance record**. It would sit in the customer's books looking
exactly like a real one, and the discovery event is an audit. An error at
submission time is recoverable; a fake clearance is not.

The `mock` provider tags every clearance `MOCK-<...>` precisely so it cannot be
mistaken for a real one, even by a script.

Adding a gateway is a code change to `IMPLEMENTED_PROVIDERS` **and nothing else in
the schema** — the lifecycle, columns and states already exist. The reason it is
not implemented is not effort. It is that we are not accredited.

---

## Why a key is not enough

Neither ZATCA (KSA) nor the UAE FTA model lets you post an invoice to an endpoint
with a bearer token. Both are *clearance* models: the invoice must be cleared by
an accredited party **before** it is legally issued to the buyer. Roughly, in
order:

1. **Entity onboarding.** The *taxpayer* — our customer, not us — is registered
   with the authority. A SaaS vendor cannot clear invoices on a customer's behalf
   without being appointed in that customer's name.
2. **Accredited Service Provider status.** In the UAE's Peppol-based model
   (E-Invoicing Programme), the software must be an accredited **ASP** on the
   authority's list. That is an application, a conformance test suite, and an
   audit — not an integration.
3. **Cryptographic identity.** A CSR is submitted; the authority issues a
   compliance certificate, then a production certificate. Invoices are signed with
   it. Losing or mishandling that key is a tax-fraud exposure, not an outage.
4. **Conformance testing.** A test batch of every invoice type (standard,
   simplified, credit note, debit note) must pass the authority's validator in a
   sandbox before production credentials are issued.
5. **Format.** UBL 2.1 XML with the authority's extensions, a hash chain linking
   each invoice to its predecessor (`PIH`), a QR code with prescribed TLV fields,
   and an XAdES signature. Getting the hash chain wrong invalidates every
   subsequent invoice, not just the bad one.

Steps 2–4 are organisational and take months. **None of them can be shortened by
writing code**, which is why shipping code that pretends they happened is the
worst available option.

---

## What we would build, once accredited

In dependency order. Nothing here needs a schema migration.

1. **Signing service.** Certificate storage in the existing vault (E5-6 rotation
   applies), CSR generation, XAdES signing. The private key must never reach a
   log line or an error payload.
2. **UBL 2.1 serialiser.** From the existing `invoices` / `invoice_lines` rows.
   The AED amounts are already correct to the fils (see E2-4 — the import path was
   truncating them, and no longer does).
3. **Hash chain.** `PIH` = hash of the previous cleared invoice, per seller. This
   needs a per-tenant serialised counter; a race that clears two invoices with the
   same predecessor hash invalidates the chain from that point.
4. **Clearance client.** Submit → poll → persist `cleared`/`rejected` with the
   authority's response verbatim. Never synthesise a status on timeout: an unknown
   outcome is `pending`, not `accepted`.
5. **Reconciliation job.** Anything left `pending` past a threshold is surfaced to
   an operator. A silently-stuck invoice is an unissued invoice.
6. **Add the provider to `IMPLEMENTED_PROVIDERS`.** One line. It comes last, and
   only after a sandbox conformance run passes.

---

## Until then

- `mock` is available in every environment for demos and tests.
- A real gateway is refused with an explicit error naming the reason.
- No invoice in this system carries a clearance reference that did not come from a
  clearing house, real or explicitly-labelled mock.

The refusal is enforced in code and covered by tests. If you find a path that
produces an `accepted` clearance without a clearing house, that is a bug of the
highest severity in this repository.
