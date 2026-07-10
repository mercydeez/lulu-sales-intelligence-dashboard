"""E1-5 — import data-quality report.

The product admits what it cannot see. The scorecard grades the FILE, names the
exact rows, and never silently drops anything: anomalies are warnings, and every
unusable row comes back as a downloadable CSV with the reason attached.

Pure: no DB, no network.
"""
from app.services.csv_import import (
    build_quality_report,
    rejected_rows_csv,
    validate_rows,
)

_SALES_MAP = {"date": "date", "store": "store", "item": "item", "units": "units"}
_HEADERS = ["date", "store", "item", "units"]


def _rows(*triples):
    return [{"date": d, "store": s, "item": i, "units": u} for d, s, i, u in triples]


def _report(raw_rows):
    v = validate_rows("sales", _HEADERS, raw_rows, _SALES_MAP)
    return v, build_quality_report("sales", v["valid"], v["errors"], v["summary"]["total"])


# --- missing days ------------------------------------------------------------

def test_missing_days_are_gaps_inside_the_files_own_range():
    """A file covering one week must not be marked down for the other 51."""
    v, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "10"),
        # 2026-06-02 is MISSING
        ("2026-06-03", "Karama", "Milk", "12"),
    ))
    assert rep["missing_days_count"] == 1
    gap = rep["missing_days"][0]
    assert gap["store"] == "Karama"
    assert gap["from"] == "2026-06-01" and gap["to"] == "2026-06-03"
    assert gap["missing"] == ["2026-06-02"]
    # continuity = 2 covered of 3 spanned
    assert rep["scorecard"]["continuity_pct"] == 66.7


def test_a_contiguous_file_has_perfect_continuity():
    _, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "10"),
        ("2026-06-02", "Karama", "Milk", "11"),
    ))
    assert rep["missing_days_count"] == 0
    assert rep["scorecard"]["continuity_pct"] == 100.0


def test_gaps_are_measured_per_store_not_globally():
    """Two stores each covering different weeks are both complete."""
    _, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "10"),
        ("2026-06-02", "Karama", "Milk", "10"),
        ("2026-07-01", "Deira", "Milk", "10"),
        ("2026-07-02", "Deira", "Milk", "10"),
    ))
    assert rep["missing_days_count"] == 0


# --- duplicates --------------------------------------------------------------

def test_duplicate_store_item_date_is_flagged_as_double_counted_revenue():
    _, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "10"),
        ("2026-06-01", "karama", "MILK", "12"),   # same key, different casing
    ))
    assert rep["duplicate_keys_count"] == 1
    d = rep["duplicate_keys"][0]
    assert d["occurrences"] == 2
    assert d["rows"] == [1, 2]
    assert rep["scorecard"]["uniqueness_pct"] == 50.0


def test_distinct_keys_are_not_duplicates():
    _, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "10"),
        ("2026-06-01", "Karama", "Bread", "10"),
    ))
    assert rep["duplicate_keys_count"] == 0
    assert rep["scorecard"]["uniqueness_pct"] == 100.0


# --- unit anomalies (warnings, never rejections) -----------------------------

def test_a_clear_outlier_is_flagged_as_a_warning():
    rows = _rows(*[(f"2026-06-0{i}", "Karama", "Milk", "10") for i in range(1, 8)])
    rows.append({"date": "2026-06-08", "store": "Karama", "item": "Milk", "units": "9999"})
    v, rep = _report(rows)

    assert rep["unit_anomalies_count"] == 1
    a = rep["unit_anomalies"][0]
    assert a["units"] == 9999 and a["row"] == 8
    assert abs(a["z"]) > 3.5
    # It is a WARNING: the row still validated and would still import.
    assert rep["scorecard"]["anomalies_are_warnings"] is True
    assert len(v["valid"]) == 8


def test_small_groups_are_never_flagged():
    """A store+item with 2 rows has no meaningful spread."""
    _, rep = _report(_rows(
        ("2026-06-01", "Karama", "Milk", "1"),
        ("2026-06-02", "Karama", "Milk", "5000"),
    ))
    assert rep["unit_anomalies_count"] == 0


def test_a_constant_series_has_no_anomalies():
    rows = _rows(*[(f"2026-06-0{i}", "Karama", "Milk", "10") for i in range(1, 8)])
    _, rep = _report(rows)
    assert rep["unit_anomalies_count"] == 0
    assert rep["scorecard"]["plausibility_pct"] == 100.0


def test_robust_stats_are_used_so_one_giant_outlier_cannot_mask_the_rest():
    """With mean/stdev a single huge value inflates the deviation and hides itself.
    Median/MAD does not."""
    rows = _rows(*[(f"2026-06-0{i}", "Karama", "Milk", "10") for i in range(1, 7)])
    rows.append({"date": "2026-06-07", "store": "Karama", "item": "Milk", "units": "1000000"})
    _, rep = _report(rows)
    assert rep["unit_anomalies_count"] == 1   # it IS caught


# --- scorecard ---------------------------------------------------------------

def test_completeness_counts_rows_that_validated():
    v, rep = _report([
        {"date": "2026-06-01", "store": "K", "item": "M", "units": "10"},
        {"date": "not-a-date", "store": "K", "item": "M", "units": "10"},
    ])
    assert v["summary"]["valid"] == 1
    assert rep["scorecard"]["completeness_pct"] == 50.0


def test_grade_bands():
    _, perfect = _report(_rows(("2026-06-01", "K", "M", "10")))
    assert perfect["scorecard"]["overall_pct"] == 100.0
    assert perfect["scorecard"]["grade"] == "A"


def test_non_sales_imports_still_get_a_completeness_score():
    v = validate_rows("items", ["name"], [{"name": "Milk"}, {"name": ""}], {"name": "name"})
    rep = build_quality_report("items", v["valid"], v["errors"], v["summary"]["total"])
    assert rep["scorecard"]["completeness_pct"] == 50.0
    assert rep["missing_days_count"] == 0     # not applicable, not invented


def test_empty_file_does_not_divide_by_zero():
    rep = build_quality_report("sales", [], [], 0)
    assert rep["scorecard"]["completeness_pct"] == 0.0
    assert rep["scorecard"]["grade"] == "F"


# --- downloadable unresolved rows -------------------------------------------

def test_rejected_rows_keep_the_operators_own_columns_and_the_reason():
    v = validate_rows("sales", _HEADERS, [
        {"date": "2026-06-01", "store": "K", "item": "M", "units": "10"},
        {"date": "bad", "store": "K", "item": "M", "units": "-5"},
    ], _SALES_MAP)

    assert len(v["rejected"]) == 1
    bad = v["rejected"][0]
    assert bad["date"] == "bad" and bad["_row"] == 2
    assert "date" in bad["_reason"] and "units" in bad["_reason"]

    out = rejected_rows_csv(_HEADERS, v["rejected"])
    lines = out.strip().splitlines()
    assert lines[0] == "date,store,item,units,_row,_reason"
    assert lines[1].startswith("bad,K,M,-5,2,")


def test_valid_rows_carry_a_source_row_number_but_never_leak_it_to_sql():
    v = validate_rows("sales", _HEADERS, _rows(("2026-06-01", "K", "M", "10")), _SALES_MAP)
    row = v["valid"][0]
    assert row["__row"] == 1
    from app.services.csv_import import _strip_markers
    assert set(_strip_markers(row)) == {"date", "store", "item", "units"}


# --- regression: dates bound to DATE columns ---------------------------------

def test_dates_are_bound_as_date_objects_not_iso_strings():
    """`_coerce` renders dates as ISO strings for the JSON API, but asyncpg binds a
    DATE parameter strictly and rejects a str ("'str' object has no attribute
    'toordinal'"). The sales and inventory CSV imports were silently broken for
    exactly this reason — every date reaching an INSERT goes through _as_date."""
    import datetime as dt

    from app.services.csv_import import _as_date

    assert _as_date("2026-06-01") == dt.date(2026, 6, 1)
    assert _as_date(dt.date(2026, 6, 1)) == dt.date(2026, 6, 1)
    assert _as_date(dt.datetime(2026, 6, 1, 14, 30)) == dt.date(2026, 6, 1)
    assert _as_date(None) is None
    assert _as_date("") is None


def test_every_date_reaching_an_insert_goes_through_the_converter():
    """A guard: a new date binding added without _as_date would 500 at runtime."""
    import inspect

    from app.services import csv_import

    src = inspect.getsource(csv_import.commit_import)
    # The three date-kind bindings in the persistence layer.
    assert '"d": _as_date(r["date"])' in src
    assert '"lsd": _as_date(r.get("last_sale_date"))' in src
    assert "vf = _as_date(r.get(\"cost_from\"))" in src
