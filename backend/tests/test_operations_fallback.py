"""Operations Copilot — deterministic recommendation builder tests.

The builder is the LLM-free floor: given a finding + live snapshots + policy it
must produce a fully-grounded recommendation or an honest refusal. These tests
assert the safety properties — every proposed action cites evidence that exists,
every number traces to a snapshot or the finding, and missing/insufficient data
yields a refusal, never an invented action.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operations.contracts import ActionType, ungrounded_numbers
from app.services.operations.fallback import build_recommendation
from app.services.operations.policy import DEFAULT_POLICY, OperationsPolicy
from app.services.operations.tools_read import (
    build_finding_evidence,
    build_inventory_evidence,
)

NOW = datetime.now(timezone.utc)


def stockout_finding(item_id=5):
    return {
        "id": 101, "tenant_id": 1, "rule": "stockout", "category": "inventory",
        "severity": "high", "title": "Widget is out of stock at Dubad Mall",
        "detail": "Widget has zero on-hand and sells 8/day.",
        "evidence": {"average_daily_sales": 8, "days_since_last_sale": 2, "current_stock": 0},
        "entity_type": "item", "entity_id": str(item_id), "entity_name": "Widget",
        "metric_value": 8, "status": "open", "action_type": "reorder",
    }


def snapshot(store_id, stock, velocity, reorder=50, oos=False, item_id=5, name="Widget",
             store_name=None):
    return {
        "store_id": store_id, "store_name": store_name or f"Store {store_id}",
        "item_id": item_id, "item_name": name, "category": "General",
        "current_stock": stock, "reorder_point": reorder, "average_daily_sales": velocity,
        "days_since_last_sale": 0 if velocity else 30,
        "is_out_of_stock": oos, "is_below_reorder": (0 < stock <= reorder),
    }


def revenue_finding():
    return {
        "id": 202, "tenant_id": 1, "rule": "revenue_drop", "category": "sales",
        "severity": "high", "title": "Revenue down 22% at Store 3",
        "detail": "Week-over-week revenue fell 22%.",
        "evidence": {"current_week": 8000, "prior_week": 10256},
        "entity_type": "store", "entity_id": "3", "entity_name": "Store 3",
        "metric_value": -0.22, "status": "open", "action_type": "investigate",
    }


class TestEvidenceBuilders:
    def test_inventory_evidence_ids_are_store_scoped(self):
        ev = build_inventory_evidence(snapshot(7, 0, 8), observed_at=NOW)
        ids = {e.evidence_id for e in ev}
        assert "s7_stock" in ids and "s7_velocity" in ids and "s7_reorder" in ids

    def test_finding_evidence_captures_metric_and_blob(self):
        ev = build_finding_evidence(stockout_finding(), observed_at=NOW)
        ids = {e.evidence_id for e in ev}
        assert "finding_metric" in ids
        assert "finding_average_daily_sales" in ids

    def test_evidence_source_types_distinguish_estimates(self):
        inv = build_inventory_evidence(snapshot(7, 0, 8), observed_at=NOW)
        assert all(e.source_type.value == "inventory" for e in inv)


class TestReplenishmentPath:
    def test_stockout_produces_a_replenishment_draft(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        assert rec.is_actionable
        act = rec.proposed_actions[0]
        assert act.action_type == ActionType.REPLENISHMENT_DRAFT
        assert act.target_item_ids == [5]
        assert act.calculated_parameters["quantity"] > 0

    def test_no_supplier_is_selected(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        assert rec.proposed_actions[0].calculated_parameters["supplier"] is None

    def test_replenishment_requires_regional_manager_by_default(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        assert rec.approval_requirement.required_role == "regional_manager"

    def test_measurement_plan_is_set_before_approval(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        assert rec.measurement_plan.metric_name == "days_of_cover"
        assert rec.measurement_plan.window_days == DEFAULT_POLICY.measurement_window_days


class TestTransferPath:
    def test_surplus_sibling_yields_a_transfer(self):
        snaps = [snapshot(7, 0, 20, oos=True, store_name="Needy"),
                 snapshot(9, 500, 2, store_name="Surplus")]
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=snaps, policy=DEFAULT_POLICY, now=NOW)
        assert rec.is_actionable
        act = rec.proposed_actions[0]
        assert act.action_type == ActionType.STOCK_TRANSFER_DRAFT
        assert set(act.target_store_ids) == {7, 9}
        assert act.required_approval_role == "regional_manager"

    def test_transfer_falls_back_to_replenishment_when_source_cannot_spare(self):
        # sibling has stock but no real surplus over its own safety cover
        snaps = [snapshot(7, 0, 10, oos=True), snapshot(9, 40, 10)]
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=snaps, policy=DEFAULT_POLICY, now=NOW)
        assert rec.is_actionable
        assert rec.proposed_actions[0].action_type == ActionType.REPLENISHMENT_DRAFT


class TestInvestigationPath:
    def test_revenue_drop_yields_an_investigation(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=revenue_finding(),
                                   snapshots=[], policy=DEFAULT_POLICY, now=NOW)
        assert rec.is_actionable
        act = rec.proposed_actions[0]
        assert act.action_type == ActionType.INVESTIGATION_TASK
        assert act.target_store_ids == [3]
        assert act.expected_effect == "unknown"          # honest: investigation ≠ fix
        assert rec.hypotheses                              # labelled hypotheses present

    def test_investigation_requires_store_manager_by_default(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=revenue_finding(),
                                   snapshots=[], policy=DEFAULT_POLICY, now=NOW)
        assert rec.approval_requirement.required_role == "store_manager"


class TestRefusals:
    def test_inventory_finding_without_snapshot_refuses(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[], policy=DEFAULT_POLICY, now=NOW)
        assert not rec.is_actionable
        assert rec.refusal_reason and rec.missing_data

    def test_well_stocked_item_refuses_to_reorder(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 5000, 8)],
                                   policy=DEFAULT_POLICY, now=NOW)
        assert not rec.is_actionable

    def test_insufficient_evidence_refuses(self):
        """Raising the evidence floor above what a single snapshot provides must
        force a refusal, not a thin proposal."""
        strict = OperationsPolicy(min_evidence_items=20)
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=strict, now=NOW)
        assert not rec.is_actionable
        assert rec.refusal_reason


class TestGrounding:
    def test_every_number_in_the_summary_is_grounded(self):
        """The builder's own prose must pass the same check the LLM path faces."""
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        qty = rec.proposed_actions[0].calculated_parameters["quantity"]
        extra = [qty, 8, 0] + [v for v in rec.proposed_actions[0].calculated_parameters.values()
                               if isinstance(v, (int, float))]
        assert ungrounded_numbers(rec.executive_summary, rec.evidence, extra_allowed=extra) == []

    def test_all_cited_evidence_exists(self):
        rec = build_recommendation(run_id=1, tenant_id=1, finding=stockout_finding(),
                                   snapshots=[snapshot(7, 0, 8, oos=True)],
                                   policy=DEFAULT_POLICY, now=NOW)
        known = {e.evidence_id for e in rec.evidence}
        for act in rec.proposed_actions:
            assert act.evidence_ids and all(e in known for e in act.evidence_ids)
        for fact in rec.measured_facts:
            assert all(e in known for e in fact.evidence_ids)
