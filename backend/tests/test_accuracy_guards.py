"""
Accuracy guards (Phase 1) — lock in the units-vs-AED convention.

The product rule (CLAUDE.md "Units vs currency"): the raw `sales` column is a
**unit count** (volume); monetary **value** is AED, derived as
`SUM(sales * unit_price_aed)`. VOLUME and VALUE must never be mixed on one axis
and a value must never be derived without the price.

These guards are deliberately **hermetic**: they parse source files with `ast`
or scan their text. They need no live Postgres/Redis and do not import the app,
so they run anywhere (and dodge the pinned-`httpx` TestClient trap noted in
CLAUDE.md). They encode the *current, correct* invariants and fail on regression.

Known remaining smell (tracked in implementation.md Phase 1, NOT asserted here so
the suite stays green): `routes/analytics.py` labels an AED sum `total_sales`
typed `int`. Renaming it to `total_revenue: float` is a coordinated
backend+frontend contract change and is intentionally out of scope for these
guards until that rename lands.
"""
import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = REPO_ROOT / "backend" / "app" / "routes"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

KPIS_PY = ROUTES_DIR / "kpis.py"

# Frontend identifiers that hold VOLUME (units). Wrapping any of these in a
# currency formatter is the exact class of bug Phase 1 fixed (admin "Sales
# Today"/"Revenue (30d)" cards, KPICards "Avg Daily Sales").
VOLUME_FIELDS = (
    "total_sales_today",
    "total_sales_week",
    "total_sales_month",
    "average_daily_sales",
    "sales_today",
    "sales_week",
    "sales_month",
)


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path} not found (unexpected repo layout)")
    return path.read_text(encoding="utf-8")


def _class_annotations(source: str, class_name: str) -> dict:
    """Return {field: annotation_source} for a class's annotated attributes."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            out = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    out[stmt.target.id] = ast.unparse(stmt.annotation)
            return out
    raise AssertionError(f"class {class_name} not found")


# --------------------------------------------------------------------------- #
# Backend: revenue (VALUE) must always be derived via unit_price_aed
# --------------------------------------------------------------------------- #

def test_kpi_revenue_aliases_derive_from_unit_price():
    """Every `... as revenue_*` SQL alias in kpis.py multiplies by unit_price_aed."""
    src = _read(KPIS_PY)
    revenue_lines = [ln for ln in src.splitlines() if re.search(r"\bas\s+revenue_\w+", ln)]
    assert revenue_lines, "expected revenue_* aliases in kpis.py"
    for ln in revenue_lines:
        assert "unit_price_aed" in ln, (
            f"revenue alias derived without unit_price_aed (units mislabeled as AED): {ln.strip()}"
        )


def test_revenue_labels_across_routes_use_unit_price():
    """Any route line that labels a result as revenue must carry unit_price_aed.

    Covers the admin Stores 'Revenue (30d)' card regression: an AED VALUE column
    must be `SUM(sales * unit_price_aed)`, never a bare unit sum.
    """
    offenders = []
    for py in ROUTES_DIR.glob("*.py"):
        for ln in py.read_text(encoding="utf-8").splitlines():
            labels_revenue = re.search(r"as\s+(total_)?revenue|label\(\s*['\"](total_)?revenue", ln)
            if labels_revenue and "SUM" in ln.upper() and "unit_price_aed" not in ln:
                offenders.append(f"{py.name}: {ln.strip()}")
    assert not offenders, "revenue VALUE derived without unit_price_aed:\n" + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# Backend: KPI volume fields are integer units; value fields are float AED
# --------------------------------------------------------------------------- #

def test_kpi_response_volume_fields_are_int():
    ann = _class_annotations(_read(KPIS_PY), "KPIResponse")
    for f in ("total_sales_today", "total_sales_week", "total_sales_month"):
        assert ann.get(f) == "int", f"{f} should be int units, got {ann.get(f)!r}"


def test_kpi_response_value_fields_are_float():
    ann = _class_annotations(_read(KPIS_PY), "KPIResponse")
    for f in (
        "total_revenue_today",
        "total_revenue_week",
        "total_revenue_month",
        "average_daily_revenue",
    ):
        assert ann.get(f) == "float", f"{f} should be float AED, got {ann.get(f)!r}"


def test_kpi_volume_sql_casts_integer_and_revenue_numeric():
    """Volume aggregates cast `::integer`; revenue aggregates cast `::numeric`."""
    src = _read(KPIS_PY)
    for ln in src.splitlines():
        if re.search(r"\bas\s+sales_(today|week|month)\b", ln):
            assert "::integer" in ln, f"volume column not cast to integer units: {ln.strip()}"
        if re.search(r"\bas\s+revenue_(today|week|month)\b", ln):
            assert "::numeric" in ln, f"revenue column not cast to numeric AED: {ln.strip()}"


# --------------------------------------------------------------------------- #
# Frontend: never format a VOLUME field as currency
# --------------------------------------------------------------------------- #

def test_frontend_does_not_currency_format_volume_fields():
    if not FRONTEND_SRC.exists():
        pytest.skip("frontend/src not found")
    pattern = re.compile(r"formatCurrency\(([^)]*)\)")
    offenders = []
    for ext in ("*.ts", "*.tsx"):
        for f in FRONTEND_SRC.rglob(ext):
            text = f.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                arg = m.group(1)
                if any(re.search(rf"\b{re.escape(field)}\b", arg) for field in VOLUME_FIELDS):
                    offenders.append(f"{f.relative_to(REPO_ROOT)}: formatCurrency({arg.strip()})")
                if re.search(r"\b\w*_units\b", arg):
                    offenders.append(f"{f.relative_to(REPO_ROOT)}: formatCurrency({arg.strip()}) [units]")
    assert not offenders, "VOLUME (units) field rendered as currency:\n" + "\n".join(offenders)
