"""
Federated Sage tests. The merge/discrepancy/narration logic is pure (DB-free) and
runs everywhere; the cross-source execution path is exercised in
test_nl2sql_pipeline-style integration when a DB is reachable.
"""
import pytest

from app.services.federation.base import SourceResult, SourceDescriptor
from app.services.federation.orchestrator import detect_discrepancy, narrate_federated
from app.services.federation import policy
from app.services.federation.adapters.postgres import build_canonical_ctes


# --- role policy ------------------------------------------------------------
def test_consumer_cannot_merge_or_see_external():
    assert not policy.allow_cross_source_merge("consumer")
    assert not policy.allow_cross_source_merge("store_manager")
    assert policy.allow_cross_source_merge("regional_manager")
    assert policy.max_rows_for("consumer") < policy.max_rows_for("admin")
    ext = SourceDescriptor(id="ds:1", name="POS", engine="postgres", description="x", min_role="admin")
    assert not policy.can_use_source("consumer", ext)
    assert policy.can_use_source("admin", ext)


# --- discrepancy detection --------------------------------------------------
def test_discrepancy_flagged_when_sources_disagree():
    res = [
        SourceResult("internal", "Retail IQ", True, [{"revenue_aed": 100000}]),
        SourceResult("ds:1", "POS", True, [{"revenue_aed": 130000}]),
    ]
    msg = detect_discrepancy(res)
    assert msg and "disagree" in msg


def test_no_discrepancy_when_close():
    res = [
        SourceResult("internal", "Retail IQ", True, [{"x": 100000}]),
        SourceResult("ds:1", "POS", True, [{"x": 102000}]),  # 2% < 5% threshold
    ]
    assert detect_discrepancy(res) is None


# --- narration is rows-only + source-attributed -----------------------------
def test_narration_attributes_each_source():
    res = [
        SourceResult("internal", "Retail IQ", True, [{"units": 500}]),
        SourceResult("ds:1", "POS", True, [{"units": 480}]),
    ]
    out = narrate_federated(res)
    assert "Retail IQ" in out and "POS" in out


def test_narration_reports_failed_sources():
    res = [SourceResult("ds:1", "POS", False, error="timeout")]
    out = narrate_federated(res)
    assert "couldn't" in out.lower() or "POS" in out


# --- canonical CTE builder produces the sage_* relations --------------------
def test_canonical_ctes_define_all_relations():
    sql = build_canonical_ctes({
        "table": "sales", "date": "d", "store": "s", "item": "i", "quantity": "q",
    })
    for rel in ("sage_sales", "sage_daily_sales", "sage_store_performance",
                "sage_category_performance", "sage_item_performance", "sage_stores", "sage_items"):
        assert rel in sql


def test_canonical_ctes_reject_unsafe_identifiers():
    # _safe_identifier should refuse injection in mapping column names.
    with pytest.raises(Exception):
        build_canonical_ctes({"table": "sales; DROP TABLE x", "date": "d", "store": "s", "item": "i", "quantity": "q"})
