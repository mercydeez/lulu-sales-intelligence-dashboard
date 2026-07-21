"""
Phase 0 GATE — transaction safety (board pack v3, p.13/p.14).

These are the invariants that cannot be proven with a mocked session: they need
real concurrent Postgres transactions. Each concurrent actor gets its OWN
AsyncSession so the row locks and guarded UPDATEs are genuinely exercised.

Gate assertions:
  1. Concurrent redemptions never drive inventory negative.
  2. Concurrent spending never exceeds the approved discount budget.
  3. A duplicate idempotency key moves stock and money exactly once.
  4. The budget ledger reconciles with campaign.budget_spent_aed (no drift).

conftest.py forces DATABASE_URL to a throwaway `testdb`, so this module builds
its OWN engine against a real Postgres. The engine is created per-test (inside
that test's event loop) because pytest-asyncio uses a fresh loop per test and
asyncpg connections cannot cross loops. Skips cleanly when no live Postgres is
reachable, so mocked suites and CI without a database stay green.

Run:  docker exec sales_backend python -m pytest tests/test_retention_concurrency.py
Override the DSN with RETENTION_TEST_DATABASE_URL when running outside compose.
"""
import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TENANT = 1
_DEFAULT_DSN = "postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb"
_DSN = os.environ.get("RETENTION_TEST_DATABASE_URL", _DEFAULT_DSN)


@pytest.fixture
async def sessions():
    """A sessionmaker on a live Postgres, created and disposed inside this
    test's own event loop."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    engine = create_async_engine(_DSN, pool_size=20, max_overflow=10)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception as e:
        await engine.dispose()
        pytest.skip(f"live Postgres not reachable at {_DSN} ({e}) — gate not exercised")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


class _Harness:
    """A disposable ACTIVE campaign with N issued offers, exact stock and exact
    budget, torn down afterwards."""

    def __init__(self, Session, stock: int, budget: Decimal, offers: int,
                 price=Decimal("20.00"), cost=Decimal("10.00"), discount=Decimal("10")):
        self.S = Session
        self.stock, self.budget, self.n = stock, budget, offers
        self.price, self.cost, self.discount = price, cost, discount
        self.campaign_id = None
        self.offer_ids = []
        self.store_id = self.item_id = None
        self._prev_stock = None

    async def setup(self):
        async with self.S() as db:
            row = (await db.execute(text("""
                SELECT inv.store_id, inv.item_id, inv.current_stock
                FROM inventory inv JOIN items i ON i.id = inv.item_id AND i.tenant_id = :t
                WHERE inv.current_stock > 0 ORDER BY inv.id LIMIT 1
            """), {"t": TENANT})).mappings().fetchone()
            assert row, "no seeded inventory to contend on"
            self.store_id, self.item_id = row["store_id"], row["item_id"]
            self._prev_stock = row["current_stock"]

            # Pin inventory to the exact contended quantity.
            await db.execute(text("""
                UPDATE inventory SET current_stock = :s, reserved_stock = 0
                WHERE store_id = :st AND item_id = :i
            """), {"s": self.stock, "st": self.store_id, "i": self.item_id})

            self.campaign_id = (await db.execute(text("""
                INSERT INTO retention_campaigns
                    (tenant_id, name, store_id, item_id, starts_on, ends_on,
                     discount_budget_aed, max_discount_pct, min_margin_pct,
                     control_pct, churn_threshold, safety_stock_units, status)
                VALUES (:t, :n, :st, :i, :s, :e, :b, 50, 0, 0, 0, 0, 'active')
                RETURNING id
            """), {"t": TENANT, "n": f"CONCURRENCY {uuid.uuid4().hex[:8]}",
                   "st": self.store_id, "i": self.item_id, "s": date.today(),
                   "e": date.today() + timedelta(days=7), "b": self.budget})).scalar()

            custs = [r[0] for r in (await db.execute(text("""
                SELECT id FROM customers WHERE tenant_id = :t ORDER BY id LIMIT :n
            """), {"t": TENANT, "n": self.n})).fetchall()]
            assert len(custs) >= self.n, "not enough seeded customers"
            expires = datetime.now(timezone.utc) + timedelta(days=3)
            for cu in custs:
                self.offer_ids.append((await db.execute(text("""
                    INSERT INTO campaign_offers
                        (tenant_id, campaign_id, customer_id, store_id, cohort,
                         churn_score, response_prob, action, item_id, discount_pct,
                         unit_price_aed, unit_cost_aed, status, expires_at)
                    VALUES (:t, :c, :cu, :st, 'treatment', 0.9, 0.5,
                            'PERCENT_DISCOUNT', :i, :d, :p, :co, 'issued', :ex)
                    RETURNING id
                """), {"t": TENANT, "c": self.campaign_id, "cu": cu, "st": self.store_id,
                       "i": self.item_id, "d": self.discount, "p": self.price,
                       "co": self.cost, "ex": expires})).scalar())
            await db.commit()

    async def teardown(self):
        async with self.S() as db:
            await db.execute(text("DELETE FROM retention_campaigns WHERE id = :c"),
                             {"c": self.campaign_id})
            await db.execute(text("""
                UPDATE inventory SET current_stock = :s
                WHERE store_id = :st AND item_id = :i
            """), {"s": self._prev_stock, "st": self.store_id, "i": self.item_id})
            await db.commit()

    async def state(self):
        async with self.S() as db:
            stock = (await db.execute(text("""
                SELECT current_stock FROM inventory WHERE store_id = :st AND item_id = :i
            """), {"st": self.store_id, "i": self.item_id})).scalar()
            camp = (await db.execute(text("""
                SELECT budget_spent_aed, discount_budget_aed, status
                FROM retention_campaigns WHERE id = :c
            """), {"c": self.campaign_id})).mappings().fetchone()
            ledger = (await db.execute(text("""
                SELECT COALESCE(SUM(amount_aed), 0) FROM retention_budget_ledger
                WHERE campaign_id = :c AND entry_type = 'spend'
            """), {"c": self.campaign_id})).scalar()
            redeemed = (await db.execute(text("""
                SELECT COUNT(*) FROM campaign_offers
                WHERE campaign_id = :c AND status = 'redeemed'
            """), {"c": self.campaign_id})).scalar()
            return {"stock": stock, "spent": Decimal(str(camp["budget_spent_aed"])),
                    "budget": Decimal(str(camp["discount_budget_aed"])),
                    "status": camp["status"], "ledger": Decimal(str(ledger)),
                    "redeemed": redeemed}


async def _redeem_one(Session, offer_id: int, key: str):
    """One redemption in its OWN session/transaction."""
    from app.services import retention_service as ret
    async with Session() as db:
        try:
            return await ret.redeem(db, TENANT, offer_id, key, actor=None)
        except Exception as e:
            return {"error": str(e)}


async def test_concurrent_redemptions_never_go_negative(sessions):
    """10 concurrent redemptions against 4 units: exactly 4 succeed, stock
    lands on 0 — never below."""
    h = _Harness(sessions, stock=4, budget=Decimal("10000"), offers=10)
    await h.setup()
    try:
        results = await asyncio.gather(*[
            _redeem_one(sessions, oid, f"conc-stock-{uuid.uuid4().hex}")
            for oid in h.offer_ids])
        st = await h.state()
        ok = [r for r in results if "error" not in r]
        assert st["stock"] >= 0, f"NEGATIVE STOCK: {st['stock']}"
        assert st["stock"] == 0, f"expected stock 0, got {st['stock']}"
        assert len(ok) == 4, f"expected 4 successful redemptions, got {len(ok)}"
        assert st["redeemed"] == 4
    finally:
        await h.teardown()


async def test_concurrent_spending_never_exceeds_budget(sessions):
    """Budget fits exactly 3 redemptions (2.00 each); 10 fire concurrently."""
    h = _Harness(sessions, stock=100, budget=Decimal("6.00"), offers=10)
    await h.setup()
    try:
        results = await asyncio.gather(*[
            _redeem_one(sessions, oid, f"conc-budget-{uuid.uuid4().hex}")
            for oid in h.offer_ids])
        st = await h.state()
        ok = [r for r in results if "error" not in r]
        assert st["spent"] <= st["budget"], f"OVERSPEND: {st['spent']} > {st['budget']}"
        assert len(ok) == 3, f"expected 3 redemptions within budget, got {len(ok)}"
        assert st["spent"] == Decimal("6.00")
        # Budget exhaustion must trip the auto-pause guardrail.
        assert st["status"] == "paused"
    finally:
        await h.teardown()


async def test_duplicate_idempotency_key_moves_money_and_stock_once(sessions):
    """The same key fired 8 times concurrently spends once, decrements once."""
    h = _Harness(sessions, stock=50, budget=Decimal("10000"), offers=1)
    await h.setup()
    try:
        key = f"idem-{uuid.uuid4().hex}"
        before = await h.state()
        results = await asyncio.gather(*[
            _redeem_one(sessions, h.offer_ids[0], key) for _ in range(8)])
        st = await h.state()
        assert [r for r in results if "error" not in r], "no redemption succeeded"
        assert st["redeemed"] == 1
        assert before["stock"] - st["stock"] == 1, "stock moved more than once"
        assert st["spent"] == Decimal("2.00"), f"spent {st['spent']}, expected 2.00 once"
    finally:
        await h.teardown()


async def test_budget_ledger_reconciles_with_campaign_spend(sessions):
    """Ledger invariant: SUM(spend entries) == campaign.budget_spent_aed."""
    h = _Harness(sessions, stock=100, budget=Decimal("10000"), offers=6)
    await h.setup()
    try:
        await asyncio.gather(*[
            _redeem_one(sessions, oid, f"ledger-{uuid.uuid4().hex}")
            for oid in h.offer_ids])
        st = await h.state()
        assert st["ledger"] == st["spent"], \
            f"LEDGER DRIFT: ledger {st['ledger']} != campaign spent {st['spent']}"
        assert st["spent"] == Decimal("2.00") * st["redeemed"]
    finally:
        await h.teardown()
