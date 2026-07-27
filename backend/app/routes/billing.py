"""
Billing API (UAE SaaS Phase 4) — subscriptions + VAT invoices.

Mounted at /api/billing. Tenant admins read their OWN subscription + invoices;
platform operators (super_admin) issue manual VAT invoices, mark them issued, and
record manual/bank-transfer payments. Provider-abstracted (manual-first). Tenant
scoping is explicit (`WHERE tenant_id = …`) like routes/tenants.py.

LEGAL/TAX: invoice/VAT modelling only — Draft, requires UAE legal/tax review.
"""
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.services.database import async_session
from app.services import billing as billing_svc
from app.auth_deps import get_current_user
from app.config import logger

router = APIRouter(tags=["Billing"])

_LEGAL_NOTE = ("Draft — VAT/invoice content requires review by a qualified UAE "
               "legal/tax professional before production/customer use.")


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")


def _require_super(user: dict) -> None:
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")


def _f(v):
    return float(v) if v is not None else None


async def _audit_invoice(event: str, invoice_id: int, user: dict, row: dict) -> None:
    """Record an invoice lifecycle action in the tenant's audit log (no money/secret
    values beyond the invoice number + status)."""
    from app.services.security_events import record_event
    await record_event(event, category="audit", severity="low",
                       tenant_id=row.get("tenant_id"),
                       actor_user_id=user.get("id"), actor_email=user.get("email"),
                       detail=f"Invoice {row.get('invoice_number')} → {row.get('status')}",
                       evidence={"invoice_number": row.get("invoice_number"),
                                 "status": row.get("status")})


class InvoiceLineIn(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: float = 1
    unit_price_aed: float = 0


class InvoiceCreate(BaseModel):
    tenant_id: int
    lines: List[InvoiceLineIn]
    billing_provider: str = "manual"
    period_start: Optional[str] = None   # ISO date
    period_end: Optional[str] = None
    po_number: Optional[str] = None
    payment_terms: Optional[str] = "Net 30"
    payment_instructions: Optional[str] = None


class MarkPaid(BaseModel):
    payment_method: str = "bank_transfer"


class EInvoiceSubmit(BaseModel):
    provider: str = "mock"


@router.get("/plans")
async def list_plans(current_user: dict = Depends(get_current_user)):
    """Plan catalogue for the pricing page (AED). Prices/limits mirror what's enforced."""
    return {"plans": billing_svc.plans_catalog(), "currency": "AED", "note": _LEGAL_NOTE}


@router.get("/providers")
async def list_providers(current_user: dict = Depends(get_current_user)):
    """Which payment providers are usable. Manual ones always; gateways only when
    configured (none wired yet — they slot in without a schema change)."""
    _require_admin(current_user)
    return {
        "manual": sorted(billing_svc.MANUAL_PROVIDERS),
        "gateways": {p: billing_svc.is_provider_supported(p) for p in sorted(billing_svc.GATEWAY_PROVIDERS)},
        "note": _LEGAL_NOTE,
    }


@router.get("/subscription")
async def get_subscription(current_user: dict = Depends(get_current_user)):
    """The caller's own subscription. Falls back to a view derived from the
    tenant's plan if no subscription row exists yet."""
    _require_admin(current_user)
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        row = (await session.execute(text("""
            SELECT plan, status, billing_provider, billing_cycle, currency,
                   current_period_start, current_period_end, trial_ends_at
            FROM subscriptions WHERE tenant_id = :tid
        """), {"tid": tenant_id})).mappings().fetchone()
        if row:
            sub = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()}
            sub["exists"] = True
            return sub
        plan_row = (await session.execute(
            text("SELECT plan FROM tenants WHERE id = :tid"), {"tid": tenant_id})).fetchone()
    plan = (plan_row.plan if plan_row else None) or "free"
    price = billing_svc.PLAN_PRICES_AED.get(plan)
    return {
        "exists": False, "plan": plan, "status": "manual",
        "billing_provider": "manual", "currency": "AED",
        "monthly_price_aed": _f(price) if price is not None else None,
        "custom_pricing": price is None,
    }


@router.get("/invoices")
async def list_invoices(tenant_id: Optional[int] = None,
                        current_user: dict = Depends(get_current_user)):
    """List invoices for the caller's tenant. A super-admin may pass ?tenant_id=
    to view another tenant's invoices (operator view)."""
    _require_admin(current_user)
    scope = current_user.get("tenant_id") or 1
    if tenant_id is not None and current_user.get("role") == "super_admin":
        scope = tenant_id
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, invoice_number, status, billing_provider, currency,
                   subtotal_aed, vat_amount_aed, total_aed, period_start, period_end,
                   issued_at, due_at, paid_at, created_at
            FROM invoices WHERE tenant_id = :tid
            ORDER BY created_at DESC LIMIT 200
        """), {"tid": scope})).mappings().fetchall()
    invoices = []
    for r in rows:
        d = dict(r)
        for k in ("subtotal_aed", "vat_amount_aed", "total_aed"):
            d[k] = _f(d[k])
        for k in ("period_start", "period_end", "issued_at", "due_at", "paid_at", "created_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        invoices.append(d)
    return {"invoices": invoices, "note": _LEGAL_NOTE}


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """Full invoice with line items. Tenant-scoped (super-admin can read any)."""
    _require_admin(current_user)
    is_super = current_user.get("role") == "super_admin"
    scope = current_user.get("tenant_id") or 1
    async with async_session() as session:
        where = "id = :iid" + ("" if is_super else " AND tenant_id = :tid")
        inv = (await session.execute(text(f"""
            SELECT * FROM invoices WHERE {where}
        """), {"iid": invoice_id, "tid": scope})).mappings().fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        lines = (await session.execute(text("""
            SELECT description, quantity, unit_price_aed, line_subtotal_aed,
                   vat_rate, vat_amount_aed, line_total_aed
            FROM invoice_lines WHERE invoice_id = :iid ORDER BY id
        """), {"iid": invoice_id})).mappings().fetchall()
    d = dict(inv)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif k.endswith("_aed") or k == "vat_rate" or k == "quantity":
            d[k] = _f(v)
    out_lines = []
    for l in lines:
        ld = dict(l)
        for k in ("quantity", "unit_price_aed", "line_subtotal_aed", "vat_rate",
                  "vat_amount_aed", "line_total_aed"):
            ld[k] = _f(ld[k])
        out_lines.append(ld)
    d["lines"] = out_lines
    d["note"] = _LEGAL_NOTE
    return d


@router.get("/invoices/{invoice_id}/print")
async def print_invoice(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """Browser-printable UAE Tax Invoice (→ PDF). Tenant-scoped (super-admin any)."""
    _require_admin(current_user)
    from fastapi.responses import HTMLResponse
    is_super = current_user.get("role") == "super_admin"
    scope = current_user.get("tenant_id") or 1
    async with async_session() as session:
        where = "id = :iid" + ("" if is_super else " AND tenant_id = :tid")
        inv = (await session.execute(text(f"SELECT * FROM invoices WHERE {where}"),
                                     {"iid": invoice_id, "tid": scope})).mappings().fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        lines = (await session.execute(text("""
            SELECT description, quantity, unit_price_aed, vat_amount_aed, line_total_aed
            FROM invoice_lines WHERE invoice_id = :iid ORDER BY id
        """), {"iid": invoice_id})).mappings().all()
    html = billing_svc.build_invoice_html(dict(inv), [dict(l) for l in lines])
    return HTMLResponse(html, headers={
        "Content-Disposition": f'attachment; filename="invoice-{inv["invoice_number"]}.html"'})


@router.post("/invoices", status_code=201)
async def create_invoice(payload: InvoiceCreate, current_user: dict = Depends(get_current_user)):
    """Issue a manual VAT invoice for a tenant (operator only). Creates it in
    'draft'; call /issue to finalise."""
    _require_super(current_user)
    if not billing_svc.is_provider_supported(payload.billing_provider):
        raise HTTPException(status_code=422,
                            detail=f"Provider '{payload.billing_provider}' is not configured")
    if not payload.lines:
        raise HTTPException(status_code=422, detail="At least one line item is required")

    def _date(s):
        return datetime.fromisoformat(s).date() if s else None

    async with async_session() as session:
        exists = (await session.execute(
            text("SELECT 1 FROM tenants WHERE id = :tid"), {"tid": payload.tenant_id})).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Tenant not found")
        result = await billing_svc.create_invoice(
            session, payload.tenant_id,
            lines=[l.model_dump() for l in payload.lines],
            billing_provider=payload.billing_provider,
            period_start=_date(payload.period_start), period_end=_date(payload.period_end),
            po_number=payload.po_number, payment_terms=payload.payment_terms,
            payment_instructions=payload.payment_instructions,
        )
        await session.commit()
    logger.info(f"Super-admin {current_user.get('email')} created invoice "
                f"{result['invoice_number']} for tenant {payload.tenant_id} "
                f"(AED {result['total_aed']})")
    from app.services.security_events import record_event
    await record_event("invoice_created", category="audit", severity="low",
                       tenant_id=payload.tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"Invoice {result['invoice_number']} created (AED {result['total_aed']})",
                       evidence={"invoice_number": result["invoice_number"],
                                 "total_aed": result["total_aed"], "provider": payload.billing_provider})
    return result


@router.post("/invoices/{invoice_id}/issue")
async def issue_invoice(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """Finalise a draft invoice: status draft→issued, set issued_at/due_at."""
    _require_super(current_user)
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        row = (await session.execute(text("""
            UPDATE invoices
               SET status = 'issued', issued_at = :now,
                   due_at = COALESCE(due_at, :due), updated_at = :now
             WHERE id = :iid AND status = 'draft'
             RETURNING id, tenant_id, invoice_number, status
        """), {"iid": invoice_id, "now": now, "due": now + timedelta(days=30)})).mappings().fetchone()
        await session.commit()
    if not row:
        raise HTTPException(status_code=409, detail="Invoice not found or not in draft")
    await _audit_invoice("invoice_issued", invoice_id, current_user, dict(row))
    from app.services.notifications import notify_tenant_admins
    await notify_tenant_admins(row["tenant_id"], type="billing", severity="medium",
                               title=f"Invoice {row['invoice_number']} issued",
                               body="A new invoice is available in Billing.",
                               link="/settings/billing",
                               metadata={"invoice_id": invoice_id})
    from app.services.webhook_service import dispatch_event_background
    dispatch_event_background(row["tenant_id"], "billing.invoice.created",
                             {"invoice_id": invoice_id, "invoice_number": row["invoice_number"]})
    return dict(row)


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_paid(invoice_id: int, payload: MarkPaid,
                    current_user: dict = Depends(get_current_user)):
    """Record a manual payment (bank transfer / cheque reconciliation): issued→paid."""
    _require_super(current_user)
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        row = (await session.execute(text("""
            UPDATE invoices
               SET status = 'paid', paid_at = :now, payment_method = :method, updated_at = :now
             WHERE id = :iid AND status = 'issued'
             RETURNING id, tenant_id, invoice_number, status, payment_method
        """), {"iid": invoice_id, "now": now, "method": payload.payment_method})).mappings().fetchone()
        await session.commit()
    if not row:
        raise HTTPException(status_code=409, detail="Invoice not found or not in 'issued' state")
    await _audit_invoice("invoice_paid", invoice_id, current_user, dict(row))
    return dict(row)


@router.post("/invoices/{invoice_id}/einvoice/submit")
async def submit_einvoice_endpoint(invoice_id: int, payload: EInvoiceSubmit,
                                   current_user: dict = Depends(get_current_user)):
    """Submit an issued invoice for e-invoicing (operator only). 'mock' auto-accepts
    a well-formed invoice; real UAE gateways are gated until configured.
    Draft — UAE e-invoicing rules require qualified tax review."""
    _require_super(current_user)
    from app.services.einvoicing import submit_einvoice
    async with async_session() as session:
        result, error = await submit_einvoice(session, invoice_id, provider=payload.provider)
        if error:
            await session.rollback()
            code = 404 if error == "Invoice not found" else 409
            raise HTTPException(status_code=code, detail=error)
        await session.commit()
    await _audit_invoice("invoice_einvoiced", invoice_id, current_user,
                         {"tenant_id": result.get("tenant_id"),
                          "invoice_number": result["invoice_number"],
                          "status": result["e_invoice_status"]})
    result["note"] = _LEGAL_NOTE
    return result


# --- E10-4: full FTA clearance harness (UBL 2.1 + PIH chain + signing scaffold) -----

class EInvoiceClearanceSubmit(BaseModel):
    provider: str = Field("mock", pattern="^(mock|zatca|uae_fta)$")
    environment: str = Field("sandbox", pattern="^(sandbox|production)$")


@router.get("/einvoice/clearance/config")
async def einvoice_clearance_config(current_user: dict = Depends(get_current_user)):
    """Honest status of the clearance harness: which providers are integrated, and the
    fact that only mock/sandbox actually clears (real FTA needs accreditation)."""
    _require_super(current_user)
    from app.services import einvoicing
    from app.services.einvoice_clearance import VALID_ENVIRONMENTS, UBL_CUSTOMIZATION_ID
    providers = {
        p: {"implemented": einvoicing.is_provider_implemented(p),
            "available": einvoicing.is_provider_available(p)}
        for p in sorted(einvoicing.ALL_PROVIDERS)
    }
    return {"providers": providers, "environments": list(VALID_ENVIRONMENTS),
            "clears_only": {"provider": "mock", "environment": "sandbox"},
            "ubl_profile": UBL_CUSTOMIZATION_ID, "note": _LEGAL_NOTE}


@router.post("/invoices/{invoice_id}/einvoice/clear")
async def clear_einvoice_endpoint(invoice_id: int, payload: EInvoiceClearanceSubmit,
                                  current_user: dict = Depends(get_current_user)):
    """Run the full clearance harness for an issued invoice (operator only): serialize to
    UBL 2.1, hash, chain to the previous cleared invoice (PIH), sign, submit, persist.
    Only mock/sandbox clears; a real gateway or production is refused (not accredited)."""
    _require_super(current_user)
    from app.services.einvoice_clearance import submit_for_clearance
    async with async_session() as session:
        result, error = await submit_for_clearance(
            session, invoice_id, provider=payload.provider,
            environment=payload.environment, submitted_by=current_user.get("email") or "operator")
        if error:
            await session.rollback()
            code = 404 if error == "Invoice not found" else 422
            raise HTTPException(status_code=code, detail=error)
        await session.commit()
    await _audit_invoice("invoice_einvoice_cleared", invoice_id, current_user,
                         {"tenant_id": result.get("tenant_id"),
                          "invoice_number": result["invoice_number"],
                          "clearance_ref": result["clearance_ref"],
                          "environment": result["environment"]})
    result["note"] = _LEGAL_NOTE
    return result


@router.get("/invoices/{invoice_id}/einvoice/submissions")
async def list_einvoice_submissions_endpoint(invoice_id: int,
                                             current_user: dict = Depends(get_current_user)):
    """The clearance ledger for an invoice (documents, hashes, PIH chain, clearance refs)."""
    _require_super(current_user)
    from app.services.einvoice_clearance import list_submissions
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        subs = await list_submissions(session, tenant_id, invoice_id)
    return {"invoice_id": invoice_id, "submissions": subs, "note": _LEGAL_NOTE}


@router.get("/einvoice/submissions/{submission_id}")
async def poll_einvoice_submission_endpoint(submission_id: int,
                                            current_user: dict = Depends(get_current_user)):
    """Poll a single clearance submission's state (terminal for mock/sandbox)."""
    _require_super(current_user)
    from app.services.einvoice_clearance import poll_clearance
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        sub = await poll_clearance(session, tenant_id, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    sub["note"] = _LEGAL_NOTE
    return sub
