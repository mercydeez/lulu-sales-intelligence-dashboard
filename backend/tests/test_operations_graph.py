"""Operations Copilot — recommend-graph orchestration tests.

Exercises the finite-state machine end to end with a FAKE db (no Postgres), so
every transition and terminal state is covered: happy path to awaiting_approval,
refusal, stale-finding escalation, missing finding → failed, and the LLM narrate
step both when no provider is present and when a provider returns an ungrounded
number (which must be rejected, leaving the deterministic summary intact).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.operations.graph import run_recommend_graph
from app.services.operations.policy import DEFAULT_POLICY

NOW = datetime.now(timezone.utc)


class _MappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeDB:
    """Returns a finding for the findings query and snapshots for the inventory
    query. Honours the store_ids predicate the way the real query does: None =>
    all snapshots (tenant-wide), a list => only those stores, [] => nothing."""

    def __init__(self, finding=None, snapshots=None, feed_rows=None):
        self._finding = finding
        self._snapshots = snapshots or []
        # Pre-aggregated {store_id, age_hours, distinct_stamps} rows for the
        # stock-feed staleness query; None => the query returns nothing (a live,
        # non-stale feed), which is what the existing tests assume.
        self._feed_rows = feed_rows

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        if "from findings" in sql:
            return _MappingResult([self._finding] if self._finding else [])
        if "metric_inventory_state" in sql:
            stores = (params or {}).get("stores")
            if stores is None:
                return _MappingResult(self._snapshots)          # tenant-wide
            allowed = set(stores)
            return _MappingResult([s for s in self._snapshots
                                   if s["store_id"] in allowed])
        if "from inventory where store_id" in sql:
            if not self._feed_rows:
                return _MappingResult([])
            allowed = set((params or {}).get("s") or [])
            return _MappingResult([r for r in self._feed_rows
                                   if r["store_id"] in allowed])
        return _MappingResult([])


def stockout_finding(status="open", updated_at=None):
    return {
        "id": 101, "tenant_id": 1, "rule": "stockout", "category": "inventory",
        "severity": "high", "title": "Widget out of stock at Store 7",
        "detail": "Widget has zero on-hand and sells 8/day.",
        "evidence": {"average_daily_sales": 8, "current_stock": 0},
        "entity_type": "item", "entity_id": "5", "entity_name": "Widget",
        "metric_value": 8, "status": status, "action_type": "reorder",
        "updated_at": updated_at or NOW, "detected_at": updated_at or NOW,
    }


def snapshot(store_id=7, stock=0, velocity=8, reorder=50, oos=True):
    return {
        "store_id": store_id, "store_name": f"Store {store_id}", "item_id": 5,
        "item_name": "Widget", "category": "General", "current_stock": stock,
        "reorder_point": reorder, "average_daily_sales": velocity,
        "days_since_last_sale": 0, "is_out_of_stock": oos,
        "is_below_reorder": (0 < stock <= reorder),
    }


def user(role="regional_manager", stores=(7, 9)):
    return {"id": 1, "email": "u@test", "role": role, "tenant_id": 1,
            "permissions": {"accessible_stores": list(stores)}}


async def run(db, **kw):
    return await run_recommend_graph(run_id=1, tenant_id=1, finding_id=101,
                                     user=user(**kw), db=db, policy=DEFAULT_POLICY)


@pytest.mark.asyncio
class TestOrchestration:
    async def test_happy_path_reaches_awaiting_approval(self):
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        assert state["status"] == "awaiting_approval"
        assert state["recommendation"]["proposed_actions"]
        types = [e["event_type"] for e in state["events"]]
        assert "finding.loaded" in types and "proposal.drafted" in types

    async def test_missing_finding_fails_cleanly(self):
        state = await run(FakeDB(None, []))
        assert state["status"] == "failed"
        assert any(e["event_type"] == "finding.not_found" for e in state["events"])
        assert "recommendation" not in state or state.get("recommendation") is None

    async def test_resolved_finding_escalates(self):
        state = await run(FakeDB(stockout_finding(status="resolved"), [snapshot()]))
        assert state["status"] == "escalated"
        assert "resolved" in state["refusal_reason"]

    async def test_stale_finding_escalates(self):
        old = NOW - timedelta(days=30)
        state = await run(FakeDB(stockout_finding(updated_at=old), [snapshot()]))
        assert state["status"] == "escalated"
        assert any(e["event_type"] == "finding.stale" for e in state["events"])

    async def test_dead_stock_feed_escalates(self):
        # A real feed (several distinct stamps) whose newest write is 800h old:
        # we've lost sight of on-hand stock, so we must not size an order on it.
        feed = [{"store_id": 7, "age_hours": 800.0, "distinct_stamps": 5}]
        state = await run(FakeDB(stockout_finding(), [snapshot()], feed_rows=feed))
        assert state["status"] == "escalated"
        assert any(e["event_type"] == "stock.stale" for e in state["events"])
        assert not state.get("recommendation")

    async def test_bulk_loaded_snapshot_feed_is_not_stale(self):
        # A single distinct stamp is a bulk-loaded snapshot (the demo seed), not a
        # dead feed — old but trustworthy, so the copilot proceeds normally.
        feed = [{"store_id": 7, "age_hours": 5000.0, "distinct_stamps": 1}]
        state = await run(FakeDB(stockout_finding(), [snapshot()], feed_rows=feed))
        assert state["status"] == "awaiting_approval"
        assert not any(e["event_type"] == "stock.stale" for e in state["events"])

    async def test_inventory_finding_without_snapshot_refuses(self):
        state = await run(FakeDB(stockout_finding(), []))
        assert state["status"] in ("refused", "escalated")
        assert not state["recommendation"]["proposed_actions"]

    async def test_events_are_recorded_for_every_phase(self):
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        types = [e["event_type"] for e in state["events"]]
        assert "finding.loaded" in types
        assert "finding.fresh" in types
        assert "evidence.gathered" in types


@pytest.mark.asyncio
class TestScopeIsolation:
    """The store-scope read leak the Phase-2 review found must stay closed."""

    async def test_non_admin_with_empty_scope_reads_no_inventory(self):
        # A store at 7 is out of stock, but this user has an EMPTY store list.
        db = FakeDB(stockout_finding(), [snapshot(store_id=7)])
        state = await run(db, role="store_manager", stores=())
        # No in-scope inventory => refusal, and NO out-of-scope store leaks in.
        assert state["status"] in ("refused", "escalated")
        gathered = next(e for e in state["events"] if e["event_type"] == "evidence.gathered")
        assert gathered["payload"]["inventory_rows"] == 0

    async def test_non_admin_only_sees_its_own_stores(self):
        snaps = [snapshot(store_id=7), snapshot(store_id=9, stock=500, velocity=2)]
        # user can see store 7 only; the surplus donor at 9 must NOT be pulled.
        state = await run(FakeDB(stockout_finding(), snaps),
                          role="regional_manager", stores=(7,))
        gathered = next(e for e in state["events"] if e["event_type"] == "evidence.gathered")
        assert gathered["payload"]["inventory_rows"] == 1
        # With no visible donor, this can only be a replenishment (not a transfer
        # citing store 9 the user cannot see).
        if state["status"] == "awaiting_approval":
            assert state["recommendation"]["proposed_actions"][0]["action_type"] \
                == "replenishment_draft"

    async def test_super_admin_empty_scope_reads_tenant_wide(self):
        snaps = [snapshot(store_id=7), snapshot(store_id=9, stock=500, velocity=2)]
        state = await run(FakeDB(stockout_finding(), snaps),
                          role="super_admin", stores=())
        gathered = next(e for e in state["events"] if e["event_type"] == "evidence.gathered")
        assert gathered["payload"]["inventory_rows"] == 2


@pytest.mark.asyncio
class TestNarrate:
    async def test_no_provider_marks_llm_unavailable_but_completes(self, monkeypatch):
        monkeypatch.setattr("app.services.operations.graph._get_providers", lambda: [])
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        assert state["status"] == "awaiting_approval"
        assert state["recommendation"]["llm_available"] is False
        assert any(e["event_type"] == "narrate.skipped" for e in state["events"])

    async def test_ungrounded_narrative_is_rejected(self, monkeypatch):
        class _BadProvider:
            async def complete(self, messages):
                return ('{"title":"x","executive_summary":"This saves 9999 AED monthly.",'
                        '"hypotheses":[]}')
        monkeypatch.setattr("app.services.operations.graph._get_providers",
                            lambda: [_BadProvider()])
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        assert state["status"] == "awaiting_approval"
        # the invented 9999 AED must NOT appear — deterministic summary stands
        assert "9999" not in state["recommendation"]["executive_summary"]
        assert any(e["event_type"] == "narrate.rejected" for e in state["events"])

    async def test_grounded_narrative_is_applied(self, monkeypatch):
        class _GoodProvider:
            async def complete(self, messages):
                # only neutral prose, no new numbers
                return ('{"title":"Restock Widget","executive_summary":'
                        '"Widget is out at Store 7 and needs restocking soon.",'
                        '"hypotheses":[{"statement":"Demand spiked","check":"compare weeks"}]}')
        monkeypatch.setattr("app.services.operations.graph._get_providers",
                            lambda: [_GoodProvider()])
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        assert state["recommendation"]["executive_summary"].startswith("Widget is out")
        assert any(e["event_type"] == "narrate.applied" for e in state["events"])

    async def test_provider_exception_falls_back(self, monkeypatch):
        class _ErrProvider:
            async def complete(self, messages):
                raise RuntimeError("model down")
        monkeypatch.setattr("app.services.operations.graph._get_providers",
                            lambda: [_ErrProvider()])
        state = await run(FakeDB(stockout_finding(), [snapshot()]))
        assert state["status"] == "awaiting_approval"
        assert state["recommendation"]["llm_available"] is False
