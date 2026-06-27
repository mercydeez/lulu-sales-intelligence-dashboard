"""
Golden-number integration tests (PRODUCT_BUILD_PLAN.md / A1).

These hit a RUNNING stack and assert that aggregations are correct and the
units/AED derivation holds — so an aggregation regression (or re-introducing the
units-as-currency bug) fails CI. They auto-skip when the API is unreachable, so
the DB-free unit suite is unaffected; the CI "smoke" job runs them against a
freshly booted stack.

Pinned constants come from the deterministic seed: the Kaggle store-item demand
dataset is 10 stores x 50 items x daily 2013-2017 => 913,000 historical rows.
Item prices (migration 005) span AED 3.50-68.00, so derived revenue/units must
fall inside that band. Week/month windows shift with the live generator, so we
assert invariants and ratios rather than brittle exact sums.
"""
import json
import os
import time
import urllib.error
import urllib.request

import pytest

# 127.0.0.1 (not "localhost") so the check doesn't hang on IPv6 ::1 where Docker
# publishes the port on IPv4 only (Windows resolves localhost to ::1 first).
API = os.environ.get("SMOKE_API_URL", "http://127.0.0.1:8000").rstrip("/")
LOGIN = {"email": "atharva@retaildemo.app", "password": "Demo@2026!"}

# Per-request timeout (s). Generous + overridable because these tests can run while
# the forecast trainer + live generator + a parallel suite all contend for the loop;
# a transient slow response under that load is not a product defect. Pair with a
# small retry (below) so a one-off timeout doesn't flake the whole suite.
REQUEST_TIMEOUT = float(os.environ.get("GOLDEN_REQUEST_TIMEOUT", "30"))
REQUEST_RETRIES = int(os.environ.get("GOLDEN_REQUEST_RETRIES", "3"))

MIN_ITEM_PRICE_AED = 3.50
MAX_ITEM_PRICE_AED = 68.00
EXPECTED_HISTORICAL_ROWS = 913_000
EXPECTED_STORES = 10
EXPECTED_ITEMS = 50


def _request(req: urllib.request.Request) -> dict:
    """Open a request, retrying transient timeouts/connection resets with backoff so
    a load spike doesn't fail an otherwise-correct assertion."""
    last: Exception | None = None
    for attempt in range(REQUEST_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last  # exhausted retries


def _post(path: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _request(req)


def _get(path: str, token: str | None = None) -> dict:
    req = urllib.request.Request(f"{API}{path}", method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return _request(req)


def _api_up() -> bool:
    try:
        with urllib.request.urlopen(f"{API}/health", timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


pytestmark = pytest.mark.skipif(not _api_up(), reason=f"API not reachable at {API}")


@pytest.fixture(scope="module")
def token() -> str:
    return _post("/api/auth/login", LOGIN)["access_token"]


@pytest.fixture(scope="module")
def kpis(token) -> dict:
    return _get("/api/kpis", token)


def test_seed_shape_is_stable(kpis):
    assert kpis["total_historical_records"] == EXPECTED_HISTORICAL_ROWS
    assert kpis["unique_stores"] == EXPECTED_STORES
    assert kpis["unique_items"] == EXPECTED_ITEMS


def test_volume_fields_are_integer_units(kpis):
    for f in ("total_sales_today", "total_sales_week", "total_sales_month"):
        assert isinstance(kpis[f], int), f"{f} must be integer units, got {type(kpis[f])}"


def test_revenue_fields_are_aed_floats(kpis):
    for f in ("total_revenue_today", "total_revenue_week", "total_revenue_month"):
        assert isinstance(kpis[f], (int, float))


def test_revenue_is_derived_within_price_band(kpis):
    """revenue = units x unit_price_aed, so revenue/units must sit inside the
    seeded per-item price band. Catches both the old units-as-AED bug (ratio ~1)
    and any bogus derivation (ratio outside the band)."""
    units = kpis["total_sales_month"]
    revenue = kpis["total_revenue_month"]
    assert units > 0 and revenue > 0, "month window should have data"
    ratio = revenue / units
    assert MIN_ITEM_PRICE_AED * 0.5 <= ratio <= MAX_ITEM_PRICE_AED * 1.5, (
        f"implied avg price AED {ratio:.2f} is outside the seeded band "
        f"[{MIN_ITEM_PRICE_AED}, {MAX_ITEM_PRICE_AED}] — revenue derivation looks wrong"
    )
    # Revenue must exceed units (avg price > 1 AED) — the smoking gun for the
    # historical 'units rendered as AED' bug would be ratio == 1.0 exactly.
    assert revenue > units


def test_analytics_categories_use_total_revenue_key(token):
    data = _get("/api/analytics/categories", token)["data"]
    assert data, "categories should not be empty"
    assert "total_revenue" in data[0], "analytics must expose total_revenue (AED), not total_sales"
    assert "total_sales" not in data[0]
