"""
Unit tests for the Daily Executive Briefing assembler (blueprint E3-1).

Pure — exercises services/briefing.build_briefing()/build_briefing_html() without a
DB, the same way test_roi.py covers the ROI builder. Guards the narrative math
(week-over-week %, trend direction), the decision/leak assembly, the win precedence,
and the units-vs-AED discipline.
"""
from datetime import datetime, timezone

from app.services.briefing import build_briefing, build_briefing_html


def _base_raw(**over):
    raw = {
        "tenant_name": "Meridian Retail",
        "now": datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc),
        "wow": {"rev_wk": 120000, "rev_prev": 100000, "units_wk": 5200, "units_prev": 5000},
        "findings": [],
        "reorder": [],
        "roi": {"dead_stock_aed": 8000, "stockout_aed": 4000, "headline_aed": 12000, "total_skus": 50},
        "season": None,
        "forecast": {"status": "ready", "horizon_days": 14, "projected_revenue": 210000, "avg_daily_revenue": 15000},
        "improved_win": None,
    }
    raw.update(over)
    return raw


def test_headline_percent_and_trend_up():
    b = build_briefing(_base_raw())
    assert b["headline"]["revenue_aed"] == 120000
    assert b["headline"]["revenue_change_pct"] == 20.0   # (120k-100k)/100k
    assert b["headline"]["trend"] == "up"
    assert "up 20.0%" in b["headline"]["summary"]


def test_headline_trend_down_and_flat():
    down = build_briefing(_base_raw(wow={"rev_wk": 80000, "rev_prev": 100000, "units_wk": 4000, "units_prev": 5000}))
    assert down["headline"]["trend"] == "down"
    assert down["headline"]["revenue_change_pct"] == -20.0
    flat = build_briefing(_base_raw(wow={"rev_wk": 101000, "rev_prev": 100000, "units_wk": 5000, "units_prev": 5000}))
    assert flat["headline"]["trend"] == "flat"


def test_no_prior_week_is_not_a_crash():
    b = build_briefing(_base_raw(wow={"rev_wk": 5000, "rev_prev": 0, "units_wk": 100, "units_prev": 0}))
    assert b["headline"]["revenue_change_pct"] is None
    assert b["headline"]["trend"] == "flat"
    assert "no prior" not in b["headline"]["summary"].lower()  # phrased gracefully


def test_changes_capped_and_severity_sorted():
    findings = [
        {"title": "Low thing", "severity": "low", "detail": "d", "entity_name": "A", "detected_at": "2026-07-01"},
        {"title": "Critical thing", "severity": "critical", "detail": "d", "entity_name": "B", "detected_at": "2026-07-02"},
        {"title": "High thing", "severity": "high", "detail": "d", "entity_name": "C", "detected_at": "2026-07-02"},
        {"title": "Medium thing", "severity": "medium", "detail": "d", "entity_name": "D", "detected_at": "2026-07-02"},
    ]
    b = build_briefing(_base_raw(findings=findings))
    assert len(b["changes"]) == 3                      # capped at MAX_CHANGES
    assert b["changes"][0]["severity"] == "critical"   # highest severity first
    assert b["counts"]["open_findings"] == 4


def test_decisions_merge_findings_and_reorder():
    findings = [{"title": "Revenue down at Al Barsha", "severity": "high", "detail": "why",
                 "entity_name": "Al Barsha", "recommended_action": "Review pricing", "detected_at": "2026-07-02"}]
    reorder = [{"item_name": "Dates 1kg", "store_name": "Deira", "days_of_cover": 2.0,
                "recommended_order_qty": 300, "urgency": "critical"}]
    b = build_briefing(_base_raw(findings=findings, reorder=reorder))
    kinds = {d["kind"] for d in b["decisions"]}
    assert "finding" in kinds and "reorder" in kinds
    # critical reorder should outrank the high finding
    assert b["decisions"][0]["urgency"] == "critical"
    assert any("PO for ~300" in d["action"] for d in b["decisions"])


def test_leak_is_dead_plus_stockout_in_aed():
    b = build_briefing(_base_raw())
    assert b["leak"]["dead_stock_aed"] == 8000
    assert b["leak"]["stockout_loss_aed"] == 4000
    assert b["leak"]["total_aed"] == 12000
    # The note breaks the leak into its two derivable components (dead stock + stockout).
    assert "AED 8,000" in b["leak"]["note"] and "AED 4,000" in b["leak"]["note"]


def test_win_prefers_measure_loop_recovery_over_growth():
    raw = _base_raw(improved_win={"title": "Returns back to normal at Deira",
                                  "metric_before": 0.2, "metric_after": 0.05})
    b = build_briefing(raw)
    assert b["win"]["kind"] == "recovered"
    # Without an improved finding, a strong revenue week becomes the win.
    b2 = build_briefing(_base_raw(improved_win=None))
    assert b2["win"]["kind"] == "growth"
    # A flat/down week yields no manufactured win.
    b3 = build_briefing(_base_raw(improved_win=None,
                                  wow={"rev_wk": 100000, "rev_prev": 100000, "units_wk": 5000, "units_prev": 5000}))
    assert b3["win"] is None


def test_watch_uses_season_and_forecast():
    season = {"name": "Ramadan", "active": False, "days_until": 12, "note": "Grocery surge", "approx": True}
    b = build_briefing(_base_raw(season=season))
    assert b["watch"]["season"]["name"] == "Ramadan"
    assert "Ramadan starts in 12 days" in b["watch"]["summary"]
    assert b["watch"]["forecast"]["projected_revenue_aed"] == 210000


def test_empty_flag_when_nothing_to_show():
    raw = _base_raw(wow={"rev_wk": 0, "rev_prev": 0, "units_wk": 0, "units_prev": 0},
                    roi={"dead_stock_aed": 0, "stockout_aed": 0, "headline_aed": 0, "total_skus": 0})
    b = build_briefing(raw)
    assert b["empty"] is True


def test_printable_html_is_self_contained_and_mentions_key_facts():
    b = build_briefing(_base_raw(findings=[{"title": "Revenue down at Deira", "severity": "high",
                                            "detail": "off 12%", "entity_name": "Deira", "detected_at": "2026-07-02"}]))
    html = build_briefing_html(b, "2026-07-04 08:00 UTC")
    assert html.startswith("<!doctype html>")
    assert "Meridian Retail" in html
    assert "Revenue down at Deira" in html
    assert "AED" in html
