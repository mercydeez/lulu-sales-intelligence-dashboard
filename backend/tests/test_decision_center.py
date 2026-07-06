"""
Unit tests for the AI Decision Center builders (blueprint E3-2).

Pure — no DB, mirroring test_briefing.py / test_roi.py. Guards the honesty
contract: AED impact only where derivable from the finding's own evidence,
units for returns (no price on returns), explicit basis everywhere, deterministic
explainable confidence, and money-first sorting.
"""
from app.services.decision_center import (
    estimate_impact, confidence, expected_outcome, evidence_facts,
    build_decision, build_reorder_decision, sort_decisions, summarize,
    triage_decisions, route_owner, strategic_score, enrich_finding,
)


def _revenue_finding(**over):
    f = {
        "id": 1, "rule": "revenue_drop", "category": "sales", "severity": "critical",
        "title": "Revenue down 61.2% at Al Barsha",
        "detail": "Al Barsha made AED 10,253 vs AED 26,446 the week before.",
        "evidence": {"rev_recent": 10253.0, "rev_prior": 26446.0, "change": -0.612},
        "entity_type": "store", "entity_name": "Al Barsha", "metric_value": -0.612,
        "recommended_action": "Check Al Barsha for stockouts; consider a promotion.",
        "action_type": "promote", "action_accepted_at": None, "detected_at": "2026-07-03",
    }
    f.update(over)
    return f


def test_revenue_impact_is_the_weekly_aed_gap():
    imp = estimate_impact(_revenue_finding())
    assert imp["aed"] == round(26446.0 - 10253.0, 2)
    assert imp["per"] == "week"
    assert imp["units"] is None
    assert "prior-week" in imp["basis"]


def test_returns_impact_is_units_never_aed():
    f = _revenue_finding(rule="return_spike", metric_value=0.9,
                         evidence={"returns_recent_units": 380, "returns_prior_units": 200, "change": 0.9})
    imp = estimate_impact(f)
    assert imp["aed"] is None            # returns carry no sale price — never fabricate AED
    assert imp["units"] == 180
    assert "units" in imp["basis"]


def test_high_return_rate_excess_units():
    f = _revenue_finding(rule="high_return_rate", metric_value=0.15,
                         evidence={"return_rate": 0.15, "mean_rate": 0.05, "return_units": 300,
                                   "gross_units": 2000})
    imp = estimate_impact(f)
    assert imp["aed"] is None
    assert imp["units"] == 200           # (0.15 - 0.05) * 2000
    assert imp["per"] == "30d"


def test_laggard_has_no_fabricated_numbers():
    f = _revenue_finding(rule="laggard_store", metric_value=0.01,
                         evidence={"store_growth": 0.01, "chain_growth": 0.12, "gap_pp": 0.11})
    imp = estimate_impact(f)
    assert imp["aed"] is None and imp["units"] is None
    assert "isn't in this finding's evidence" in imp["basis"]


def test_confidence_is_deterministic_and_explained():
    c = confidence(_revenue_finding())
    # 61.2% drop vs a 15% threshold (>4x), full windows, rev_prior >> floor -> high
    assert c["level"] == "high"
    assert 0.75 <= c["score"] <= 0.95
    assert any("threshold" in f for f in c["factors"])
    assert any("windows" in f for f in c["factors"])


def test_confidence_lower_for_marginal_small_finding():
    weak = _revenue_finding(metric_value=-0.16,
                            evidence={"rev_recent": 420.0, "rev_prior": 500.0, "change": -0.16})
    c = confidence(weak)
    strong = confidence(_revenue_finding())
    assert c["score"] < strong["score"]
    assert c["level"] in ("low", "medium")


def test_expected_outcome_uses_derived_gap():
    f = _revenue_finding()
    out = expected_outcome(f, estimate_impact(f))
    assert "AED 16,193" in out
    assert "re-measures" in out


def test_evidence_facts_humanized():
    facts = evidence_facts(_revenue_finding())
    labels = {x["label"]: x["value"] for x in facts}
    assert labels["This week"] == "AED 10,253"
    assert labels["Prior week"] == "AED 26,446"
    assert labels["Change"] == "-61.2%"


def test_build_decision_pending_vs_decided():
    pending = build_decision(_revenue_finding())
    assert pending["state"] == "pending" and "decision" not in pending
    decided = build_decision(_revenue_finding(
        action_accepted_at="2026-07-03T10:00:00Z", action_accepted_by="a@b.c",
        outcome_status="improved", metric_before=-0.612, metric_after=None))
    assert decided["state"] == "decided"
    assert decided["decision"]["outcome_status"] == "improved"


def test_reorder_decision_units_only_and_procurement_href():
    d = build_reorder_decision({
        "item_name": "Dates 1kg", "store_name": "Deira", "days_of_cover": 2.0,
        "recommended_order_qty": 300, "urgency": "critical", "on_hand": 20,
        "forecast_daily_demand": 12.5, "forecast_demand_lead_time": 87.5,
        "lead_time_days": 7,
    })
    assert d["impact"]["aed"] is None and d["impact"]["units"] == 88
    assert d["severity"] == "critical"
    assert d["href"] == "/procurement"
    assert "PO for ~300" in d["recommended_action"]


def test_sort_money_first_then_severity():
    big = build_decision(_revenue_finding(id=1))
    small = build_decision(_revenue_finding(
        id=2, severity="medium",
        evidence={"rev_recent": 900.0, "rev_prior": 1000.0, "change": -0.1}))
    no_aed_critical = build_reorder_decision({
        "item_name": "X", "store_name": "Y", "days_of_cover": 1.0,
        "recommended_order_qty": 10, "urgency": "critical", "on_hand": 1,
        "forecast_daily_demand": 5, "forecast_demand_lead_time": 35, "lead_time_days": 7})
    ordered = sort_decisions([no_aed_critical, small, big])
    assert ordered[0]["id"] == 1          # biggest AED first
    assert ordered[1]["id"] == 2          # then smaller AED
    assert ordered[2]["kind"] == "reorder"  # AED-less last, even if critical


def test_summary_sums_only_derivable_aed():
    ds = [build_decision(_revenue_finding()), build_reorder_decision({
        "item_name": "X", "store_name": "Y", "days_of_cover": 1.0,
        "recommended_order_qty": 10, "urgency": "critical", "on_hand": 1,
        "forecast_daily_demand": 5, "forecast_demand_lead_time": 35, "lead_time_days": 7})]
    s = summarize(ds)
    assert s["pending"] == 2
    assert s["at_stake_aed_per_week"] == round(26446.0 - 10253.0, 2)


def test_string_evidence_is_parsed():
    f = _revenue_finding(evidence='{"rev_recent": 100.0, "rev_prior": 300.0, "change": -0.66}')
    assert estimate_impact(f)["aed"] == 200.0


# --- Triage / delegation (COO view) ---------------------------------------

def _category(name, prior, recent, fid):
    return build_decision({
        "id": fid, "rule": "category_slump", "category": "sales", "severity": "critical",
        "title": f"{name} revenue down", "detail": "d", "entity_type": "category",
        "entity_id": name, "entity_name": name, "metric_value": (recent - prior) / prior,
        "evidence": {"rev_recent": recent, "rev_prior": prior, "change": (recent - prior) / prior},
        "recommended_action": "Review pricing", "action_type": "review_pricing",
        "action_accepted_at": None, "detected_at": "2026-07-03",
    })


def _store(name, store_id, prior, recent, fid):
    return build_decision({
        "id": fid, "rule": "revenue_drop", "category": "sales", "severity": "high",
        "title": f"Revenue down at {name}", "detail": "d", "entity_type": "store",
        "entity_id": str(store_id), "entity_name": name, "metric_value": (recent - prior) / prior,
        "evidence": {"rev_recent": recent, "rev_prior": prior, "change": (recent - prior) / prior},
        "recommended_action": "Check store", "action_type": "promote",
        "action_accepted_at": None, "detected_at": "2026-07-03",
    })


def _reorder(item, store, qty):
    return build_reorder_decision({
        "item_name": item, "store_name": store, "days_of_cover": 2.0,
        "recommended_order_qty": qty, "urgency": "high", "on_hand": 10,
        "forecast_daily_demand": 8.0, "forecast_demand_lead_time": qty * 0.3, "lead_time_days": 7,
    })


def _mixed_deck():
    return [
        _category("Seafood", 147843, 16548, 1),      # huge chain-wide -> exec
        _category("Beverages", 183903, 74708, 2),    # big chain-wide  -> exec
        _category("Spices", 108687, 35245, 3),       # chain-wide      -> exec
        _category("Sweets", 116550, 90000, 4),       # smaller chain-wide -> exec.more
        _store("Meridian Deira", 7, 165812, 90000, 5),  # store -> regional
        _store("Meridian Al Barsha", 1, 100000, 70000, 6),  # store -> regional
        _reorder("Dates 1kg", "Meridian Deira", 60),     # small PO -> automate
        _reorder("Rice 5kg", "Meridian Al Barsha", 800),  # large PO -> store
        build_decision({                                   # high return rate -> automate
            "id": 9, "rule": "high_return_rate", "category": "returns", "severity": "high",
            "title": "High return rate in Electronics", "detail": "d", "entity_type": "category",
            "entity_id": "Electronics", "entity_name": "Electronics", "metric_value": 0.15,
            "evidence": {"return_rate": 0.15, "mean_rate": 0.05, "return_units": 300, "gross_units": 2000},
            "recommended_action": "Audit supplier", "action_type": "review_supplier",
            "action_accepted_at": None, "detected_at": "2026-07-03"}),
    ]


def test_triage_picks_exactly_three_for_the_executive():
    t = triage_decisions(_mixed_deck(), {"7": "Dubai", "1": "Dubai"})
    assert len(t["executive"]["decisions"]) == 3
    # The three biggest chain-wide slumps outrank a mid store drop of similar AED.
    titles = [d["problem"] for d in t["executive"]["decisions"]]
    assert "Seafood revenue down" in titles and "Beverages revenue down" in titles


def test_triage_routes_by_owner():
    t = triage_decisions(_mixed_deck(), {"7": "Dubai", "1": "Dubai"})
    lanes = {ln["key"]: ln for ln in t["lanes"]}
    reg_titles = [d["problem"] for d in lanes["regional"]["decisions"]]
    assert any("Meridian Deira" in x for x in reg_titles)         # store drop -> regional
    auto_actions = [d["action_type"] for d in lanes["automate"]["decisions"]]
    assert lanes["automate"]["count"] >= 2                        # small PO + return audit
    assert any(d["kind"] == "reorder" for d in lanes["automate"]["decisions"])
    assert any("Rice" in d["problem"] for d in lanes["store"]["decisions"])  # big PO -> store


def test_triage_extra_chainwide_go_to_executive_more_not_a_lane():
    t = triage_decisions(_mixed_deck(), {})
    assert t["executive"]["more"]["count"] >= 1                   # Sweets slump
    lane_keys = {ln["key"] for ln in t["lanes"]}
    assert "strategic" not in lane_keys                            # not a delegation lane


def test_triage_regional_grouped_by_region():
    t = triage_decisions(_mixed_deck(), {"7": "Dubai", "1": "Abu Dhabi"})
    reg = next(ln for ln in t["lanes"] if ln["key"] == "regional")
    names = {g["name"] for g in reg["groups"]}
    assert names == {"Dubai", "Abu Dhabi"}
    assert all("count" in g and "aed" in g for g in reg["groups"])


def test_triage_reduces_the_queue_and_totals_honest_aed():
    deck = _mixed_deck()
    t = triage_decisions(deck, {"7": "Dubai", "1": "Dubai"})
    assert t["total"] == len(deck)
    assert t["routed_count"] == len(deck) - 3          # everything but the 3
    # at_stake sums only derivable AED (reorders/returns contribute none)
    assert t["at_stake_aed_per_week"] > 0
    assert t["at_stake_aed_per_week"] == summarize(deck)["at_stake_aed_per_week"]


def test_route_owner_reorder_threshold():
    assert route_owner(_reorder("x", "y", 50)) == "automate"
    assert route_owner(_reorder("x", "y", 500)) == "store"


def test_strategic_score_weights_chainwide_above_store_of_equal_aed():
    cat = _category("C", 100000, 20000, 1)      # AED gap 80k, category (1.4x)
    store = _store("S", 3, 100000, 20000, 2)    # AED gap 80k, store (1.0x)
    assert strategic_score(cat) > strategic_score(store)


# ---------------------------------------------------------------------------
# enrich_finding — the findings API attaches the SAME derivations the Decision
# Center uses, so Insights and /decisions can never disagree on a number.
# ---------------------------------------------------------------------------
def test_enrich_finding_attaches_decision_derivations():
    f = enrich_finding(_revenue_finding())
    assert f["impact"] == estimate_impact(_revenue_finding())
    assert f["confidence"] == confidence(_revenue_finding())
    assert f["expected_outcome"] == expected_outcome(_revenue_finding(), f["impact"])
    assert f["evidence_facts"] == evidence_facts(_revenue_finding())
    # raw fields survive untouched (the Finding contract is additive)
    assert f["title"] == "Revenue down 61.2% at Al Barsha"
    assert f["evidence"]["rev_prior"] == 26446.0


def test_enrich_finding_matches_build_decision_exactly():
    """The two consumer paths (findings API vs decisions API) must agree."""
    f = enrich_finding(_revenue_finding())
    d = build_decision(_revenue_finding())
    assert f["impact"] == d["impact"]
    assert f["confidence"] == d["confidence"]
    assert f["expected_outcome"] == d["expected_outcome"]
    assert f["evidence_facts"] == d["evidence"]


def test_enrich_finding_handles_json_string_evidence():
    """DB rows may deliver evidence as a JSON string — same result either way."""
    import json as _json
    raw = _revenue_finding()
    stringy = _revenue_finding(evidence=_json.dumps(raw["evidence"]))
    assert enrich_finding(stringy)["impact"] == enrich_finding(raw)["impact"]
