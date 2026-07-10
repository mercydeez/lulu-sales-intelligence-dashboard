"""
E-invoicing submission (UAE SaaS Phase 5 — completing the readiness fields).

Builds on the e_invoice_* columns added in migration 044. UAE e-invoicing is being
phased in; this provides the SUBMISSION LIFECYCLE (submit → accepted/rejected) behind
a provider abstraction. A built-in 'mock' clearing house works with no external
service (auto-accepts a well-formed invoice, tagged MOCK-) so the flow is demoable
today. Real gateways (ZATCA-style / a UAE FTA-accredited provider) are recognised
but NOT integrated: submit_einvoice refuses them — even when their API key is set —
rather than fake an 'accepted' clearance. Wiring a real gateway is a later change
(no schema change) that adds it to IMPLEMENTED_PROVIDERS.

Pure helpers (payload build, provider check, validation) unit-test with no DB.

LEGAL/TAX: NOT a compliance guarantee. Draft — UAE e-invoicing format, accreditation
and submission rules require review by a qualified UAE tax professional before
production/customer use.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 'mock' is always available (local clearing-house simulation). Real gateways are
# gated behind <NAME>_API_KEY until accredited + wired.
MOCK_PROVIDER = "mock"
GATEWAY_PROVIDERS = {"zatca", "uae_fta"}
ALL_PROVIDERS = {MOCK_PROVIDER} | GATEWAY_PROVIDERS

# Providers with an ACTUAL submission implementation. A real gateway being
# recognised + key-configured does NOT mean we can submit to it — the outbound
# integration/accreditation is not built. Only 'mock' actually clears an invoice.
# submit_einvoice refuses anything outside this set rather than faking acceptance.
IMPLEMENTED_PROVIDERS = {MOCK_PROVIDER}


def is_provider_available(provider: str) -> bool:
    if provider == MOCK_PROVIDER:
        return True
    if provider in GATEWAY_PROVIDERS:
        return bool(os.getenv(f"{provider.upper()}_API_KEY"))
    return False


def is_provider_implemented(provider: str) -> bool:
    """Whether we can actually submit to this provider (vs. merely recognise it).
    Real UAE gateways are recognised but not yet integrated/accredited."""
    return provider in IMPLEMENTED_PROVIDERS


def validate_submittable(invoice: Dict) -> Tuple[bool, Optional[str]]:
    """An invoice must be 'issued' (not draft/void) and carry both TRNs to be a
    valid e-invoice candidate. Returns (ok, error)."""
    if invoice.get("status") != "issued":
        return False, "Only an issued invoice can be submitted for e-invoicing"
    if not invoice.get("supplier_trn"):
        return False, "Supplier TRN is required for e-invoicing (set PLATFORM_SUPPLIER_TRN)"
    if not invoice.get("customer_trn"):
        return False, "Customer TRN is required — complete the tenant's UAE billing profile"
    return True, None


def build_einvoice_payload(invoice: Dict, lines: Optional[List[Dict]] = None) -> Dict:
    """Construct the minimal structured e-invoice payload (FTA-style fields). Pure.
    Money already lives on the invoice in AED with explicit VAT."""
    return {
        "schema": "uae-einvoice-draft-v0",
        "invoice_number": invoice.get("invoice_number"),
        "issue_date": (invoice.get("issued_at") or invoice.get("created_at")),
        "currency": invoice.get("currency", "AED"),
        "supplier": {"legal_name": invoice.get("supplier_legal_name"),
                     "trn": invoice.get("supplier_trn")},
        "customer": {"legal_name": invoice.get("customer_legal_name"),
                     "trn": invoice.get("customer_trn")},
        "totals": {
            "subtotal_aed": str(invoice.get("subtotal_aed")),
            "vat_rate": str(invoice.get("vat_rate")),
            "vat_amount_aed": str(invoice.get("vat_amount_aed")),
            "total_aed": str(invoice.get("total_aed")),
        },
        "line_count": len(lines) if lines is not None else None,
    }


async def submit_einvoice(db: AsyncSession, invoice_id: int, *,
                          provider: str = MOCK_PROVIDER) -> Tuple[Optional[Dict], Optional[str]]:
    """Submit an issued invoice to an e-invoicing provider. Only the 'mock'
    clearing house is actually implemented; it accepts a well-formed invoice and
    tags the clearance MOCK- so it can never be mistaken for a real one.

    A real gateway ('zatca'/'uae_fta') is REFUSED even when its API key is set —
    the outbound integration/accreditation is not built, and marking a tax invoice
    'accepted' without a real clearing response would be a fabricated compliance
    record. Caller commits. Returns (result, None) or (None, error)."""
    if not is_provider_available(provider):
        return None, f"E-invoicing provider '{provider}' is not configured"

    # Honesty gate: recognised + key-configured is NOT integrated. Never fake a
    # real gateway's acceptance.
    if not is_provider_implemented(provider):
        return None, (
            f"E-invoicing provider '{provider}' is recognised but not yet "
            "integrated/accredited — no submission was performed and the invoice "
            "was not cleared. Use 'mock' for demos; a real gateway requires the "
            "outbound integration and UAE-FTA accreditation to be completed first."
        )

    inv = (await db.execute(text("""
        SELECT id, tenant_id, invoice_number, status, currency, issued_at, created_at,
               supplier_legal_name, supplier_trn, customer_legal_name, customer_trn,
               subtotal_aed, vat_rate, vat_amount_aed, total_aed, e_invoice_status
        FROM invoices WHERE id = :iid
    """), {"iid": invoice_id})).mappings().fetchone()
    if not inv:
        return None, "Invoice not found"
    if inv["e_invoice_status"] == "accepted":
        return None, "Invoice has already been accepted by the e-invoicing provider"

    ok, err = validate_submittable(dict(inv))
    if not ok:
        return None, err

    import json
    payload = build_einvoice_payload(dict(inv))
    payload["clearing"] = "mock"  # provenance stamped into the stored payload
    now = datetime.now(timezone.utc)

    # Mock clearing house: a valid payload is accepted immediately. The external id
    # is MOCK-tagged so a mock clearance is never confused with a real FTA one.
    new_status = "accepted"
    external_id = f"MOCK-EI-{inv['invoice_number']}"

    await db.execute(text("""
        UPDATE invoices
           SET e_invoice_status = :st, e_invoice_provider = :prov,
               e_invoice_external_id = :ext, e_invoice_payload = CAST(:pl AS JSONB),
               e_invoice_submitted_at = :now, e_invoice_accepted_at = :now,
               updated_at = :now
         WHERE id = :iid
    """), {"st": new_status, "prov": provider, "ext": external_id,
           "pl": json.dumps(payload, default=str), "now": now, "iid": invoice_id})

    return {"invoice_id": invoice_id, "tenant_id": inv["tenant_id"],
            "invoice_number": inv["invoice_number"],
            "e_invoice_status": new_status, "e_invoice_provider": provider,
            "e_invoice_external_id": external_id, "mock": True}, None
