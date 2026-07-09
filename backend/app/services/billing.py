"""
UAE billing + VAT invoices (Phase 4).

Provider-abstracted and manual-first: manual invoice / bank transfer / purchase
order need NO external service, so billing works in local dev and for enterprise
procurement out of the box. Stripe/Telr/PayTabs/etc. are recognised but gated as
"not configured" until wired — adding one later does not touch the data model.

Money is AED with explicit VAT (UAE standard 5%). VALUE in AED, never mixed with
units (the repo-wide convention). The pure helpers (VAT math, invoice number,
provider checks) unit-test with no DB.

LEGAL/TAX: invoice/VAT modelling only — NOT a compliance guarantee. Draft —
requires review by a qualified UAE legal/tax professional before production use.
"""
from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

UAE_VAT_RATE = Decimal("0.05")  # standard rate; draft — confirm with a tax professional

# Monthly list prices (AED). enterprise/None => custom (manual invoice / PO).
PLAN_PRICES_AED: Dict[str, Optional[Decimal]] = {
    "free":       Decimal("0"),
    "starter":    Decimal("499"),
    "growth":     Decimal("1999"),
    "enterprise": None,
}

# Providers that need no integration work — usable today.
MANUAL_PROVIDERS = {"manual", "bank_transfer", "purchase_order"}
# Recognised gateways, gated until configured (added later, no schema change).
GATEWAY_PROVIDERS = {"stripe", "telr", "paytabs", "network", "checkout"}
ALL_PROVIDERS = MANUAL_PROVIDERS | GATEWAY_PROVIDERS


def is_provider_supported(name: str) -> bool:
    """Manual providers are always usable. A gateway is 'supported' only once its
    credentials are present in the environment (none are wired yet → all gated)."""
    if name in MANUAL_PROVIDERS:
        return True
    if name in GATEWAY_PROVIDERS:
        return bool(os.getenv(f"{name.upper()}_API_KEY"))
    return False


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_line(description: str, quantity, unit_price_aed,
                 vat_rate: Decimal = UAE_VAT_RATE) -> Dict:
    """VAT-exclusive line: subtotal = qty×unit, VAT on top, total = subtotal+VAT."""
    qty = Decimal(str(quantity))
    unit = _money(unit_price_aed)
    subtotal = _money(qty * unit)
    vat = _money(subtotal * vat_rate)
    return {
        "description": description,
        "quantity": qty,
        "unit_price_aed": unit,
        "line_subtotal_aed": subtotal,
        "vat_rate": vat_rate,
        "vat_amount_aed": vat,
        "line_total_aed": _money(subtotal + vat),
    }


def compute_invoice_totals(lines: List[Dict]) -> Dict:
    """Sum the line amounts. VAT is summed at line level (not recomputed on the
    grand subtotal) so the invoice always reconciles line-by-line."""
    subtotal = sum((l["line_subtotal_aed"] for l in lines), Decimal("0"))
    vat = sum((l["vat_amount_aed"] for l in lines), Decimal("0"))
    return {
        "subtotal_aed": _money(subtotal),
        "vat_amount_aed": _money(vat),
        "total_aed": _money(subtotal + vat),
    }


def generate_invoice_number(tenant_id: int, when: Optional[datetime] = None) -> str:
    """Human-readable, sortable, globally unique: INV-<YYYYMM>-<tenant>-<epoch_ms>.
    The epoch suffix guarantees uniqueness without a DB sequence."""
    when = when or datetime.now(timezone.utc)
    return f"INV-{when:%Y%m}-{tenant_id:04d}-{int(when.timestamp() * 1000)}"


def _supplier_details() -> Dict[str, Optional[str]]:
    """The platform's own legal/VAT identity for the invoice 'from' block. Draft
    defaults; override via env before issuing real invoices."""
    return {
        "supplier_legal_name": os.getenv(
            "PLATFORM_SUPPLIER_NAME", f"{get_settings().product_name} FZ-LLC (draft)"
        ),
        "supplier_trn": os.getenv("PLATFORM_SUPPLIER_TRN"),  # None until set — draft
    }


# Plan catalogue for the pricing page (AED-first). Limits come from plan_limits +
# usage_metering so the page never drifts from what's enforced. Draft pricing.
_PLAN_FEATURES: Dict[str, List[str]] = {
    "free": ["Demo or limited real data", "1 user", "Dashboards + Sage AI", "Community support"],
    "starter": ["CSV import", "Sage AI assistant", "Forecasting", "Findings & outcomes", "Email support"],
    "growth": ["Everything in Starter", "Public API + webhooks", "Advanced forecasting",
               "Team roles", "Priority support"],
    "enterprise": ["Custom AED pricing", "Manual invoice / PO", "SLA + SSO (roadmap)",
                   "Dedicated support", "Security review", "Optional dedicated deployment"],
}
_PLAN_TAGLINE = {
    "free": "Try it", "starter": "Small retailer", "growth": "Regional retailer", "enterprise": "Large / multi-region",
}


def plans_catalog() -> List[Dict]:
    """Plan cards for the pricing page. Prices/limits stay in sync with what's
    enforced (plan_limits + usage_metering). Draft — confirm pricing before sale."""
    from app.services.plan_limits import PLAN_LIMITS
    from app.services.usage_metering import USAGE_LIMITS
    out = []
    for plan in ("free", "starter", "growth", "enterprise"):
        price = PLAN_PRICES_AED.get(plan)
        out.append({
            "plan": plan,
            "tagline": _PLAN_TAGLINE[plan],
            "monthly_price_aed": (None if price is None else float(price)),
            "custom_pricing": price is None,
            "limits": {
                "users": PLAN_LIMITS[plan]["users"],
                "api_requests_month": USAGE_LIMITS[plan]["api_requests"],
                "sage_messages_month": USAGE_LIMITS[plan]["sage_messages"],
            },
            "features": _PLAN_FEATURES[plan],
        })
    return out


def _inv_aed(v) -> str:
    return f"AED {float(v or 0):,.2f}"


def build_invoice_html(inv: Dict, lines: List[Dict]) -> str:
    """Self-contained, browser-printable UAE Tax Invoice (→ PDF). Pure. Shows both
    TRNs, the VAT breakdown, and payment instructions. Draft until legal review."""
    rows = "".join(
        f"<tr><td>{l.get('description','')}</td>"
        f"<td class='r'>{float(l.get('quantity') or 0):g}</td>"
        f"<td class='r'>{_inv_aed(l.get('unit_price_aed'))}</td>"
        f"<td class='r'>{_inv_aed(l.get('vat_amount_aed'))}</td>"
        f"<td class='r'>{_inv_aed(l.get('line_total_aed'))}</td></tr>"
        for l in lines
    )
    vat_pct = round(float(inv.get("vat_rate") or 0.05) * 100)
    po = f"<div>PO: {inv['po_number']}</div>" if inv.get("po_number") else ""
    instr = (f"<div class='box'><strong>Payment instructions</strong><br>{inv['payment_instructions']}</div>"
             if inv.get("payment_instructions") else "")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Tax Invoice {inv.get('invoice_number','')}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;max-width:760px;margin:32px auto;padding:0 20px}}
 h1{{font-size:22px;margin:0}} .muted{{color:#666;font-size:13px}}
 .head{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px}}
 .parties{{display:flex;justify-content:space-between;gap:24px;margin:20px 0}}
 .parties>div{{flex:1}} .lbl{{font-size:11px;text-transform:uppercase;color:#888;margin-bottom:3px}}
 table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}}
 th,td{{padding:9px 8px;border-bottom:1px solid #eee;text-align:left}} th{{font-size:11px;text-transform:uppercase;color:#666}}
 td.r,th.r{{text-align:right}}
 .totals{{margin-top:16px;margin-left:auto;width:280px}}
 .totals div{{display:flex;justify-content:space-between;padding:4px 0}}
 .totals .grand{{font-size:18px;font-weight:700;border-top:2px solid #1a1a1a;padding-top:8px;margin-top:6px}}
 .box{{background:#f7f7f5;border-radius:8px;padding:12px;margin-top:16px;font-size:13px}}
 .foot{{margin-top:28px;font-size:11px;color:#999;border-top:1px solid #eee;padding-top:12px}}
</style></head><body>
<div class="head">
  <div><h1>Tax Invoice</h1><div class="muted">{inv.get('invoice_number','')}</div></div>
  <div class="muted" style="text-align:right">
    <div>Status: {inv.get('status','')}</div>
    {po}
    <div>Terms: {inv.get('payment_terms') or '—'}</div>
  </div>
</div>
<div class="parties">
  <div><div class="lbl">From (supplier)</div><div>{inv.get('supplier_legal_name') or '—'}</div>
    <div class="muted">TRN {inv.get('supplier_trn') or '—'}</div></div>
  <div><div class="lbl">Bill to (customer)</div><div>{inv.get('customer_legal_name') or '—'}</div>
    <div class="muted">TRN {inv.get('customer_trn') or '—'}</div></div>
</div>
<table><thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th><th class="r">VAT</th><th class="r">Amount</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="totals">
  <div><span>Subtotal</span><span>{_inv_aed(inv.get('subtotal_aed'))}</span></div>
  <div><span>VAT ({vat_pct}%)</span><span>{_inv_aed(inv.get('vat_amount_aed'))}</span></div>
  <div class="grand"><span>Total</span><span>{_inv_aed(inv.get('total_aed'))}</span></div>
</div>
{instr}
<p class="foot">Draft — VAT/invoice content requires review by a qualified UAE legal/tax
professional before production/customer use. Generated by {get_settings().product_name}.</p>
</body></html>"""


async def create_invoice(
    db: AsyncSession, tenant_id: int, *, lines: List[Dict],
    billing_provider: str = "manual", period_start=None, period_end=None,
    po_number: Optional[str] = None, payment_terms: Optional[str] = "Net 30",
    payment_instructions: Optional[str] = None, vat_rate: Decimal = UAE_VAT_RATE,
) -> Dict:
    """Build a draft VAT invoice for a tenant: snapshot supplier (env) + customer
    (tenant_billing_profile) identity, compute AED totals, persist invoice + lines.
    Caller commits. Returns the invoice dict (Decimals as floats for JSON)."""
    computed = [compute_line(l["description"], l.get("quantity", 1),
                             l.get("unit_price_aed", 0), vat_rate) for l in lines]
    totals = compute_invoice_totals(computed)

    supplier = _supplier_details()
    cust = (await db.execute(text("""
        SELECT legal_name, trn FROM tenant_billing_profile WHERE tenant_id = :tid
    """), {"tid": tenant_id})).fetchone()

    number = generate_invoice_number(tenant_id)
    inv = (await db.execute(text("""
        INSERT INTO invoices (
            tenant_id, invoice_number, status, billing_provider,
            supplier_legal_name, supplier_trn, customer_legal_name, customer_trn,
            currency, subtotal_aed, vat_rate, vat_amount_aed, total_aed,
            period_start, period_end, po_number, payment_terms, payment_instructions)
        VALUES (:tid, :num, 'draft', :prov,
                :sname, :strn, :cname, :ctrn,
                'AED', :sub, :rate, :vat, :total,
                :ps, :pe, :po, :terms, :instr)
        RETURNING id, invoice_number, status, total_aed
    """), {
        "tid": tenant_id, "num": number, "prov": billing_provider,
        "sname": supplier["supplier_legal_name"], "strn": supplier["supplier_trn"],
        "cname": cust.legal_name if cust else None, "ctrn": cust.trn if cust else None,
        "sub": str(totals["subtotal_aed"]), "rate": str(vat_rate),
        "vat": str(totals["vat_amount_aed"]), "total": str(totals["total_aed"]),
        "ps": period_start, "pe": period_end, "po": po_number,
        "terms": payment_terms, "instr": payment_instructions,
    })).fetchone()

    invoice_id = inv.id
    for l in computed:
        await db.execute(text("""
            INSERT INTO invoice_lines (invoice_id, description, quantity, unit_price_aed,
                line_subtotal_aed, vat_rate, vat_amount_aed, line_total_aed)
            VALUES (:iid, :desc, :qty, :unit, :sub, :rate, :vat, :total)
        """), {"iid": invoice_id, "desc": l["description"], "qty": str(l["quantity"]),
               "unit": str(l["unit_price_aed"]), "sub": str(l["line_subtotal_aed"]),
               "rate": str(l["vat_rate"]), "vat": str(l["vat_amount_aed"]),
               "total": str(l["line_total_aed"])})

    return {
        "id": invoice_id, "invoice_number": number, "status": "draft",
        "subtotal_aed": float(totals["subtotal_aed"]),
        "vat_amount_aed": float(totals["vat_amount_aed"]),
        "total_aed": float(totals["total_aed"]),
        "line_count": len(computed),
    }
