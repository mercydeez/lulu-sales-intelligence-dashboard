"""
CSV import — parse / map / validate core (no DB).

The sacred rule is units-vs-AED: a unit count must never validate as money and an
AED field must reject non-numeric junk. These guard the pure core that both preview
and commit rely on. Persistence + name→id resolution are integration-tested.
"""
from app.services.csv_import import (
    parse_csv, validate_rows, schema_for, import_types, sample_csv,
)


def test_every_type_has_a_parseable_sample():
    # The pilot-in-a-box samples must parse and have the required fields available.
    for t in import_types():
        csv = sample_csv(t)
        assert csv, t
        headers, rows = parse_csv(csv)
        assert headers and len(rows) >= 1, t


def test_parse_csv_headers_and_rows():
    headers, rows = parse_csv("name,location\nMall Store,Dubai\nCity Store,Sharjah\n")
    assert headers == ["name", "location"]
    assert len(rows) == 2
    assert rows[0] == {"name": "Mall Store", "location": "Dubai"}


def test_parse_csv_strips_bom_and_blank_lines():
    headers, rows = parse_csv("﻿name,location\nA,Dubai\n\n\n")
    assert headers == ["name", "location"]
    assert len(rows) == 1


def test_all_import_types_have_schema():
    for t in import_types():
        s = schema_for(t)
        assert s and s["fields"] and s["target"]


def test_items_valid_rows_pass():
    csv = "Product,Cat,Price\nMilk 1L,Dairy,6.50\nBread,Bakery,3\n"
    headers, rows = parse_csv(csv)
    res = validate_rows("items", headers, rows,
                        {"name": "Product", "category": "Cat", "unit_price_aed": "Price"})
    assert res["summary"]["valid"] == 2
    assert res["valid"][0]["unit_price_aed"] == 6.50


def test_aed_rejects_non_numeric():
    headers, rows = parse_csv("Product,Price\nMilk,abc\n")
    res = validate_rows("items", headers, rows, {"name": "Product", "unit_price_aed": "Price"})
    assert res["summary"]["valid"] == 0
    assert any("AED" in e["message"] for e in res["errors"])


def test_aed_rejects_negative():
    headers, rows = parse_csv("Product,Price\nMilk,-5\n")
    res = validate_rows("items", headers, rows, {"name": "Product", "unit_price_aed": "Price"})
    assert res["summary"]["valid"] == 0


def test_units_must_be_whole_number():
    headers, rows = parse_csv("d,s,i,u\n2026-06-01,Store A,Milk,12\n2026-06-01,Store A,Milk,oops\n")
    res = validate_rows("sales", headers, rows,
                        {"date": "d", "store": "s", "item": "i", "units": "u"})
    assert res["summary"]["valid"] == 1
    assert res["valid"][0]["units"] == 12


def test_missing_required_mapping_is_flagged():
    headers, rows = parse_csv("Product\nMilk\n")
    res = validate_rows("sales", headers, rows, {"item": "Product"})  # date/store/units unmapped
    assert res["summary"]["valid"] == 0
    assert any("not mapped" in e["message"] for e in res["errors"])


def test_date_formats_normalised_to_iso():
    headers, rows = parse_csv("d,s,i,u\n01/06/2026,A,Milk,3\n")
    res = validate_rows("sales", headers, rows,
                        {"date": "d", "store": "s", "item": "i", "units": "u"})
    assert res["valid"][0]["date"] == "2026-06-01"


def test_optional_empty_field_becomes_null():
    headers, rows = parse_csv("Product,Cat\nMilk,\n")
    res = validate_rows("items", headers, rows, {"name": "Product", "category": "Cat"})
    assert res["valid"][0]["category"] is None


def test_inventory_units_and_cost_typing():
    csv = "store,item,stock,cost\nStore A,Milk,40,4.25\n"
    headers, rows = parse_csv(csv)
    res = validate_rows("inventory", headers, rows,
                        {"store": "store", "item": "item",
                         "current_stock": "stock", "unit_cost": "cost"})
    assert res["valid"][0]["current_stock"] == 40
    assert res["valid"][0]["unit_cost"] == 4.25
