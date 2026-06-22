"""
Accuracy guard tests — static invariants that make "accuracy is the product"
enforceable in CI (PRODUCT_BUILD_PLAN.md / implementation.md Phase A1).

These are deliberately DB-free: they read the source tree and assert the
units-vs-AED convention can't silently regress. Convention:
  * VOLUME metrics are integer UNITS  -> total_sales_* / formatNumber/formatQuantity
  * VALUE metrics are AED revenue floats -> total_revenue_* / formatCurrency
  * never mixed on one axis; reference: backend/app/routes/kpis.py
"""
import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]          # .../backend
REPO_ROOT = BACKEND_ROOT.parent                              # repo root
ROUTES = BACKEND_ROOT / "app" / "routes"
SERVICES = BACKEND_ROOT / "app" / "services"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


# --------------------------------------------------------------------------
# Guard 1: AED endpoints must not expose a JSON key called "total_sales".
# total_sales is a UNITS name; revenue endpoints carry AED, so the contract
# field must be total_revenue. (This locks the analytics.py rename.)
# --------------------------------------------------------------------------
def test_analytics_has_no_total_sales_output_key():
    src = _read(ROUTES / "analytics.py")
    # The double-quoted form is a JSON output key. The single-quoted
    # .label('total_sales') internal alias is allowed (not part of the contract).
    assert '"total_sales"' not in src, (
        "analytics.py exposes a JSON key 'total_sales' that holds AED revenue. "
        "Rename it to 'total_revenue' — total_sales denotes units."
    )


def test_admin_aed_field_is_named_revenue():
    src = _read(ROUTES / "admin.py")
    assert "total_sales_30d" not in src, (
        "admin.py 'total_sales_30d' holds AED revenue (units x unit_price_aed); "
        "it must be named 'total_revenue_30d'."
    )


# --------------------------------------------------------------------------
# Guard 2: revenue is always DERIVED as units * unit_price_aed, never raw sales.
# Every analytics money aggregation must multiply by unit_price_aed.
# --------------------------------------------------------------------------
def test_analytics_revenue_is_derived_from_unit_price():
    src = _read(ROUTES / "analytics.py")
    # Each total_revenue output must be backed by a sum that includes unit_price_aed.
    assert "unit_price_aed" in src, "analytics.py must derive AED via unit_price_aed"
    # No analytics money aggregation should sum bare Sale.sales as a revenue value:
    # guard against re-introducing func.sum(Sale.sales) labelled as revenue.
    bad = re.findall(r"func\.sum\(\s*Sale\.sales\s*\)\.label\(\s*['\"]total_revenue", src)
    assert not bad, "total_revenue must be SUM(sales * unit_price_aed), not SUM(sales)"


# --------------------------------------------------------------------------
# Guard 3: KPI volume fields are integer units; revenue fields are AED floats.
# kpis.py is the reference implementation of the convention.
# --------------------------------------------------------------------------
def test_kpi_response_types_follow_convention():
    src = _read(ROUTES / "kpis.py")
    for field in ("total_sales_today", "total_sales_week", "total_sales_month"):
        assert re.search(rf"{field}\s*:\s*int", src), f"{field} must be typed int (units)"
    for field in ("total_revenue_today", "total_revenue_week", "total_revenue_month"):
        assert re.search(rf"{field}\s*:\s*float", src), f"{field} must be typed float (AED)"


# --------------------------------------------------------------------------
# Guard 4: a SINGLE price source. Only data_sync.py may define CATEGORY_COSTS,
# and it must be refreshable from items.unit_price_aed (no parallel hardcoded
# price tables that can drift from the revenue math).
# --------------------------------------------------------------------------
def test_single_price_source():
    defs = []
    for p in SERVICES.rglob("*.py"):
        if re.search(r"^\s*CATEGORY_COSTS\s*=\s*\{", _read(p), re.MULTILINE):
            defs.append(p.name)
    for p in ROUTES.rglob("*.py"):
        if re.search(r"^\s*CATEGORY_COSTS\s*=\s*\{", _read(p), re.MULTILINE):
            defs.append(p.name)
    assert defs == ["data_sync.py"], (
        f"CATEGORY_COSTS must be defined once (data_sync.py); found in {defs}"
    )
    ds = _read(SERVICES / "data_sync.py")
    assert "def refresh_category_costs" in ds, (
        "data_sync must derive CATEGORY_COSTS from items.unit_price_aed at startup"
    )


# --------------------------------------------------------------------------
# Guard 5 (frontend): formatCurrency must never be bound to a *units* field,
# and the AED analytics charts must not bind to total_sales. Best-effort — skips
# cleanly if the frontend tree isn't present (e.g. backend-only CI job).
# --------------------------------------------------------------------------
@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="frontend tree not present")
def test_frontend_does_not_format_units_as_currency():
    offenders = []
    units_fields = ("total_sales", "items_sold", "total_sales_today",
                    "total_sales_week", "total_sales_month")
    for tsx in FRONTEND_SRC.rglob("*.tsx"):
        text = _read(tsx)
        for m in re.finditer(r"formatCurrency\(([^)]*)\)", text):
            arg = m.group(1)
            for uf in units_fields:
                # word-boundary so total_sales_week doesn't match total_sales loosely
                if re.search(rf"\b{uf}\b", arg):
                    offenders.append(f"{tsx.relative_to(FRONTEND_SRC)}: formatCurrency({arg})")
    assert not offenders, "formatCurrency() bound to a UNITS field:\n" + "\n".join(offenders)
