"""
Alert Service Tests (Phase 2.2/2.3) — type mapping, dedup keys, expiry
severity, and access checks. DB-backed flows are covered by the live stack;
these tests cover the pure logic.
"""
from app.services.alert_service import (
    EXPIRY_CRITICAL_DAYS,
    AlertService,
    category_for,
    db_alert_type,
    expiry_severity,
    make_dedupe_key,
)


class TestAlertTypeMapping:

    def test_out_of_stock_maps_to_stockout(self):
        assert db_alert_type({"alert_type": "inventory", "title": "Out of Stock: Rice"}) == "stockout"

    def test_low_stock_maps_to_low_stock(self):
        assert db_alert_type({"alert_type": "inventory", "title": "Low Stock: Rice"}) == "low_stock"

    def test_sales_maps_to_anomaly(self):
        assert db_alert_type({"alert_type": "sales", "title": "High Sales Alert"}) == "sales_anomaly"

    def test_expiry_maps_to_expiry_risk(self):
        assert db_alert_type({"alert_type": "expiry", "title": "Expiry Risk: Milk"}) == "expiry_risk"

    def test_unknown_maps_to_system_health(self):
        assert db_alert_type({"alert_type": "weird", "title": "x"}) == "system_health"


class TestCategoryMapping:
    """The frontend filters on coarse categories; every db type must map."""

    def test_inventory_types(self):
        for t in ("low_stock", "stockout", "overstock", "dead_stock"):
            assert category_for(t) == "inventory"

    def test_sales_types(self):
        for t in ("sales_anomaly", "returns_anomaly", "forecast_deviation"):
            assert category_for(t) == "sales"

    def test_expiry(self):
        assert category_for("expiry_risk") == "expiry"

    def test_system(self):
        assert category_for("system_health") == "system"


class TestDedupeKey:

    def test_stable_for_same_condition(self):
        assert make_dedupe_key("low_stock", 3, 17) == make_dedupe_key("low_stock", 3, 17)

    def test_distinct_across_stores_and_items(self):
        keys = {
            make_dedupe_key("low_stock", 1, 1),
            make_dedupe_key("low_stock", 1, 2),
            make_dedupe_key("low_stock", 2, 1),
            make_dedupe_key("stockout", 1, 1),
        }
        assert len(keys) == 4

    def test_none_ids_collapse_to_all(self):
        assert make_dedupe_key("sales_anomaly", 5, None) == "sales_anomaly:5:all"

    def test_extra_disambiguates_batches(self):
        a = make_dedupe_key("expiry_risk", 1, 1, "batch10")
        b = make_dedupe_key("expiry_risk", 1, 1, "batch11")
        assert a != b


class TestExpirySeverity:

    def test_imminent_is_critical(self):
        for d in range(0, EXPIRY_CRITICAL_DAYS + 1):
            assert expiry_severity(d) == "critical"

    def test_later_is_warning(self):
        assert expiry_severity(EXPIRY_CRITICAL_DAYS + 1) == "warning"
        assert expiry_severity(7) == "warning"


class TestAccessCheck:

    def test_super_admin_always_allowed(self):
        user = {"role": "super_admin", "permissions": {"accessible_stores": []}}
        assert AlertService._check_access({"store_id": 99}, user) is True

    def test_storeless_alert_visible_to_all(self):
        user = {"role": "store_manager", "permissions": {"accessible_stores": [1]}}
        assert AlertService._check_access({"store_id": None}, user) is True

    def test_scoped_user_denied_other_store(self):
        user = {"role": "store_manager", "permissions": {"accessible_stores": [1]}}
        assert AlertService._check_access({"store_id": 2}, user) is False

    def test_scoped_user_allowed_own_store(self):
        user = {"role": "store_manager", "permissions": {"accessible_stores": [1, 3]}}
        assert AlertService._check_access({"store_id": 3}, user) is True
