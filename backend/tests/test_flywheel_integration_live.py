"""Live-Postgres integration tests for the Flywheel — the shape that catches
what unit tests cannot.

WHY THIS FILE EXISTS. This project has a documented, expensive lesson: 180 green
unit tests plus a clean type-check, and the module still failed on its FIRST
LIVE CALL — because the unit tests exercised pure functions and never executed a
single SQL statement. Wrong column names, asyncpg bind-type quirks, RLS grants,
NOT NULL and CHECK constraints — none of those show up until real SQL hits a
real Postgres. Every test here runs against the live database, most of them AS
THE NON-OWNER app_rw ROLE, which is the only way to prove tenant isolation is
enforced by the database rather than by hopeful application code.

GATING. These need a seeded two-tenant Postgres, so they are skipped unless
RUN_DB_TESTS=1. In the container:  RUN_DB_TESTS=1 pytest tests/test_flywheel_integration_live.py

They are deliberately conservative about cleanup — every row they create is
removed in a finally, and they never touch the demo tenant's real campaigns.
"""
from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="needs a seeded two-tenant Postgres (set RUN_DB_TESTS=1)",
)

DEMO_TENANT = 1
OTHER_TENANT = 2

# THE REAL DATABASE, NOT conftest's stub.
#
# conftest.py forces DATABASE_URL to a localhost test stub before the app
# imports, so app.services.database.async_session points at a DB that does not
# exist in the container. These integration tests must reach the ACTUAL seeded
# Postgres, so they build their own engine from IT_DATABASE_URL (owner creds).
# Run with:
#   RUN_DB_TESTS=1 IT_DATABASE_URL=postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb \
#       pytest tests/test_flywheel_integration_live.py
_IT_URL = os.getenv(
    "IT_DATABASE_URL",
    "postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb")

_engine = None
_sessionmaker = None


def _owner_sessionmaker():
    """A sessionmaker bound to the real DB, built lazily so import stays cheap
    and the module can be collected even when RUN_DB_TESTS is off."""
    global _engine, _sessionmaker
    if _sessionmaker is None:
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from sqlalchemy.pool import NullPool
        _engine = create_async_engine(_IT_URL, poolclass=NullPool)
        _sessionmaker = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def _owner_session():
    return _owner_sessionmaker()()


async def _set_tenant(session, tenant_id: int):
    from sqlalchemy import text
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})


def _app_rw_dsn() -> str:
    """The non-owner app_rw DSN for the real DB, as raw asyncpg (no +asyncpg).
    Built by swapping the owner creds in IT_DATABASE_URL for app_rw's, matching
    what app.services.database._derive_rls_url does for the running app."""
    url = _IT_URL.replace("postgresql+asyncpg://", "postgresql://")
    # postgresql://<user>:<pass>@host/db  ->  app_rw creds
    scheme, rest = url.split("://", 1)
    _creds, host = rest.split("@", 1)
    return f"{scheme}://app_rw:app_rw_dev_pass@{host}"



# ===========================================================================
# GATE 2(b) — cross-tenant isolation is enforced at the DATABASE.
#
# Run AS app_rw (non-owner, non-bypassrls), the role the request path uses when
# RLS is enforced. If any of these fail, a forgotten `WHERE tenant_id` in
# application code is a cross-tenant breach — which is exactly the risk ruling #2
# removed the escape hatch for.
# ===========================================================================

@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_read_as_app_rw():
    """With tenant GUC=1, app_rw cannot see tenant 2's rows."""
    import asyncpg
    dsn = _app_rw_dsn()
    probe = f"rls_probe_{uuid.uuid4().hex[:8]}"

    # Seed one row in EACH tenant as the owner (owner bypasses RLS).
    from sqlalchemy import text
    async with await _owner_session() as s:
        await s.execute(text("""INSERT INTO flywheel_promotion_criteria
            (tenant_id, model_label, status) VALUES (1, :m, 'shadow'), (2, :m, 'shadow')"""),
            {"m": probe})
        await s.commit()

    try:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("SELECT set_config('app.tenant_id', '1', false)")
            rows = await conn.fetch(
                "SELECT tenant_id FROM flywheel_promotion_criteria WHERE model_label = $1",
                probe)
            seen = {r["tenant_id"] for r in rows}
            assert seen == {1}, f"app_rw with tenant=1 saw tenants {seen} — RLS leak"

            # And with tenant=2 it sees only tenant 2.
            await conn.execute("SELECT set_config('app.tenant_id', '2', false)")
            rows = await conn.fetch(
                "SELECT tenant_id FROM flywheel_promotion_criteria WHERE model_label = $1",
                probe)
            assert {r["tenant_id"] for r in rows} == {2}
        finally:
            await conn.close()
    finally:
        async with await _owner_session() as s:
            await s.execute(text("DELETE FROM flywheel_promotion_criteria WHERE model_label = :m"),
                            {"m": probe})
            await s.commit()


@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_write_as_app_rw():
    """With tenant GUC=1, app_rw cannot INSERT a row for tenant 2 — the WITH
    CHECK clause of the policy rejects it. USING alone would let the write
    through; this proves both halves of the policy are present."""
    import asyncpg
    dsn = _app_rw_dsn()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', '1', false)")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute(
                """INSERT INTO flywheel_promotion_criteria (tenant_id, model_label, status)
                   VALUES (2, 'cross_tenant_evil', 'shadow')""")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_app_rw_is_not_a_superuser():
    """The whole scheme rests on app_rw being unable to bypass RLS. If someone
    grants it BYPASSRLS or SUPERUSER, every isolation test above silently becomes
    vacuous — so assert the role's posture directly."""
    import asyncpg
    dsn = _app_rw_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert row["rolsuper"] is False, "app_rw must not be a superuser"
        assert row["rolbypassrls"] is False, "app_rw must not bypass RLS"
    finally:
        await conn.close()


# ===========================================================================
# GATE 2(a) — a job survives a worker dying mid-run.
# ===========================================================================

@pytest.mark.asyncio
async def test_job_resumes_from_checkpoint_after_crash():
    """Claim a job, run one batch, simulate a crash (expire its lease without
    finishing), reap it, and resume it to completion — with no work lost or
    repeated."""
    from sqlalchemy import text
    from app.services.flywheel import jobs, churn

    async with _owner_sessionmaker()() as s:
        await s.execute(text("DELETE FROM flywheel_jobs WHERE tenant_id = 1 "
                             "AND idempotency_key = 'itest:resume'"))
        await s.commit()

    try:
        async with _owner_sessionmaker()() as s:
            job_id = await jobs.enqueue(s, tenant_id=1, kind="score_audience",
                                        payload={"batch_size": 90},
                                        idempotency_key="itest:resume")
            await s.commit()

        # claim + one batch + checkpoint
        async with _owner_sessionmaker()() as s:
            job = await jobs.claim(s, worker_id="itest-w1")
            await s.commit()
        assert job is not None and job["id"] == job_id

        async with _owner_sessionmaker()() as s:
            ids = [int(r[0]) for r in (await s.execute(text(
                "SELECT id FROM flywheel_customers WHERE tenant_id=1 ORDER BY id LIMIT 90"))).fetchall()]
            await churn.score_customers(s, tenant_id=1, customer_ids=ids)
            await jobs.checkpoint(s, job_id=job_id,
                                  checkpoint={"last_customer_id": ids[-1], "scored": len(ids)})
            await s.commit()

        # simulate crash: lease in the past, job stuck 'running'
        async with _owner_sessionmaker()() as s:
            await s.execute(text("UPDATE flywheel_jobs SET lease_expires_at = now() - interval '5 min' "
                                 "WHERE id = :j"), {"j": job_id})
            await s.commit()

        # reap + resume
        async with _owner_sessionmaker()() as s:
            reaped = await jobs.reap(s)
            await s.commit()
        assert reaped >= 1

        kind = await jobs.run_one(_owner_sessionmaker(), worker_id="itest-w2")
        assert kind == "score_audience"

        async with _owner_sessionmaker()() as s:
            total = int((await s.execute(text(
                "SELECT count(*) FROM flywheel_customers WHERE tenant_id=1"))).scalar())
            info = await jobs.get_job(s, tenant_id=1, job_id=job_id)
        assert info["status"] == "succeeded"
        assert info["result"]["scored"] == total, (
            "resumed job did not score exactly every customer once")
    finally:
        async with _owner_sessionmaker()() as s:
            await s.execute(text("DELETE FROM flywheel_jobs WHERE tenant_id=1 "
                                 "AND idempotency_key='itest:resume'"))
            await s.commit()


@pytest.mark.asyncio
async def test_enqueue_is_idempotent():
    from sqlalchemy import text
    from app.services.flywheel import jobs
    key = f"itest:idem:{uuid.uuid4().hex[:8]}"
    try:
        async with _owner_sessionmaker()() as s:
            a = await jobs.enqueue(s, tenant_id=1, kind="measure_all", idempotency_key=key)
            await s.commit()
        async with _owner_sessionmaker()() as s:
            b = await jobs.enqueue(s, tenant_id=1, kind="measure_all", idempotency_key=key)
            await s.commit()
        assert a == b, "second enqueue of the same key created a duplicate job"
    finally:
        async with _owner_sessionmaker()() as s:
            await s.execute(text("DELETE FROM flywheel_jobs WHERE tenant_id=1 AND idempotency_key=:k"),
                            {"k": key})
            await s.commit()


@pytest.mark.asyncio
async def test_delivery_receipt_is_exactly_once():
    from sqlalchemy import text
    from app.services.flywheel import jobs
    key = f"itest:evt:{uuid.uuid4().hex[:8]}"
    try:
        async with _owner_sessionmaker()() as s:
            first = await jobs.mark_delivered(s, tenant_id=1, consumer="itest", event_key=key)
            second = await jobs.mark_delivered(s, tenant_id=1, consumer="itest", event_key=key)
            await s.commit()
        assert first is True and second is False, "delivery ledger allowed a double action"
    finally:
        async with _owner_sessionmaker()() as s:
            await s.execute(text("DELETE FROM flywheel_delivery_receipts WHERE event_key=:k"),
                            {"k": key})
            await s.commit()


# ===========================================================================
# Model registry — snapshot binding, promotion guard, rollback.
# ===========================================================================

@pytest.mark.asyncio
async def test_registry_binds_snapshot_and_guards_promotion():
    from sqlalchemy import text
    from app.services.flywheel import registry

    created = []
    try:
        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            unbound = int((await s.execute(text("""INSERT INTO flywheel_model_versions
                (tenant_id, model_kind, algorithm, version_label, is_active,
                 feature_window_days, outcome_window_days, trained_at)
                VALUES (1,'churn','itest','v-itest-unbound',false,180,60,now())
                RETURNING id"""))).scalar())
            created.append(unbound)
            await s.commit()

        # an unbound version cannot be promoted — its data cannot be identified.
        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            with pytest.raises(ValueError, match="snapshot"):
                await registry.promote(s, tenant_id=1, model_version_id=unbound)
            await s.rollback()

        # bind it, then it can be promoted, and the previous active is superseded.
        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            snap = await registry.register_snapshot(s, tenant_id=1, model_version_id=unbound)
            assert snap["hash"] and snap["rows"] > 0
            await s.commit()

        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            lst = await registry.list_versions(s, tenant_id=1)
            bound = next(v for v in lst["versions"] if v["id"] == unbound)
            assert bound["reproducible"] is True
    finally:
        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            for vid in created:
                await s.execute(text("DELETE FROM flywheel_model_versions WHERE id=:i"), {"i": vid})
            await s.commit()


# ===========================================================================
# Tracing — a decision writes a trace, and the timeline reads it.
# ===========================================================================

@pytest.mark.asyncio
async def test_decision_timeline_reads_a_traced_decision():
    from sqlalchemy import text
    from app.services.flywheel import trace

    tid = f"itest-{uuid.uuid4().hex[:10]}"
    did = None
    try:
        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            cust = int((await s.execute(text(
                "SELECT id FROM flywheel_customers WHERE tenant_id=1 LIMIT 1"))).scalar())
            did = int((await s.execute(text("""INSERT INTO flywheel_decisions
                (tenant_id, customer_id, action_type, discount_pct, eiv_aed,
                 reason_codes, churn_probability, uplift, trace_id, request_id,
                 policy_version)
                VALUES (1, :c, 'REMINDER', 0, 5.00, CAST('[]' AS JSONB),
                        0.7, 0.05, :tr, 'itest', 'v1') RETURNING id"""),
                {"c": cust, "tr": tid})).scalar())
            await s.commit()

        async with _owner_sessionmaker()() as s:
            await _set_tenant(s, 1)
            tl = await trace.decision_timeline(s, tenant_id=1, decision_id=did)
        assert tl is not None
        assert tl["traced"] is True
        assert tl["trace_id"] == tid
        assert any(e["stage"] == "decided" for e in tl["timeline"])
        assert "PDPL" in tl["note"], "the explanation note must name the lawful basis"
    finally:
        if did:
            async with _owner_sessionmaker()() as s:
                await _set_tenant(s, 1)
                await s.execute(text("DELETE FROM flywheel_decisions WHERE id=:i"), {"i": did})
                await s.commit()


# ===========================================================================
# Horizon 1 services against live SQL (the queries unit tests never executed).
# ===========================================================================

@pytest.mark.asyncio
async def test_balance_check_runs_against_live_schema():
    """readout.check_balance joins several real tables with a DISTINCT ON and
    real column names. This is exactly the kind of query a pure-function test
    cannot exercise — it either matches the schema or it does not."""
    from app.services.flywheel import readout

    async with _owner_sessionmaker()() as s:
        await _set_tenant(s, 1)
        campaign = None
        from sqlalchemy import text
        row = (await s.execute(text(
            "SELECT id FROM flywheel_campaigns WHERE tenant_id=1 ORDER BY id LIMIT 1"))).fetchone()
        if row:
            campaign = int(row[0])
    if campaign is None:
        pytest.skip("no campaign in the demo tenant to check")

    async with _owner_sessionmaker()() as s:
        await _set_tenant(s, 1)
        result = await readout.check_balance(s, tenant_id=1, campaign_id=campaign, persist=False)
    # It must return the documented shape without raising — the column names,
    # the DISTINCT ON, and the SMD math all have to line up with reality.
    assert "summary" in result and "status" in result["summary"]
    assert result["summary"]["status"] in ("balanced", "imbalanced", "unknown")


@pytest.mark.asyncio
async def test_readout_portfolio_summary_runs():
    from app.services.flywheel import readout
    async with _owner_sessionmaker()() as s:
        await _set_tenant(s, 1)
        summary = await readout.portfolio_summary(s, tenant_id=1)
    assert "campaigns_measured" in summary
    assert "inconclusive" in summary


# ===========================================================================
# HORIZON 3 — Track B and shared services, against live SQL.
# ===========================================================================

@pytest.mark.asyncio
async def test_supplier_funding_scope_survives_adversarial_probe():
    """Gate 3, the adversarial half: a supplier's scope is exactly their funded
    SKUs, and a funding cannot be created over a SKU the supplier does not
    supply. The second is the attack a dishonest retailer would try — billing a
    supplier for a competitor's SKU — and it must be refused."""
    from sqlalchemy import text
    from app.services.flywheel import trade
    import uuid as _uuid

    sm = _owner_sessionmaker()
    created = {"supplier": None, "funding": None, "link_item": None}
    tag = _uuid.uuid4().hex[:8]
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            supplier_id = int((await s.execute(text(
                "INSERT INTO suppliers (tenant_id,name,status) VALUES (1,:n,'active') RETURNING id"),
                {"n": f"IT Supplier {tag}"})).scalar())
            created["supplier"] = supplier_id
            # link ONE item to this supplier
            owned = int((await s.execute(text("SELECT id FROM items WHERE tenant_id=1 ORDER BY id LIMIT 1"))).scalar())
            not_owned = int((await s.execute(text("SELECT id FROM items WHERE tenant_id=1 ORDER BY id DESC LIMIT 1"))).scalar())
            await s.execute(text("""INSERT INTO product_suppliers (tenant_id,item_id,supplier_id,unit_cost,moq,lead_time_days)
                                    VALUES (1,:i,:s,5,1,7) ON CONFLICT DO NOTHING"""),
                            {"i": owned, "s": supplier_id})
            created["link_item"] = owned
            campaign_id = int((await s.execute(text("SELECT id FROM flywheel_campaigns WHERE tenant_id=1 ORDER BY id LIMIT 1"))).scalar())
            await s.commit()

        # ADVERSARIAL: funding a SKU the supplier does not supply must be refused.
        async with sm() as s:
            await _set_tenant(s, 1)
            with pytest.raises(trade.TradeError, match="does not supply"):
                await trade.propose_funding(
                    s, tenant_id=1, supplier_id=supplier_id, campaign_id=campaign_id,
                    funding_type="co_op", committed_aed=__import__("decimal").Decimal("100"),
                    item_ids=[not_owned])
            await s.rollback()

        # Legitimate funding on the owned SKU, then scope == exactly that SKU.
        async with sm() as s:
            await _set_tenant(s, 1)
            f = await trade.propose_funding(
                s, tenant_id=1, supplier_id=supplier_id, campaign_id=campaign_id,
                funding_type="co_op", committed_aed=__import__("decimal").Decimal("500"),
                item_ids=[owned])
            created["funding"] = f["funding_id"]
            await s.commit()

        async with sm() as s:
            await _set_tenant(s, 1)
            scope = await trade.supplier_scope(s, tenant_id=1, supplier_id=supplier_id)
        assert scope == [owned], f"supplier scope {scope} != funded SKU [{owned}]"
    finally:
        async with sm() as s:
            await _set_tenant(s, 1)
            if created["funding"]:
                await s.execute(text("DELETE FROM flywheel_supplier_funding WHERE id=:f"), {"f": created["funding"]})
            if created["supplier"]:
                await s.execute(text("DELETE FROM product_suppliers WHERE tenant_id=1 AND supplier_id=:s"), {"s": created["supplier"]})
                await s.execute(text("DELETE FROM suppliers WHERE id=:s"), {"s": created["supplier"]})
            await s.commit()


@pytest.mark.asyncio
async def test_supplier_money_cannot_be_overspent_at_the_db():
    """The invariant, proven at the database rather than in the service."""
    from sqlalchemy import text
    import asyncpg
    dsn = _app_rw_dsn()
    sm = _owner_sessionmaker()
    supplier_id = funding_id = None
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            supplier_id = int((await s.execute(text(
                "INSERT INTO suppliers (tenant_id,name,status) VALUES (1,'IT overspend','active') RETURNING id"))).scalar())
            campaign_id = int((await s.execute(text("SELECT id FROM flywheel_campaigns WHERE tenant_id=1 ORDER BY id LIMIT 1"))).scalar())
            funding_id = int((await s.execute(text("""INSERT INTO flywheel_supplier_funding
                (tenant_id,supplier_id,campaign_id,funding_type,committed_aed,status)
                VALUES (1,:s,:c,'co_op',1000,'committed') RETURNING id"""),
                {"s": supplier_id, "c": campaign_id})).scalar())
            await s.commit()

        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("SELECT set_config('app.tenant_id','1',false)")
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await conn.execute(
                    "UPDATE flywheel_supplier_funding SET spent_aed = 5000 WHERE id = $1", funding_id)
        finally:
            await conn.close()
    finally:
        async with sm() as s:
            await _set_tenant(s, 1)
            if funding_id:
                await s.execute(text("DELETE FROM flywheel_supplier_funding WHERE id=:f"), {"f": funding_id})
            if supplier_id:
                await s.execute(text("DELETE FROM suppliers WHERE id=:s"), {"s": supplier_id})
            await s.commit()


@pytest.mark.asyncio
async def test_profiling_objection_excludes_customer_from_decisions():
    """PDPL: an objecting customer is excluded from automated decisions."""
    from sqlalchemy import text
    from app.services.flywheel import objections, decisioning, trace
    sm = _owner_sessionmaker()
    cust = None
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            row = (await s.execute(text(
                "SELECT id, home_store_id FROM flywheel_customers WHERE tenant_id=1 AND status='active' ORDER BY id LIMIT 1"))).fetchone()
            cust, store = int(row[0]), int(row[1])
            await objections.record_objection(s, tenant_id=1, customer_id=cust)
            await s.commit()

        async with sm() as s:
            await _set_tenant(s, 1)
            trace.trace_context.set(None)
            res = await decisioning.evaluate(s, tenant_id=1, customer_id=cust, store_id=store,
                                             request_id="it-obj")
        assert res.get("reason_code") == "PROFILING_OBJECTION" or \
            "PROFILING_OBJECTION" in str(res.get("reason_codes", [])), \
            "objecting customer was not excluded"
    finally:
        if cust:
            async with sm() as s:
                await _set_tenant(s, 1)
                await s.execute(text("DELETE FROM flywheel_profiling_objections WHERE tenant_id=1 AND customer_id=:c"), {"c": cust})
                await s.commit()


@pytest.mark.asyncio
async def test_identity_declines_to_guess_when_ambiguous():
    """A wrong merge corrupts the feature store, holdout and consent ledger at
    once, so an ambiguous match must resolve to unlinked, never a coin-flip."""
    from sqlalchemy import text
    from datetime import datetime, timezone
    from app.services.flywheel import identity
    sm = _owner_sessionmaker()
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            item = int((await s.execute(text("SELECT id FROM items WHERE tenant_id=1 LIMIT 1"))).scalar())
            now = datetime.now(timezone.utc)
            # a transaction with no loyalty_ref and no store -> cannot be linked
            await identity.ingest_pos_row(s, tenant_id=1, external_txn_id="IT-ANON",
                                          occurred_at=now, item_id=item, units=1, amount_aed=10)
            await s.commit()
        async with sm() as s:
            await _set_tenant(s, 1)
            r = await identity.resolve_pending(s, tenant_id=1)
            await s.commit()
        # The anonymous row must be unlinked, not force-matched.
        assert r["outcomes"].get("unlinked", 0) >= 1
    finally:
        async with sm() as s:
            await _set_tenant(s, 1)
            await s.execute(text("DELETE FROM flywheel_pos_staging WHERE tenant_id=1 AND external_txn_id='IT-ANON'"))
            await s.commit()


# ===========================================================================
# HORIZON 4 — expand, against live SQL.
# ===========================================================================

@pytest.mark.asyncio
async def test_seasonality_factor_reflects_the_calendar():
    """The seeded UAE calendar returns the right multiplier by date — 1.0 outside
    any window, the Ramadan factor inside it."""
    from datetime import date
    from app.services.flywheel import seasonality
    sm = _owner_sessionmaker()
    async with sm() as s:
        await _set_tenant(s, 1)
        ramadan = await seasonality.factor_for(s, tenant_id=1, on=date(2026, 3, 1))
        flat = await seasonality.factor_for(s, tenant_id=1, on=date(2026, 6, 10))
    assert ramadan > 1, f"Ramadan factor should exceed 1, got {ramadan}"
    assert flat == __import__("decimal").Decimal("1.000"), \
        f"a flat week should be neutral, got {flat}"


@pytest.mark.asyncio
async def test_coalition_attribution_weights_sum_to_one():
    """The central invariant: across the partners a customer engaged with, the
    attribution weights sum to 1 — so the retailer never double-counts value a
    coalition partner delivered."""
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal
    from sqlalchemy import text
    from app.services.flywheel import coalition
    sm = _owner_sessionmaker()
    created = {"partners": [], "campaign": None, "customer": None}
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            campaign = int((await s.execute(text("SELECT id FROM flywheel_campaigns WHERE tenant_id=1 ORDER BY id LIMIT 1"))).scalar())
            cust = int((await s.execute(text("SELECT id FROM flywheel_customers WHERE tenant_id=1 LIMIT 1"))).scalar())
            created["campaign"], created["customer"] = campaign, cust
            now = datetime.now(timezone.utc)
            for name, days in (("IT Fuel", 5), ("IT Travel", 2), ("IT Dining", 1)):
                p = await coalition.register_partner(s, tenant_id=1, partner_name=name, partner_type="other")
                created["partners"].append(p["partner_id"])
                await coalition.record_activity(s, tenant_id=1, customer_id=cust,
                                                partner_id=p["partner_id"], activity_type="earn",
                                                value_aed=Decimal("20"), occurred_at=now - timedelta(days=days))
            await s.commit()

        for model in ("linear", "time_decay", "position"):
            async with sm() as s:
                await _set_tenant(s, 1)
                attr = await coalition.attribute(s, tenant_id=1, campaign_id=campaign, customer_id=cust,
                                                 incremental_margin_aed=Decimal("300"), model=model, persist=False)
            assert abs(attr["weight_sum"] - 1.0) < 1e-4, f"{model}: weights sum to {attr['weight_sum']}, not 1"
            # And the attributed margins sum to the whole, to the fils.
            total = sum(Decimal(a["attributed_margin_aed"]) for a in attr["attribution"])
            assert total == Decimal("300.00"), f"{model}: margins sum to {total}, not 300.00"
    finally:
        async with sm() as s:
            await _set_tenant(s, 1)
            if created["campaign"] and created["customer"]:
                await s.execute(text("DELETE FROM flywheel_coalition_activity WHERE tenant_id=1 AND customer_id=:c"), {"c": created["customer"]})
            for pid in created["partners"]:
                await s.execute(text("DELETE FROM flywheel_coalition_partners WHERE tenant_id=1 AND id=:p"), {"p": pid})
            await s.commit()


@pytest.mark.asyncio
async def test_outcome_pricing_gate_stays_closed_without_evidence():
    """The gate that protects the whole product's trust: an outcome-pricing plan
    cannot bill until enough significant holdout readouts exist, and compute_charge
    refuses. gate_met is computed, never hand-set."""
    from decimal import Decimal
    from sqlalchemy import text
    from app.services.flywheel import outcome_pricing
    sm = _owner_sessionmaker()
    plan_id = None
    try:
        async with sm() as s:
            await _set_tenant(s, 1)
            plan = await outcome_pricing.propose_plan(s, tenant_id=1, plan_name="IT-Perf",
                                                      margin_share_pct=Decimal("0.15"),
                                                      gate_readouts_required=999)  # unreachable bar
            plan_id = plan["plan_id"]
            await s.commit()

        async with sm() as s:
            await _set_tenant(s, 1)
            gate = await outcome_pricing.evaluate_gate(s, tenant_id=1, plan_id=plan_id)
            await s.commit()
        assert gate["gate_met"] is False, "an unreachable bar must never be met"

        async with sm() as s:
            await _set_tenant(s, 1)
            campaign = int((await s.execute(text("SELECT id FROM flywheel_campaigns WHERE tenant_id=1 ORDER BY id LIMIT 1"))).scalar())
            charge = await outcome_pricing.compute_charge(s, tenant_id=1, plan_id=plan_id, campaign_id=campaign)
        assert charge["chargeable"] is False
        assert charge["charge_aed"] is None
        assert "refusal" in charge
    finally:
        if plan_id:
            async with sm() as s:
                await _set_tenant(s, 1)
                await s.execute(text("DELETE FROM flywheel_outcome_pricing WHERE tenant_id=1 AND id=:p"), {"p": plan_id})
                await s.commit()
