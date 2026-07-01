"""
Action drafting — autonomy level 1 (Phase: agentic increment). Pure mapper (no DB).

Guards the deterministic action_type → draft artifact mapping. The artifact must be
fully derivable (no LLM) and must never imply auto-execution. DB persistence + review
are covered by the integration suite.
"""
from app.services.action_drafting import build_draft, ACTION_TO_DRAFT, DRAFT_TYPES


def _finding(**kw):
    base = {"title": "Margin slipping in Beverages", "detail": "Down 12% w/w",
            "entity_type": "category", "entity_name": "Beverages",
            "recommended_action": "Review supplier terms", "action_type": "review_supplier"}
    base.update(kw)
    return base


def test_review_supplier_drafts_email():
    d = build_draft(_finding(action_type="review_supplier"))
    assert d["draft_type"] == "supplier_email"
    assert "subject" in d["payload"] and "body" in d["payload"]
    assert "Beverages" in d["payload"]["body"]


def test_review_pricing_drafts_markdown():
    d = build_draft(_finding(action_type="review_pricing"))
    assert d["draft_type"] == "markdown_proposal"
    assert isinstance(d["payload"]["proposed_steps"], list)


def test_promote_drafts_promotion():
    d = build_draft(_finding(action_type="promote"))
    assert d["draft_type"] == "promotion_proposal"
    assert "proposed_promo" in d["payload"]


def test_investigate_drafts_review_task():
    d = build_draft(_finding(action_type="investigate"))
    assert d["draft_type"] == "review_task"
    assert "task" in d["payload"]


def test_unknown_action_falls_back_to_review_task():
    d = build_draft(_finding(action_type="teleport"))
    assert d["draft_type"] == "review_task"


def test_every_mapped_draft_type_is_valid():
    for dt in ACTION_TO_DRAFT.values():
        assert dt in DRAFT_TYPES


def test_title_and_summary_present():
    d = build_draft(_finding())
    assert d["title"].startswith("Draft:")
    assert d["summary"]
    assert d["source_action_type"] == "review_supplier"


def test_missing_entity_name_is_handled():
    d = build_draft({"title": "Global anomaly", "action_type": "investigate",
                     "entity_type": "global", "entity_name": None})
    assert d["draft_type"] == "review_task"
    assert d["payload"]["entity"]  # never blank
