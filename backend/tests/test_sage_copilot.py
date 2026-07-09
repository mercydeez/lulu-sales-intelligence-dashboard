"""
Unit tests for the Sage Copilot feed (SAGE_COPILOT_ARCHITECTURE §3.3, Phase 2).

Two halves, mirroring the repo's established styles:
  - pure `build_feed` tests (no DB, like test_briefing.py / test_decision_center.py):
    guard the honesty contract — no re-derivation (briefing passes through
    untouched), risks/alerts/actions are reshapings of decision_center's own
    scored decisions, opportunities carry the measured-vs-estimate confidence
    distinction, and empty is an honest state (metadata.confidence is None).
  - route contract tests (like test_ai_rbac.py): the route hands the caller's
    RBAC scope down to generate_feed, without a live DB.
"""
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.services.sage_copilot import (
    build_feed, compose_business_health, _to_recommended_action, _dedupe_by_id,
    MAX_RISKS, MAX_OPPORTUNITIES, MAX_RECOMMENDED_ACTIONS, MAX_ALERTS,
    _GROUNDED_MEASURED_CONFIDENCE, _GROUNDED_ESTIMATE_CONFIDENCE,
)

_NOW = datetime(2026, 7, 8, 7, 0, tzinfo=timezone.utc)

STABLE_KEYS = {
    "version", "generated_at", "fresh_until", "briefing", "business_health",
    "decisions", "risks", "opportunities", "forecast", "roi",
    "recommended_actions", "alerts", "metadata",
}


def _decision(i, sev="high", aed=1000.0, **over):
    """A finding-derived decision shaped like decision_center.build_decision."""
    d = {
        "id": i, "kind": "finding", "rule": "revenue_drop", "severity": sev,
        "state": "pending", "problem": f"Revenue down at Store {i}",
        "detail": "…", "entity_type": "store", "entity_id": str(i),
        "entity_name": f"Store {i}", "category": "sales",
        "impact": {"aed": aed, "units": None, "per": "week", "basis": "prior-week gap"},
        "confidence": {"score": 0.8, "level": "high", "factors": ["threshold", "windows"]},
        "evidence": [{"label": "This week", "value": "AED 10,253"}],
        "recommended_action": f"Investigate Store {i}.",
        "action_type": "promote", "expected_outcome": "…",
        "detected_at": "2026-07-03", "href": "/insights",
    }
    d.update(over)
    return d


def _reorder(i=None, sev="critical", qty=300, **over):
    """A forecast-driven reorder decision shaped like build_reorder_decision."""
    d = {
        "id": i, "kind": "reorder", "rule": "stockout_risk", "reorder_qty": qty,
        "severity": sev, "state": "pending",
        "problem": "Dates 1kg will run out at Deira", "detail": "…",
        "entity_type": "store", "entity_id": "9", "entity_name": "Deira",
        "category": "inventory",
        "impact": {"aed": None, "units": 88, "per": "lead time", "basis": "forecast demand"},
        "confidence": {"score": 0.6, "level": "medium", "factors": ["Forecast-driven"]},
        "evidence": [{"label": "On hand", "value": "20 units"}],
        "recommended_action": "Raise a PO for ~300 units of Dates 1kg at Deira.",
        "action_type": "reorder", "expected_outcome": "…",
        "detected_at": None, "href": "/procurement",
    }
    d.update(over)
    return d


def _base_raw(**over):
    raw = {
        "now": _NOW,
        "briefing": {
            "headline": {"trend": "down", "revenue_change_pct": -12.4},
            "win": None,
        },
        "pending_decisions": [],
        "region_map": {"1": "Dubai"},
        "scope": "chain",
        "roi": {"metrics": {}, "context": {}},
        "forecast": {"status": "insufficient_history"},
        "forecast_text": "Not enough evidence to project a forecast yet.",
    }
    raw.update(over)
    return raw


# --- shape & passthrough ---------------------------------------------------

def test_stable_keys_always_present_even_when_empty():
    feed = build_feed(_base_raw())
    assert set(feed.keys()) == STABLE_KEYS
    assert feed["version"] == 2
    # list sections are honestly empty, never missing
    for k in ("decisions", "risks", "opportunities", "recommended_actions", "alerts"):
        assert feed[k] == []
    # dict sections are present with an honest degraded status
    assert feed["forecast"]["status"] == "insufficient_history"
    assert "not enough" in feed["forecast"]["narrative"].lower()


def test_briefing_passes_through_identically():
    """The feed never re-derives the briefing — /api/briefing and the copilot
    can never disagree about what happened this week."""
    raw = _base_raw()
    feed = build_feed(raw)
    assert feed["briefing"] is raw["briefing"]


# --- decisions / risks / alerts (reshapings of the decision pool) ----------

def test_decisions_are_the_top3_by_strategic_score():
    pending = [_decision(i, aed=aed) for i, aed in
               enumerate([100.0, 9000.0, 50.0, 7000.0, 8000.0], start=1)]
    feed = build_feed(_base_raw(pending_decisions=pending))
    assert [d["id"] for d in feed["decisions"]] == [2, 5, 4]   # AED desc


def test_risks_are_critical_high_findings_not_already_top_decisions():
    top = [_decision(i, aed=50000.0 + i) for i in (1, 2, 3)]
    lesser = [_decision(i, sev="critical", aed=100.0) for i in range(4, 12)]
    medium = [_decision(20, sev="medium", aed=90.0)]
    reorder = [_reorder(sev="critical")]
    feed = build_feed(_base_raw(pending_decisions=top + lesser + medium + reorder))
    top_ids = {d["id"] for d in feed["decisions"]}
    risk_ids = {d["id"] for d in feed["risks"]}
    assert len(feed["risks"]) == MAX_RISKS
    assert not (risk_ids & top_ids)                      # exclusion
    assert all(d["kind"] == "finding" for d in feed["risks"])
    assert all(d["severity"] in ("critical", "high") for d in feed["risks"])
    assert 20 not in risk_ids                            # medium excluded


def test_alerts_are_critical_reorders_only():
    pending = ([_reorder(sev="critical") for _ in range(MAX_ALERTS + 2)]
               + [_reorder(sev="high")] + [_decision(1, sev="critical")])
    feed = build_feed(_base_raw(pending_decisions=pending))
    assert len(feed["alerts"]) == MAX_ALERTS
    assert all(d["kind"] == "reorder" and d["severity"] == "critical"
               for d in feed["alerts"])


# --- recommended actions (pure reshaping, no new analysis) ------------------

def test_recommended_action_reshaping_copies_the_decision():
    d = _decision(7, sev="critical")
    a = _to_recommended_action(d)
    assert a["title"] == d["recommended_action"]
    assert a["reason"] == d["problem"]
    assert a["evidence"] is d["evidence"]
    assert a["priority"] == "urgent"                     # critical -> urgent
    assert a["confidence"] == 0.8
    assert a["deep_link"] == "/insights"


def test_recommended_action_deep_link_falls_back_to_decisions():
    a = _to_recommended_action(_decision(1, href=None))
    assert a["deep_link"] == "/decisions"


def test_decision_without_recommended_action_is_dropped():
    assert _to_recommended_action(_decision(1, recommended_action=None)) is None
    pending = [_decision(1, recommended_action=None), _decision(2)]
    feed = build_feed(_base_raw(pending_decisions=pending))
    assert [a["title"] for a in feed["recommended_actions"]] == ["Investigate Store 2."]


def test_dedupe_by_id():
    a, b = _decision(1), _decision(1)
    c = _decision(2)
    assert _dedupe_by_id([a, b, c]) == [a, c]
    # id-less decisions (reorders) are kept individually, never collapsed
    r1, r2 = _reorder(), _reorder()
    assert _dedupe_by_id([r1, r2]) == [r1, r2]


def test_recommended_actions_capped():
    pending = [_decision(i) for i in range(1, 12)]
    feed = build_feed(_base_raw(pending_decisions=pending))
    assert len(feed["recommended_actions"]) <= MAX_RECOMMENDED_ACTIONS


# --- opportunities (grounded positives only) --------------------------------

def test_growth_win_becomes_a_measured_opportunity():
    briefing = {"headline": {"trend": "up", "revenue_change_pct": 8.0},
                "win": {"kind": "growth", "title": "Revenue up 8%", "detail": "WoW growth."}}
    feed = build_feed(_base_raw(briefing=briefing))
    assert len(feed["opportunities"]) == 1
    opp = feed["opportunities"][0]
    assert opp["title"] == "Revenue up 8%"
    assert opp["confidence"] == _GROUNDED_MEASURED_CONFIDENCE["score"]
    assert opp["deep_link"] == "/analytics"


def test_recovered_win_links_to_insights():
    briefing = {"headline": {"trend": "flat", "revenue_change_pct": 0.0},
                "win": {"kind": "recovered", "title": "Al Barsha recovered", "detail": "…"}}
    feed = build_feed(_base_raw(briefing=briefing))
    assert feed["opportunities"][0]["deep_link"] == "/insights"


def test_roi_opportunities_distinguish_measured_from_estimate():
    """Dead stock is a live inventory FACT (0.85); stockout loss is a projection
    (0.55) — the same is_estimate honesty roi.py already flags."""
    roi = {"metrics": {"dead_stock": {"aed": 5000.0, "count": 3},
                       "stockout_loss_estimate": {"aed": 1200.0, "projection_days": 30}},
           "context": {"below_reorder_count": 0, "total_skus": 100}}
    feed = build_feed(_base_raw(roi=roi))
    by_conf = {o["confidence"] for o in feed["opportunities"]}
    assert by_conf == {_GROUNDED_MEASURED_CONFIDENCE["score"],
                       _GROUNDED_ESTIMATE_CONFIDENCE["score"]}
    assert all(o["deep_link"] == "/value" for o in feed["opportunities"])


def test_opportunities_capped():
    briefing = {"headline": {"trend": "up", "revenue_change_pct": 8.0},
                "win": {"kind": "growth", "title": "t", "detail": "d"}}
    roi = {"metrics": {"dead_stock": {"aed": 5000.0, "count": 3},
                       "stockout_loss_estimate": {"aed": 1200.0}},
           "context": {}}
    feed = build_feed(_base_raw(briefing=briefing, roi=roi))
    assert len(feed["opportunities"]) == MAX_OPPORTUNITIES


# --- business health (aggregation, factors explain the score) ---------------

def test_health_trend_up_no_risks_is_strong():
    h = compose_business_health({"revenue_trend": "up", "revenue_change_pct": 8.0,
                                 "critical_risk_count": 0, "forecast_status": "ready"})
    assert h["overall"] == "strong" and h["score"] == 0.75
    assert any("trending up" in f for f in h["factors"])
    assert any("No critical" in f for f in h["factors"])


def test_health_trend_down_with_risks_degrades():
    h = compose_business_health({"revenue_trend": "down", "revenue_change_pct": -20.0,
                                 "critical_risk_count": 5,
                                 "forecast_status": "insufficient_history"})
    # 0.6 - 0.2 (down) - 0.25 (risk cap) = 0.15 -> critical band
    assert h["overall"] == "critical" and h["score"] == 0.15
    assert any("5 critical" in f for f in h["factors"])
    assert any("not enough sales history" in f for f in h["factors"])


def test_health_inventory_pressure_factor():
    h = compose_business_health({"revenue_trend": "flat", "below_reorder_count": 20,
                                 "total_skus": 100, "forecast_status": "ready"})
    assert h["score"] == 0.5                          # 0.6 - 0.1 pressure
    assert any("20 of 100 SKUs" in f for f in h["factors"])
    assert h["components"]["inventory_pressure"] == {"below_reorder_count": 20,
                                                     "total_skus": 100}


def test_health_degraded_input_does_not_crash():
    h = compose_business_health({})
    assert h["overall"] in ("strong", "steady", "attention", "critical")
    assert h["factors"]


# --- metadata (honest aggregate) --------------------------------------------

def test_empty_feed_has_no_invented_confidence():
    feed = build_feed(_base_raw())
    assert feed["metadata"]["confidence"] is None
    assert feed["metadata"]["more_strategic_count"] == 0


def test_metadata_confidence_is_the_mean_of_present_scores():
    pending = [_decision(i) for i in (1, 2)]          # all confidences 0.8
    feed = build_feed(_base_raw(pending_decisions=pending))
    assert feed["metadata"]["confidence"] == 0.8
    assert "decisions" in feed["metadata"]["sections_included"]
    assert "briefing" in feed["metadata"]["sections_included"]


# =============================================================================
# Route contract (test_ai_rbac.py style): the route hands the caller's RBAC
# scope down to generate_feed. No live DB — generate_feed is patched.
# =============================================================================
from app.main import app
from app.routes.auth import get_current_user
from tests.test_ai_rbac import (
    MOCK_SUPER_ADMIN, MOCK_REGIONAL_MANAGER, MOCK_STORE_MANAGER,
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


async def _get_feed_as(user):
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.routes.copilot.generate_feed", new_callable=AsyncMock) as mock_feed:
        mock_feed.return_value = {"version": 2}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/ai/copilot/feed")
        return resp, mock_feed


def _scope_args(mock_feed):
    """generate_feed(db, tenant_id, role, allowed, scope=...)."""
    args = mock_feed.call_args.args
    return args[1], args[2], args[3], mock_feed.call_args.kwargs.get("scope")


@pytest.mark.asyncio
async def test_store_manager_feed_is_store_scoped():
    resp, mock_feed = await _get_feed_as(MOCK_STORE_MANAGER)
    assert resp.status_code == 200
    tenant_id, role, allowed, scope = _scope_args(mock_feed)
    assert (tenant_id, role, allowed, scope) == (1, "store_manager", [1], "store")


@pytest.mark.asyncio
async def test_regional_manager_feed_is_region_scoped():
    resp, mock_feed = await _get_feed_as(MOCK_REGIONAL_MANAGER)
    assert resp.status_code == 200
    tenant_id, role, allowed, scope = _scope_args(mock_feed)
    assert (tenant_id, role, allowed, scope) == (1, "regional_manager", [1, 2, 3], "region")


@pytest.mark.asyncio
async def test_super_admin_feed_is_chain_scoped():
    resp, mock_feed = await _get_feed_as(MOCK_SUPER_ADMIN)
    assert resp.status_code == 200
    tenant_id, role, allowed, scope = _scope_args(mock_feed)
    assert (tenant_id, role, scope) == (1, "super_admin", "chain")
    assert allowed == []                              # empty = all stores in tenant


@pytest.mark.asyncio
async def test_unauthenticated_feed_is_refused():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/ai/copilot/feed")
    assert resp.status_code == 401
