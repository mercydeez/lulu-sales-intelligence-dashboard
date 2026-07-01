"""
ROI calculator — pure assembly logic (no DB).

Guards the honesty rules: cost-dependent metrics (cash-at-cost, GMROI) are null with
a `needs` flag when there's no cost data — never fabricated. Stockout loss is an
explicit projection. The headline is dead-stock + projected stockout loss.
"""
from app.services.roi import (
    build_summary, build_report_html, build_report_csv, STOCKOUT_PROJECTION_DAYS,
)

_RAW = {
    "inventory_retail_value": 100000, "inventory_cost_value": 60000, "has_cost": True,
    "dead_stock_value": 12000, "dead_stock_count": 8,
    "stockout_daily_loss_aed": 500, "below_reorder_count": 14,
    "avg_days_of_supply": 23.4, "total_skus": 50, "total_stock_units": 9000,
    "revenue_90d": 240000, "cogs_90d": 150000,
}


def test_headline_is_deadstock_plus_projected_stockout():
    s = build_summary(_RAW)
    expected = 12000 + 500 * STOCKOUT_PROJECTION_DAYS
    assert s["headline"]["aed"] == expected


def test_stockout_loss_is_projected_and_flagged_estimate():
    s = build_summary(_RAW, projection_days=30)
    m = s["metrics"]["stockout_loss_estimate"]
    assert m["aed"] == 15000  # 500 * 30
    assert m["per_day_aed"] == 500
    assert m["is_estimate"] is True


def test_gmroi_computed_when_cost_present():
    s = build_summary(_RAW)
    # gross margin = 240000 - 150000 = 90000; GMROI = 90000 / 60000 = 1.5
    assert s["metrics"]["gmroi"]["value"] == 1.5
    assert s["metrics"]["gmroi"]["gross_margin_90d_aed"] == 90000


def test_cost_metrics_null_with_needs_flag_when_no_cost():
    raw = {**_RAW, "has_cost": False, "inventory_cost_value": 0, "cogs_90d": 0}
    s = build_summary(raw)
    assert s["metrics"]["cash_tied_at_cost"]["aed"] is None
    assert "cost" in s["metrics"]["cash_tied_at_cost"]["needs"]
    assert s["metrics"]["gmroi"]["value"] is None
    assert s["metrics"]["gmroi"]["needs"]


def test_retail_value_always_present():
    raw = {**_RAW, "has_cost": False, "inventory_cost_value": 0}
    s = build_summary(raw)
    assert s["metrics"]["inventory_value_retail"]["aed"] == 100000


def test_currency_is_aed():
    assert build_summary(_RAW)["currency"] == "AED"


def test_empty_tenant_is_all_zero_not_error():
    s = build_summary({})
    assert s["headline"]["aed"] == 0
    assert s["metrics"]["inventory_value_retail"]["aed"] == 0
    assert s["context"]["total_skus"] == 0


def test_html_report_has_company_headline_and_methodology():
    html = build_report_html(build_summary(_RAW), "Meridian Retail LLC", "2026-06-30")
    assert "Meridian Retail LLC" in html
    assert "AED" in html and "<table" in html
    assert "How it is derived" in html  # methodology column present


def test_html_report_warns_when_no_cost():
    raw = {**_RAW, "has_cost": False, "inventory_cost_value": 0, "cogs_90d": 0}
    html = build_report_html(build_summary(raw), "Acme", "2026-06-30")
    assert "never estimate cost" in html
    assert "needs cost data" in html  # cost metrics shown honestly, not fabricated


def test_csv_report_has_headline_and_rows():
    csv = build_report_csv(build_summary(_RAW))
    assert "Metric,Value,How it is derived" in csv
    assert "headline" in csv.lower()
    assert "GMROI" in csv or "gmroi" in csv.lower()
