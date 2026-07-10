"""E10-4 — UAE-FTA e-invoice CLEARANCE harness.

einvoicing.py gave a coarse submit → accepted lifecycle. Real FTA clearance needs the
full document harness, and this builds it:

    serialize the invoice to UBL 2.1  ->  hash it  ->  chain it to the previous cleared
    invoice's hash (PIH)  ->  sign it  ->  submit to the clearing house  ->  persist the
    clearance in an auditable einvoice_submissions ledger.

THE HONEST BOUNDARY (identical posture to einvoicing.py / payments.py / pos_connectors):

  * Only the `mock` clearing house, in the `sandbox` environment, actually clears an
    invoice. Everything it produces is SANDBOX-labelled and is_production_signed=FALSE,
    so a sandbox clearance can never be mistaken for a real FTA one.
  * A real gateway (`uae_fta`) is REFUSED until it is integrated AND the operator is
    FTA-accredited — an organisational/legal process code cannot shortcut. We build the
    document, hash, chain and sign; we never fake a clearing response we did not receive.
  * The `production` environment is refused outright here (no accreditation, no signing
    cert). Migration 071's CHECK also makes a production signature impossible in sandbox.

The pure builders (UBL, hash, PIH, sandbox signature) unit-test with no DB. Reuses the
provider gating in einvoicing.py so there is ONE source of truth for what is integrated.

LEGAL/TAX: NOT a compliance guarantee. UAE e-invoicing format (PINT-AE/UBL), accreditation
and signing rules require review by a qualified UAE tax professional before production use.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services import einvoicing

SANDBOX = "sandbox"
PRODUCTION = "production"
VALID_ENVIRONMENTS = (SANDBOX, PRODUCTION)

# The UBL profile this harness targets (UAE PINT-AE is Peppol-BIS-based). Draft.
UBL_CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"
UBL_PROFILE_ID = "urn:peppol:bis:billing"


# ---------------------------------------------------------------------------
# 1. UBL 2.1 serialization (pure).
# ---------------------------------------------------------------------------

def _el(tag: str, value) -> str:
    return f"<{tag}>{escape(str(value))}</{tag}>"


def build_ubl_invoice(invoice: Dict, lines: Optional[List[Dict]] = None) -> str:
    """Serialize an invoice to a UBL 2.1 Invoice document (FTA/PINT-AE draft shape).

    Pure and deterministic given the same inputs — so its hash is stable and the PIH
    chain is reproducible. Money is already AED with explicit VAT on the invoice.
    """
    lines = lines or []
    cur = invoice.get("currency") or "AED"
    issue = invoice.get("issued_at") or invoice.get("created_at")
    issue_date = str(issue)[:10] if issue else ""

    line_xml = []
    for i, ln in enumerate(lines, start=1):
        line_xml.append(
            "<cac:InvoiceLine>"
            + _el("cbc:ID", i)
            + f'<cbc:InvoicedQuantity unitCode="EA">{escape(str(ln.get("quantity", 1)))}</cbc:InvoicedQuantity>'
            + f'<cbc:LineExtensionAmount currencyID="{escape(cur)}">{escape(str(ln.get("line_subtotal_aed", 0)))}</cbc:LineExtensionAmount>'
            + "<cac:Item>" + _el("cbc:Name", ln.get("description", "")) + "</cac:Item>"
            + "<cac:Price>"
            + f'<cbc:PriceAmount currencyID="{escape(cur)}">{escape(str(ln.get("unit_price_aed", 0)))}</cbc:PriceAmount>'
            + "</cac:Price>"
            + "</cac:InvoiceLine>"
        )

    def _party(role_tag: str, name, trn) -> str:
        return (
            f"<cac:{role_tag}><cac:Party>"
            + "<cac:PartyTaxScheme>"
            + _el("cbc:CompanyID", trn or "")
            + "<cac:TaxScheme>" + _el("cbc:ID", "VAT") + "</cac:TaxScheme>"
            + "</cac:PartyTaxScheme>"
            + "<cac:PartyLegalEntity>" + _el("cbc:RegistrationName", name or "") + "</cac:PartyLegalEntity>"
            + f"</cac:Party></cac:{role_tag}>"
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"'
        ' xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
        ' xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        + _el("cbc:CustomizationID", UBL_CUSTOMIZATION_ID)
        + _el("cbc:ProfileID", UBL_PROFILE_ID)
        + _el("cbc:ID", invoice.get("invoice_number", ""))
        + _el("cbc:IssueDate", issue_date)
        + _el("cbc:InvoiceTypeCode", "388")
        + _el("cbc:DocumentCurrencyCode", cur)
        + _party("AccountingSupplierParty", invoice.get("supplier_legal_name"), invoice.get("supplier_trn"))
        + _party("AccountingCustomerParty", invoice.get("customer_legal_name"), invoice.get("customer_trn"))
        + "<cac:TaxTotal>"
        + f'<cbc:TaxAmount currencyID="{escape(cur)}">{escape(str(invoice.get("vat_amount_aed", 0)))}</cbc:TaxAmount>'
        + "</cac:TaxTotal>"
        + "<cac:LegalMonetaryTotal>"
        + f'<cbc:TaxExclusiveAmount currencyID="{escape(cur)}">{escape(str(invoice.get("subtotal_aed", 0)))}</cbc:TaxExclusiveAmount>'
        + f'<cbc:TaxInclusiveAmount currencyID="{escape(cur)}">{escape(str(invoice.get("total_aed", 0)))}</cbc:TaxInclusiveAmount>'
        + f'<cbc:PayableAmount currencyID="{escape(cur)}">{escape(str(invoice.get("total_aed", 0)))}</cbc:PayableAmount>'
        + "</cac:LegalMonetaryTotal>"
        + "".join(line_xml)
        + "</Invoice>"
    )
    return body


def canonical_hash(ubl_xml: str) -> str:
    """SHA-256 (hex) of the document. The harness hashes the exact submitted bytes so
    the stored hash reproduces from the stored UBL."""
    return hashlib.sha256(ubl_xml.encode("utf-8")).hexdigest()


def sign_document(ubl_xml: str, invoice_hash: str, *, environment: str,
                  previous_hash: Optional[str]) -> Tuple[str, bool]:
    """Produce the document signature. Returns (signature, is_production_signed).

    A real production signature is an XAdES enveloped signature made with the operator's
    FTA-issued certificate — NOT built here (no cert, not accredited). In `production`
    this refuses rather than emit a signature it cannot legitimately make. In `sandbox`
    it emits a clearly-labelled digest chaining the PIH, is_production_signed=FALSE, so
    the flow is exercised without ever asserting a real signature."""
    if environment == PRODUCTION:
        raise NotImplementedError(
            "Production XAdES signing requires an FTA-accredited signing certificate, "
            "which is not configured. No production signature was produced.")
    chained = f"{previous_hash or 'GENESIS'}:{invoice_hash}"
    digest = hashlib.sha256(chained.encode("utf-8")).hexdigest()
    return f"SANDBOX-UNSIGNED-{digest[:32]}", False


# ---------------------------------------------------------------------------
# 2. PIH chain.
# ---------------------------------------------------------------------------

async def get_previous_hash(db: AsyncSession, tenant_id: int) -> Optional[str]:
    """The invoice_hash of this tenant's most recently CLEARED submission — the PIH the
    next document chains to. NULL for the first in the chain."""
    return (await db.execute(text("""
        SELECT invoice_hash FROM einvoice_submissions
         WHERE tenant_id = :t AND status = 'cleared' AND invoice_hash IS NOT NULL
         ORDER BY cleared_at DESC NULLS LAST, id DESC LIMIT 1
    """), {"t": tenant_id})).scalar()


# ---------------------------------------------------------------------------
# 3. Submit → clear → persist.
# ---------------------------------------------------------------------------

async def submit_for_clearance(
    db: AsyncSession, invoice_id: int, *, provider: str = einvoicing.MOCK_PROVIDER,
    environment: str = SANDBOX, submitted_by: str = "operator",
) -> Tuple[Optional[Dict], Optional[str]]:
    """Build, hash, chain, sign and submit an invoice for clearance, persisting the
    attempt. Only mock/sandbox actually clears; a real gateway or the production
    environment is refused. Caller commits. Returns (result, None) or (None, error)."""
    if environment not in VALID_ENVIRONMENTS:
        return None, f"Unknown environment {environment!r}"

    # Provider gating — the single source of truth lives in einvoicing.py.
    if not einvoicing.is_provider_available(provider):
        return None, f"E-invoicing provider '{provider}' is not configured"
    if not einvoicing.is_provider_implemented(provider):
        return None, (
            f"E-invoicing provider '{provider}' is recognised but not yet "
            "integrated/accredited — no clearance was performed. Use 'mock' in the "
            "sandbox; a real gateway needs the outbound integration and UAE-FTA "
            "accreditation to be completed first.")
    # Even an implemented provider does not clear in production without accreditation.
    if environment == PRODUCTION:
        return None, (
            "Production clearance is refused: no FTA-accredited signing certificate or "
            "production clearing-house credentials are configured. Use the sandbox.")

    inv = (await db.execute(text("""
        SELECT id, tenant_id, invoice_number, status, currency, issued_at, created_at,
               supplier_legal_name, supplier_trn, customer_legal_name, customer_trn,
               subtotal_aed, vat_rate, vat_amount_aed, total_aed, e_invoice_status
          FROM invoices WHERE id = :iid
    """), {"iid": invoice_id})).mappings().fetchone()
    if not inv:
        return None, "Invoice not found"
    inv = dict(inv)
    tenant_id = inv["tenant_id"]

    if inv["e_invoice_status"] == "accepted":
        return None, "Invoice has already been cleared"
    ok, err = einvoicing.validate_submittable(inv)
    if not ok:
        return None, err

    lines = [dict(r) for r in (await db.execute(text("""
        SELECT description, quantity, unit_price_aed, line_subtotal_aed, vat_amount_aed, line_total_aed
          FROM invoice_lines WHERE invoice_id = :iid ORDER BY id
    """), {"iid": invoice_id})).mappings().all()]

    # Build the document, hash it, chain it to the previous cleared hash, sign it.
    ubl = build_ubl_invoice(inv, lines)
    invoice_hash = canonical_hash(ubl)
    previous_hash = await get_previous_hash(db, tenant_id)
    try:
        signature, is_prod_signed = sign_document(
            ubl, invoice_hash, environment=environment, previous_hash=previous_hash)
    except NotImplementedError as exc:
        return None, str(exc)

    # Open the submission (building), then submit to the clearing house.
    sub_id = (await db.execute(text("""
        INSERT INTO einvoice_submissions (tenant_id, invoice_id, provider, environment, status,
                                          ubl_xml, invoice_hash, previous_invoice_hash,
                                          signature, is_production_signed, submitted_by)
        VALUES (:t, :iid, :p, :env, 'submitted', :ubl, :h, :ph, :sig, :ips, :by)
        RETURNING id
    """), {"t": tenant_id, "iid": invoice_id, "p": provider, "env": environment, "ubl": ubl,
           "h": invoice_hash, "ph": previous_hash, "sig": signature, "ips": is_prod_signed,
           "by": submitted_by})).scalar()

    # Mock clearing house: a well-formed, validated document clears synchronously. The
    # clearance ref is SANDBOX- prefixed so it is never confused with a real FTA UUID.
    clearance_ref = f"SANDBOX-CLR-{inv['invoice_number']}"
    now = datetime.now(timezone.utc)
    response = {"clearing": "mock", "environment": environment,
                "invoice_hash": invoice_hash, "previous_invoice_hash": previous_hash,
                "profile": UBL_CUSTOMIZATION_ID}

    await db.execute(text("""
        UPDATE einvoice_submissions
           SET status='cleared', clearance_ref=:ref, cleared_at=:now, poll_attempts=1,
               response_payload=CAST(:resp AS JSONB), updated_at=:now
         WHERE id=:sid
    """), {"ref": clearance_ref, "now": now, "resp": json.dumps(response), "sid": sub_id})

    # Mirror the clearance onto the invoice's coarse e_invoice_* fields (existing contract).
    await db.execute(text("""
        UPDATE invoices
           SET e_invoice_status='accepted', e_invoice_provider=:prov,
               e_invoice_external_id=:ext, e_invoice_payload=CAST(:pl AS JSONB),
               e_invoice_submitted_at=:now, e_invoice_accepted_at=:now, updated_at=:now
         WHERE id=:iid
    """), {"prov": provider, "ext": clearance_ref, "pl": json.dumps(response), "now": now,
           "iid": invoice_id})

    logger.info(f"[einvoice] invoice {invoice_id} cleared in {environment} via {provider} "
                f"(hash={invoice_hash[:12]}…, pih={'∅' if not previous_hash else previous_hash[:12]+'…'})")

    return {
        "submission_id": sub_id, "invoice_id": invoice_id, "tenant_id": tenant_id,
        "invoice_number": inv["invoice_number"], "provider": provider,
        "environment": environment, "status": "cleared", "clearance_ref": clearance_ref,
        "invoice_hash": invoice_hash, "previous_invoice_hash": previous_hash,
        "is_production_signed": is_prod_signed, "line_count": len(lines), "sandbox": True,
    }, None


async def poll_clearance(db: AsyncSession, tenant_id: int, submission_id: int) -> Optional[Dict]:
    """Return a submission's current clearance state. For the mock/sandbox path clearance
    is synchronous, so this reads the terminal state; a real async gateway would use this
    to poll the clearing house and advance submitted → cleared/rejected."""
    row = (await db.execute(text("""
        SELECT id, invoice_id, provider, environment, status, invoice_hash,
               previous_invoice_hash, clearance_ref, cleared_at, rejection_reason,
               poll_attempts, is_production_signed
          FROM einvoice_submissions WHERE id = :sid AND tenant_id = :t
    """), {"sid": submission_id, "t": tenant_id})).mappings().fetchone()
    if not row:
        return None
    d = dict(row)
    d["cleared_at"] = d["cleared_at"].isoformat() if d.get("cleared_at") else None
    return d


async def list_submissions(db: AsyncSession, tenant_id: int, invoice_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT id, provider, environment, status, invoice_hash, previous_invoice_hash,
               clearance_ref, cleared_at, is_production_signed, created_at
          FROM einvoice_submissions
         WHERE tenant_id = :t AND invoice_id = :iid ORDER BY id DESC
    """), {"t": tenant_id, "iid": invoice_id})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("cleared_at", "created_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        out.append(d)
    return out
