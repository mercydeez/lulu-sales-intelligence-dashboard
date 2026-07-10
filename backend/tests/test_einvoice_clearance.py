"""E10-4 — UAE-FTA e-invoice CLEARANCE harness.

einvoicing.py already refuses a real gateway (P1.2); this harness adds the document
machinery — UBL 2.1 serialization, canonical hashing, the PIH (previous-invoice-hash)
chain, and a signing scaffold — behind the SAME honest boundary:

  * only mock/sandbox actually clears; a real gateway or the production environment is
    refused (no accreditation, no signing certificate);
  * a sandbox run can never assert a production signature (is_production_signed=FALSE),
    and migration 071's CHECK enforces that at the DB;
  * nothing but the invoice's own e_invoice_* fields + the submissions ledger is written
    — the clearance harness never touches sales.

The pure builders unit-test with no DB. The live round-trip (clear invoice A → PIH null
→ clear invoice B → PIH == hash(A) → uae_fta refused → production refused → stored hash
reproduces the stored UBL) is verified against the running stack in the commit.
"""
import ast
import inspect
import pathlib
import textwrap
from xml.etree import ElementTree as ET

import pytest

from app.services import einvoice_clearance as clr


def _find_migration(name: str) -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("071_krishna_einvoice_clearance.sql")

_INV = {
    "invoice_number": "INV-CLR-A", "status": "issued", "currency": "AED",
    "supplier_legal_name": "Retail IQ FZ-LLC", "supplier_trn": "100000000000003",
    "customer_legal_name": "Meridian Retail LLC", "customer_trn": "100123456700003",
    "subtotal_aed": "1000.00", "vat_rate": "0.05", "vat_amount_aed": "50.00",
    "total_aed": "1050.00", "issued_at": "2026-07-10T00:00:00Z",
}
_LINES = [{"description": "Pro plan", "quantity": "1", "unit_price_aed": "1000.00",
           "line_subtotal_aed": "1000.00", "vat_amount_aed": "50.00", "line_total_aed": "1050.00"}]


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# UBL 2.1 serialization.
# --------------------------------------------------------------------------

def test_ubl_is_well_formed_xml():
    xml = clr.build_ubl_invoice(_INV, _LINES)
    root = ET.fromstring(xml)  # raises if malformed
    assert root.tag.endswith("}Invoice")


def test_ubl_carries_trns_totals_and_lines():
    xml = clr.build_ubl_invoice(_INV, _LINES)
    assert "100000000000003" in xml and "100123456700003" in xml  # both TRNs
    assert "INV-CLR-A" in xml
    assert "1050.00" in xml  # payable/tax-inclusive total
    assert xml.count("<cac:InvoiceLine>") == 1
    assert clr.UBL_CUSTOMIZATION_ID in xml  # the FTA/PINT-AE profile id


def test_ubl_escapes_content():
    inv = {**_INV, "customer_legal_name": "A & B <Co>"}
    xml = clr.build_ubl_invoice(inv, [])
    assert "&amp;" in xml and "&lt;Co&gt;" in xml
    ET.fromstring(xml)  # still well-formed after escaping


def test_ubl_is_deterministic():
    assert clr.build_ubl_invoice(_INV, _LINES) == clr.build_ubl_invoice(_INV, _LINES)


# --------------------------------------------------------------------------
# Hash + signature.
# --------------------------------------------------------------------------

def test_hash_is_stable_and_content_sensitive():
    xml = clr.build_ubl_invoice(_INV, _LINES)
    h1 = clr.canonical_hash(xml)
    assert h1 == clr.canonical_hash(xml)                       # stable
    assert len(h1) == 64                                       # sha-256 hex
    other = clr.build_ubl_invoice({**_INV, "total_aed": "9999.00"}, _LINES)
    assert clr.canonical_hash(other) != h1                     # content-sensitive


def test_sandbox_signature_is_labelled_and_not_production():
    sig, is_prod = clr.sign_document("<x/>", "a" * 64, environment=clr.SANDBOX, previous_hash=None)
    assert is_prod is False
    assert sig.startswith("SANDBOX-UNSIGNED-")


def test_sandbox_signature_chains_the_pih():
    genesis = clr.sign_document("<x/>", "a" * 64, environment=clr.SANDBOX, previous_hash=None)[0]
    chained = clr.sign_document("<x/>", "a" * 64, environment=clr.SANDBOX, previous_hash="b" * 64)[0]
    assert genesis != chained  # the previous hash participates in the signature


def test_production_signing_refuses_without_a_certificate():
    with pytest.raises(NotImplementedError, match="accredited signing certificate"):
        clr.sign_document("<x/>", "a" * 64, environment=clr.PRODUCTION, previous_hash=None)


# --------------------------------------------------------------------------
# submit_for_clearance — refusals happen before any DB write.
# --------------------------------------------------------------------------

class _ExplodingDB:
    async def execute(self, *a, **k):
        raise AssertionError("DB touched on a refused clearance")

    async def commit(self):
        raise AssertionError("DB commit on a refused clearance")


@pytest.mark.asyncio
async def test_real_gateway_is_refused_before_db(monkeypatch):
    # Key present so the provider is 'available' — it must STILL refuse (not integrated).
    monkeypatch.setenv("UAE_FTA_API_KEY", "present-but-not-integrated")
    result, err = await clr.submit_for_clearance(_ExplodingDB(), 1, provider="uae_fta",
                                                 environment=clr.SANDBOX)
    assert result is None and "not yet integrated" in err


@pytest.mark.asyncio
async def test_production_is_refused_before_db():
    result, err = await clr.submit_for_clearance(_ExplodingDB(), 1, provider="mock",
                                                 environment=clr.PRODUCTION)
    assert result is None and "Production clearance is refused" in err


@pytest.mark.asyncio
async def test_unknown_environment_is_refused():
    result, err = await clr.submit_for_clearance(_ExplodingDB(), 1, provider="mock",
                                                 environment="live")
    assert result is None and "Unknown environment" in err


# --------------------------------------------------------------------------
# The harness writes only the invoice + submissions ledger — never sales.
# --------------------------------------------------------------------------

def test_clearance_never_touches_sales():
    code = _code(clr.submit_for_clearance)
    assert "einvoice_submissions" in code
    for forbidden in ("sales_fact_view", "sales_stream_raw", "sales_historical",
                      "sales_rollup_daily"):
        assert forbidden not in code


def test_pih_reads_only_cleared_submissions():
    code = _code(clr.get_previous_hash)
    assert "status = 'cleared'" in code and "einvoice_submissions" in code


def test_provider_gating_is_delegated_to_einvoicing():
    """One source of truth for what is integrated — the harness must reuse einvoicing's
    gating, not fork its own IMPLEMENTED list."""
    code = _code(clr.submit_for_clearance)
    assert "einvoicing.is_provider_available" in code
    assert "einvoicing.is_provider_implemented" in code


# --------------------------------------------------------------------------
# Migration guards.
# --------------------------------------------------------------------------

def test_migration_enforces_clearance_invariants():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    # cleared requires a document hash + a clearance ref.
    assert "einvoice_submissions_cleared_has_proof" in ddl
    assert "status <> 'cleared' or (clearance_ref is not null and invoice_hash is not null)" in ddl
    # a production signature can only exist in production (no sandbox forgery).
    assert "einvoice_submissions_prod_sig_only_in_prod" in ddl
    assert "is_production_signed = false or environment = 'production'" in ddl
    assert "environment in ('sandbox', 'production')" in ddl
    assert "enable row level security" in ddl and "force row level security" in ddl


# --------------------------------------------------------------------------
# Route wiring.
# --------------------------------------------------------------------------

def test_clearance_endpoints_are_operator_only():
    from app.routes import billing as b
    for fn in (b.clear_einvoice_endpoint, b.einvoice_clearance_config,
               b.list_einvoice_submissions_endpoint, b.poll_einvoice_submission_endpoint):
        assert "_require_super(current_user)" in _code(fn)


def test_config_endpoint_reports_only_mock_sandbox_clears():
    from app.routes import billing as b
    code = _code(b.einvoice_clearance_config)
    assert "clears_only" in code
