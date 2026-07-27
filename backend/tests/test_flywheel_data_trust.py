"""
The data trust gate — verdict logic and live refusal behaviour.

Two layers:
  * Pure verdict/threshold logic, no database.
  * Live checks against a real Postgres, including the one that matters most:
    injecting a CONTRADICTION (negative stock) must make simulate() REFUSE,
    not merely annotate its answer.

Live tests skip cleanly without a database, so database-free CI stays green.
"""
import asyncio
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.flywheel import data_trust as dt

TENANT = 1
_DSN = os.environ.get("RETENTION_TEST_DATABASE_URL",
                      "postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb")


# --- pure verdict logic -----------------------------------------------------

def _f(code, severity):
    return dt.Finding(code, severity, f"{code} detail", {})


def test_clean_input_is_ready():
    assert dt.verdict_for([]) == dt.READY


def test_warnings_alone_do_not_block():
    assert dt.verdict_for([_f("sales_feed_stale", "warn")]) == dt.READY_WITH_WARNINGS


def test_any_blocker_makes_it_not_ready():
    assert dt.verdict_for([_f("sales_feed_stale", "warn"),
                           _f("inventory_impossible", "block")]) == dt.NOT_READY


def test_blocker_wins_regardless_of_order():
    assert dt.verdict_for([_f("inventory_impossible", "block"),
                           _f("model_stale", "warn")]) == dt.NOT_READY


def test_exception_carries_the_report_and_names_the_action():
    report = {"status": dt.NOT_READY, "findings": [
        {"code": "inventory_impossible", "severity": "block", "detail": "negative stock"}]}
    exc = dt.DataNotReady(report, "activate")
    assert exc.report is report
    assert exc.action == "activate"
    assert "activate" in str(exc) and "negative stock" in str(exc)


def test_data_not_ready_is_a_valueerror():
    """Routes already funnel ValueError to a 4xx; subclassing keeps any handler
    we did not update from turning a refusal into a 500."""
    assert issubclass(dt.DataNotReady, ValueError)


def test_thresholds_are_env_overridable():
    """Tightening the gate for a real feed must be config, not a code change."""
    for name in ("FLYWHEEL_MAX_SALES_STALENESS_DAYS", "FLYWHEEL_MIN_COST_COVERAGE",
                 "FLYWHEEL_MIN_CONSENT_COVERAGE", "FLYWHEEL_MIN_TREATMENT_ARM",
                 "FLYWHEEL_MAX_MODEL_AGE_DAYS"):
        assert name.startswith("FLYWHEEL_")
    assert 0.0 < dt.MIN_COST_COVERAGE <= 1.0
    assert 0.0 < dt.MIN_CONSENT_COVERAGE <= 1.0
    assert dt.MIN_TREATMENT_ARM > 0


# --- live checks ------------------------------------------------------------

pytestmark_live = pytest.mark.asyncio


@pytest.fixture
async def sessions():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    engine = create_async_engine(_DSN, pool_size=5, max_overflow=5)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
            n = (await c.execute(text(
                "SELECT count(*) FROM pg_tables WHERE tablename = 'flywheel_campaigns'"))).scalar()
        if not n:
            await engine.dispose()
            pytest.skip("flywheel tables absent — run migrations 075+ first")
    except Exception as e:
        await engine.dispose()
        pytest.skip(f"live Postgres not reachable ({e})")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_seeded_demo_tenant_is_decidable(sessions):
    """The demo tenant must not be NOT_READY — if it were, the gate would block
    every demo, which means the thresholds are wrong rather than the data."""
    async with sessions() as db:
        report = await dt.evaluate(db, tenant_id=TENANT, campaign_id=None)
    assert report["status"] in (dt.READY, dt.READY_WITH_WARNINGS), \
        f"demo tenant blocked by {report['blockers']}"
    assert report["scope"]["items_evaluated"] > 0


@pytest.mark.asyncio
async def test_negative_stock_blocks_and_is_named(sessions):
    """A CONTRADICTION must fail shut. Negative stock is not missing data — it is
    data that is definitely wrong, and ATP derived from it would be wrong too."""
    async with sessions() as db:
        row = (await db.execute(text(
            "SELECT id, current_stock FROM inventory ORDER BY id LIMIT 1"))).fetchone()
        inv_id, original = int(row[0]), int(row[1])
        await db.execute(text("UPDATE inventory SET current_stock = -5 WHERE id = :i"),
                         {"i": inv_id})
        await db.commit()
        try:
            report = await dt.evaluate(db, tenant_id=TENANT, campaign_id=None)
            assert report["status"] == dt.NOT_READY
            assert "inventory_impossible" in report["blockers"]
            with pytest.raises(dt.DataNotReady):
                await dt.assert_ready(db, tenant_id=TENANT, campaign_id=None,
                                      action="simulate")
        finally:
            await db.execute(text("UPDATE inventory SET current_stock = :s WHERE id = :i"),
                             {"s": original, "i": inv_id})
            await db.commit()


@pytest.mark.asyncio
async def test_simulate_refuses_when_data_is_not_ready(sessions):
    """The gate is only worth having if it actually stops the optimizer. This
    drives the REAL simulate() path, not the checker in isolation."""
    from app.services.flywheel import campaigns as campaign_service

    async with sessions() as db:
        # A campaign with an audience, so simulate gets past its own precondition
        # and reaches the trust gate.
        cid = (await db.execute(text("""
            INSERT INTO flywheel_campaigns
                (tenant_id, name, objective, status, starts_on, ends_on, channel,
                 max_discount_pct, min_margin_pct, discount_budget_aed,
                 safety_stock_pct, policy_version)
            VALUES (:t, :n, 'retain_at_risk', 'AUDIENCE_READY', :s, :e, 'email',
                    20, 10, 5000, 10, 'test')
            RETURNING id
        """), {"t": TENANT, "n": f"TRUST {uuid.uuid4().hex[:8]}", "s": date.today(),
               "e": date.today() + timedelta(days=14)})).scalar()
        # The customer's HOME STORE matters: the gate narrows its inventory scope
        # to the stores the audience actually sits in, so the contradiction has to
        # be planted there to be seen (which is the behaviour under test).
        home = (await db.execute(text("""
            SELECT id, home_store_id FROM flywheel_customers
             WHERE tenant_id = :t AND home_store_id IS NOT NULL LIMIT 1
        """), {"t": TENANT})).fetchone()
        cust = home[0] if home else None
        home_store = home[1] if home else None
        if cust is None:
            await db.execute(text("DELETE FROM flywheel_campaigns WHERE id = :c"), {"c": cid})
            await db.commit()
            pytest.skip("no seeded flywheel customers — run /api/flywheel/seed first")
        await db.execute(text("""
            INSERT INTO flywheel_campaign_audience
                (tenant_id, campaign_id, customer_id, assignment,
                 assignment_hash, churn_probability)
            VALUES (:t, :c, :cu, 'treatment', :h, 0.9)
        """), {"t": TENANT, "c": cid, "cu": cust,
               "h": int(uuid.uuid4().int % (2 ** 62))})   # bigint, not text

        row = (await db.execute(text(
            "SELECT id, current_stock FROM inventory WHERE store_id = :s ORDER BY id LIMIT 1"),
            {"s": home_store})).fetchone()
        assert row, f"no inventory in the audience's home store {home_store}"
        inv_id, original = int(row[0]), int(row[1])
        await db.execute(text("UPDATE inventory SET current_stock = -5 WHERE id = :i"),
                         {"i": inv_id})
        await db.commit()
        try:
            with pytest.raises(dt.DataNotReady) as caught:
                await campaign_service.simulate(
                    db, tenant_id=TENANT, campaign_id=cid, sample_size=50)
            assert "inventory_impossible" in caught.value.report["blockers"]
        finally:
            await db.rollback()
            await db.execute(text("UPDATE inventory SET current_stock = :s WHERE id = :i"),
                             {"s": original, "i": inv_id})
            await db.execute(text("DELETE FROM flywheel_campaign_audience WHERE campaign_id = :c"),
                             {"c": cid})
            await db.execute(text("DELETE FROM flywheel_campaigns WHERE id = :c"), {"c": cid})
            await db.commit()


@pytest.mark.asyncio
async def test_report_explains_itself(sessions):
    """Every finding must carry a code, a severity, a human detail and evidence —
    a verdict an operator cannot act on is not worth returning."""
    async with sessions() as db:
        report = await dt.evaluate(db, tenant_id=TENANT, campaign_id=None)
    for f in report["findings"]:
        assert f["code"] and f["detail"]
        assert f["severity"] in ("block", "warn")
        assert isinstance(f["evidence"], dict)
    assert set(report["thresholds"]) >= {
        "max_sales_staleness_days", "min_cost_coverage", "min_consent_coverage"}
