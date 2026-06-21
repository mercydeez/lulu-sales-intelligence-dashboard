"""
Tests for the proactive risk-scan module (DB-free surface).

The detectors themselves read the live database and are verified end-to-end in
Docker; here we lock down the stable contract: the scan type set, the severity
ranking weights, and the dedupe-key scheme the upsert/resolve logic depends on.
"""
from app.services.intelligence import risk_scans as rs
from app.services.alert_service import make_dedupe_key


def test_scan_types_are_the_expected_four():
    assert rs.SCAN_TYPES == ["stockout_risk", "demand_drop", "return_spike", "dead_stock"]


def test_severity_weights_rank_high_above_medium_above_low():
    base = rs._SEV_BASE
    assert base["high"] > base["medium"] > base["low"]
    assert all(v > 0 for v in base.values())


def test_dedupe_key_is_stable_and_distinguishes_entities():
    # Same (type, store, item) -> same key (so a re-scan updates, not duplicates).
    k1 = make_dedupe_key("stockout_risk", 3, 17)
    k2 = make_dedupe_key("stockout_risk", 3, 17)
    assert k1 == k2
    # Different store or item -> different key.
    assert make_dedupe_key("stockout_risk", 3, 17) != make_dedupe_key("stockout_risk", 4, 17)
    assert make_dedupe_key("demand_drop", 3, None) != make_dedupe_key("return_spike", 3, None)


def test_detectors_registered():
    # All four detectors are wired into the scan tuple.
    names = {d.__name__ for d in rs._DETECTORS}
    assert names == {"_detect_stockout", "_detect_demand_drop", "_detect_return_spike", "_detect_dead_stock"}
