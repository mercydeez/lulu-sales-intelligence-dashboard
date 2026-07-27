"""
E-invoicing submission lifecycle (Phase 5) — pure logic (no DB).

Covers provider gating, submittability validation, and payload shape. Live submit
against the invoices table is covered by the integration suite.
"""
from unittest.mock import AsyncMock

import pytest

from app.services.einvoicing import (
    MOCK_PROVIDER, GATEWAY_PROVIDERS, is_provider_available, is_provider_implemented,
    validate_submittable, build_einvoice_payload, submit_einvoice,
)

_GOOD = {
    "status": "issued", "invoice_number": "INV-202606-0001-1",
    "supplier_legal_name": "Retail IQ FZ-LLC", "supplier_trn": "100000000000003",
    "customer_legal_name": "Meridian Retail LLC", "customer_trn": "100123456700003",
    "currency": "AED", "subtotal_aed": "2000.00", "vat_rate": "0.05",
    "vat_amount_aed": "100.00", "total_aed": "2100.00",
}


def test_mock_provider_always_available():
    assert is_provider_available(MOCK_PROVIDER) is True


def test_gateways_gated_until_configured(monkeypatch):
    for p in GATEWAY_PROVIDERS:
        monkeypatch.delenv(f"{p.upper()}_API_KEY", raising=False)
        assert is_provider_available(p) is False
    monkeypatch.setenv("ZATCA_API_KEY", "x")
    assert is_provider_available("zatca") is True


def test_unknown_provider_unavailable():
    assert is_provider_available("paper") is False


# --- P1.2 honesty: a real gateway must never fake acceptance ----------------

def test_only_mock_is_implemented():
    assert is_provider_implemented(MOCK_PROVIDER) is True
    for p in GATEWAY_PROVIDERS:
        assert is_provider_implemented(p) is False


@pytest.mark.asyncio
async def test_configured_real_gateway_is_refused_not_faked(monkeypatch):
    """Even with UAE_FTA_API_KEY set (so the provider is 'available'), submitting
    to it must REFUSE and touch nothing — never mark the invoice accepted."""
    monkeypatch.setenv("UAE_FTA_API_KEY", "present-but-not-integrated")
    assert is_provider_available("uae_fta") is True  # the trap: looks configured

    db = AsyncMock()
    result, error = await submit_einvoice(db, invoice_id=1, provider="uae_fta")

    assert result is None
    assert error is not None and "not yet integrated" in error
    # The honesty guarantee: no SELECT, no UPDATE — the invoice was never touched.
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_unconfigured_gateway_still_refused():
    db = AsyncMock()
    result, error = await submit_einvoice(db, invoice_id=1, provider="zatca")
    assert result is None and "not configured" in error
    db.execute.assert_not_called()


def test_validate_requires_issued():
    bad = {**_GOOD, "status": "draft"}
    ok, err = validate_submittable(bad)
    assert not ok and "issued" in err


def test_validate_requires_supplier_trn():
    bad = {**_GOOD, "supplier_trn": None}
    ok, err = validate_submittable(bad)
    assert not ok and "Supplier TRN" in err


def test_validate_requires_customer_trn():
    bad = {**_GOOD, "customer_trn": ""}
    ok, err = validate_submittable(bad)
    assert not ok and "Customer TRN" in err


def test_validate_passes_for_good_invoice():
    ok, err = validate_submittable(_GOOD)
    assert ok and err is None


def test_payload_carries_trns_and_totals():
    p = build_einvoice_payload(_GOOD)
    assert p["supplier"]["trn"] == "100000000000003"
    assert p["customer"]["trn"] == "100123456700003"
    assert p["totals"]["total_aed"] == "2100.00"
    assert p["schema"].startswith("uae-einvoice")
