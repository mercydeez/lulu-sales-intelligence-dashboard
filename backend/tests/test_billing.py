"""
UAE billing + VAT invoices (Phase 4) — pure money math (no DB).

VAT correctness is the product here: VALUE in AED, VAT explicit, totals reconcile
line-by-line. Live invoice persistence + RLS are covered by the integration suite.
"""
from decimal import Decimal

from app.services.billing import (
    UAE_VAT_RATE, PLAN_PRICES_AED, MANUAL_PROVIDERS, GATEWAY_PROVIDERS,
    is_provider_supported, compute_line, compute_invoice_totals, generate_invoice_number,
    build_invoice_html,
)


def test_invoice_html_shows_trns_vat_and_total():
    inv = {"invoice_number": "INV-202606-0001-1", "status": "issued",
           "supplier_legal_name": "Retail IQ FZ-LLC", "supplier_trn": "100000000000003",
           "customer_legal_name": "Meridian Retail LLC", "customer_trn": "100123456700003",
           "subtotal_aed": 2000, "vat_rate": 0.05, "vat_amount_aed": 100, "total_aed": 2100,
           "payment_terms": "Net 30", "po_number": "PO-9"}
    lines = [{"description": "Growth plan", "quantity": 1, "unit_price_aed": 2000,
              "vat_amount_aed": 100, "line_total_aed": 2100}]
    html = build_invoice_html(inv, lines)
    assert "Tax Invoice" in html
    assert "100000000000003" in html and "100123456700003" in html  # both TRNs
    assert "VAT (5%)" in html
    assert "AED 2,100.00" in html
    assert "PO-9" in html
    assert "qualified UAE legal/tax" in html  # draft disclaimer


def test_uae_vat_rate_is_5_percent():
    assert UAE_VAT_RATE == Decimal("0.05")


def test_compute_line_vat_exclusive():
    line = compute_line("Growth plan — June", quantity=2, unit_price_aed=1000)
    assert line["line_subtotal_aed"] == Decimal("2000.00")
    assert line["vat_amount_aed"] == Decimal("100.00")      # 5% of 2000
    assert line["line_total_aed"] == Decimal("2100.00")


def test_compute_line_rounds_to_fils():
    # 333.33 * 1 @ 5% = 16.6665 -> 16.67 (half-up)
    line = compute_line("odd", quantity=1, unit_price_aed="333.33")
    assert line["vat_amount_aed"] == Decimal("16.67")


def test_invoice_totals_reconcile_line_by_line():
    lines = [
        compute_line("A", 1, 500),
        compute_line("B", 3, 100),
    ]
    totals = compute_invoice_totals(lines)
    assert totals["subtotal_aed"] == Decimal("800.00")      # 500 + 300
    assert totals["vat_amount_aed"] == Decimal("40.00")     # 25 + 15
    assert totals["total_aed"] == Decimal("840.00")
    # Total always equals subtotal + VAT exactly.
    assert totals["total_aed"] == totals["subtotal_aed"] + totals["vat_amount_aed"]


def test_zero_amount_line_has_zero_vat():
    line = compute_line("Free plan", quantity=1, unit_price_aed=0)
    assert line["vat_amount_aed"] == Decimal("0.00")
    assert line["line_total_aed"] == Decimal("0.00")


def test_manual_providers_always_supported():
    for p in MANUAL_PROVIDERS:
        assert is_provider_supported(p) is True


def test_gateways_gated_until_configured(monkeypatch):
    for p in GATEWAY_PROVIDERS:
        monkeypatch.delenv(f"{p.upper()}_API_KEY", raising=False)
        assert is_provider_supported(p) is False
    monkeypatch.setenv("TELR_API_KEY", "test")
    assert is_provider_supported("telr") is True


def test_unknown_provider_unsupported():
    assert is_provider_supported("bitcoin") is False


def test_plan_prices_enterprise_is_custom():
    assert PLAN_PRICES_AED["enterprise"] is None
    assert PLAN_PRICES_AED["free"] == Decimal("0")
    assert PLAN_PRICES_AED["growth"] == Decimal("1999")


def test_invoice_number_format_and_uniqueness():
    from datetime import datetime, timezone
    n1 = generate_invoice_number(7, datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc))
    assert n1.startswith("INV-202606-0007-")
    n2 = generate_invoice_number(7, datetime(2026, 6, 30, 10, 0, 0, 1000, tzinfo=timezone.utc))
    assert n1 != n2  # epoch-ms suffix differs
