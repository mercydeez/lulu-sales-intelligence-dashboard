"""E1-3 — Excel (.xlsx/.xls) import.

The whole design rests on one invariant: a workbook parses into the SAME
(headers, rows) contract as the equivalent CSV, so validate_rows/commit_import
never learn there was a spreadsheet. Everything here defends that invariant, plus
the Excel-specific traps (typed cells, float noise, blank rows, duplicate headers,
row limits, and trusting the client's declared file type).

Pure: workbooks are built in memory. No DB, no network.
"""
import datetime
import io

import pytest
from openpyxl import Workbook

from app.services.csv_import import (
    MAX_ROWS,
    normalize_headers,
    parse_csv,
    parse_workbook,
    sample_csv,
    sample_xlsx,
    sniff_workbook_kind,
    validate_rows,
)


def _xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- the invariant ----------------------------------------------------------

def test_xlsx_parses_identically_to_the_equivalent_csv():
    """Excel hands back datetime/float; CSV hands back strings. Downstream code
    must not be able to tell them apart."""
    csv_text = "date,store,item,units\n2026-01-05,Al Barsha,Milk 1L,42\n"
    data = _xlsx([
        ["date", "store", "item", "units"],
        [datetime.datetime(2026, 1, 5), "Al Barsha", "Milk 1L", 42.0],  # typed cells
    ])

    assert parse_csv(csv_text) == parse_workbook(data)


def test_parsed_workbook_flows_through_the_untouched_validator():
    data = _xlsx([
        ["date", "store", "item", "units"],
        [datetime.date(2026, 1, 5), "Al Barsha", "Milk 1L", 42],
    ])
    headers, rows = parse_workbook(data)
    result = validate_rows("sales", headers, rows,
                           {"date": "date", "store": "store", "item": "item", "units": "units"})
    assert result["summary"]["valid"] == 1
    assert result["errors"] == []


# --- Excel-specific coercion traps ------------------------------------------

def test_typed_cells_are_stringified_the_way_the_validator_expects():
    data = _xlsx([
        ["price", "qty", "note", "when"],
        [6.5000000000000002, 3.0, None, datetime.datetime(2026, 3, 1, 14, 30)],
    ])
    _, rows = parse_workbook(data)
    r = rows[0]
    assert r["price"] == "6.5"      # binary float noise killed
    assert r["qty"] == "3"          # 3.0 is a count, not "3.0"
    assert r["note"] == ""          # empty cell, not "None"
    assert r["when"] == "2026-03-01"  # date only — _coerce accepts no time part


def test_trailing_blank_rows_and_columns_are_dropped():
    """Excel exports trail hundreds of empty rows and unnamed columns."""
    data = _xlsx([
        ["name", "category", None, None],
        ["Milk 1L", "Dairy", None, None],
        [None, None, None, None],
        [None, None, None, None],
    ])
    headers, rows = parse_workbook(data)
    assert headers == ["name", "category"]
    assert rows == [{"name": "Milk 1L", "category": "Dairy"}]


def test_duplicate_headers_are_suffixed_not_silently_collapsed():
    """The row dict is keyed by header — two `name` columns would lose one of the
    customer's columns entirely."""
    assert normalize_headers(["name", "name", "name"]) == ["name", "name_2", "name_3"]


def test_invisible_characters_in_headers_are_normalised():
    assert normalize_headers(["﻿ Units  Sold ", "\xa0Price"]) == ["Units Sold", "Price"]


def test_header_normalisation_is_shared_by_both_parsers():
    csv_headers, _ = parse_csv("﻿ Units  Sold ,Price\n1,2\n")
    xlsx_headers, _ = parse_workbook(_xlsx([["﻿ Units  Sold ", "Price"], [1, 2]]))
    assert csv_headers == xlsx_headers == ["Units Sold", "Price"]


# --- format sniffing: never trust the client --------------------------------

def test_format_is_sniffed_from_magic_bytes():
    assert sniff_workbook_kind(_xlsx([["a"]])) == "xlsx"
    assert sniff_workbook_kind(b"\xd0\xcf\x11\xe0junk") == "xls"
    assert sniff_workbook_kind(b"date,store\n1,2\n") is None   # a CSV renamed .xlsx


def test_a_csv_renamed_to_xlsx_fails_loudly_not_as_mojibake():
    with pytest.raises(ValueError, match="not a recognised|Not a recognised"):
        parse_workbook(b"date,store,item,units\n2026-01-05,A,B,1\n")


# --- guards -----------------------------------------------------------------

def test_row_limit_is_enforced_while_streaming():
    """A crafted workbook can claim millions of rows; we must not materialise them."""
    rows = [["units"]] + [[1]] * (MAX_ROWS + 5)
    with pytest.raises(ValueError, match="row limit|exceeds"):
        parse_workbook(_xlsx(rows))


def test_sample_preview_short_circuits_before_the_row_limit():
    rows = [["units"]] + [[1]] * 50
    headers, out = parse_workbook(_xlsx(rows), sample=5)
    assert headers == ["units"]
    assert len(out) == 5


# --- samples can't drift ----------------------------------------------------

@pytest.mark.parametrize("import_type", ["items", "sales", "inventory", "stores", "suppliers"])
def test_xlsx_sample_round_trips_to_the_csv_sample(import_type):
    """The Excel sample is generated from the CSV sample, so parsing it back must
    reproduce exactly the CSV sample's headers and rows."""
    blob = sample_xlsx(import_type)
    assert blob and sniff_workbook_kind(blob) == "xlsx"
    assert parse_workbook(blob) == parse_csv(sample_csv(import_type))


def test_no_sample_for_unknown_type():
    assert sample_xlsx("nope") is None
