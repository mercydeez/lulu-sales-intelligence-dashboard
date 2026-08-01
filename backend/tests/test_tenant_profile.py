"""
UAE tenant legal/billing profile (Phase 1).

Unit-covers the pure validation that runs before any DB access (TRN/emirate/
jurisdiction/currency/contacts) and confirms the routes are registered with the
right auth posture. Cross-tenant RLS isolation is proven by the live integration
suite (test_tenant_isolation.py) — these run with no Postgres.
"""
from fastapi.testclient import TestClient

from app.services.uae_profile import validate_profile, EMIRATES
from tests.conftest import registered_paths


def test_valid_partial_profile_passes():
    cleaned, err = validate_profile({
        "legal_name": "Meridian Retail LLC",
        "emirate": "dubai",
        "jurisdiction": "mainland",
        "trn": "100123456700003",
        "vat_registered": True,
    })
    assert err is None
    assert cleaned["emirate"] == "dubai"
    assert cleaned["trn"] == "100123456700003"
    assert cleaned["vat_registered"] is True


def test_trn_accepts_spaced_and_dashed_then_normalises():
    cleaned, err = validate_profile({"trn": "100-1234-5670-0003"})
    assert err is None
    assert cleaned["trn"] == "100123456700003"  # separators stripped


def test_trn_wrong_length_rejected():
    cleaned, err = validate_profile({"trn": "12345"})
    assert cleaned is None
    assert err and "15 digits" in err


def test_invalid_emirate_rejected():
    cleaned, err = validate_profile({"emirate": "doha"})
    assert cleaned is None
    assert err and "Invalid emirate" in err


def test_all_seven_emirates_accepted():
    for e in EMIRATES:
        cleaned, err = validate_profile({"emirate": e})
        assert err is None and cleaned["emirate"] == e


def test_invalid_jurisdiction_rejected():
    cleaned, err = validate_profile({"jurisdiction": "offshore"})
    assert cleaned is None and err and "jurisdiction" in err


def test_blank_strings_normalise_to_null():
    cleaned, err = validate_profile({"legal_name": "   ", "trading_name": ""})
    assert err is None
    assert cleaned["legal_name"] is None and cleaned["trading_name"] is None


def test_negative_store_count_rejected():
    cleaned, err = validate_profile({"store_count": -3})
    assert cleaned is None and err and "negative" in err


def test_bad_billing_email_rejected():
    cleaned, err = validate_profile({"billing_contact_email": "not-an-email"})
    assert cleaned is None and err and "email" in err


def test_currency_uppercased():
    cleaned, err = validate_profile({"currency": "aed"})
    assert err is None and cleaned["currency"] == "AED"


def test_unknown_keys_ignored():
    cleaned, err = validate_profile({"hacker": "drop table", "legal_name": "OK"})
    assert err is None
    assert "hacker" not in cleaned and cleaned["legal_name"] == "OK"


def test_billing_profile_routes_registered():
    from app.main import app
    paths = registered_paths(app)
    assert "/api/tenants/billing-profile" in paths


def test_billing_profile_requires_auth():
    from app.main import app
    client = TestClient(app)
    # GET hits auth (401). PUT is state-changing, so the Bearer-exempt CSRF
    # middleware rejects the un-authenticated request first (403) — both are
    # correct "you can't touch this without auth" outcomes.
    assert client.get("/api/tenants/billing-profile").status_code == 401
    assert client.put("/api/tenants/billing-profile", json={"legal_name": "X"}).status_code in (401, 403)
