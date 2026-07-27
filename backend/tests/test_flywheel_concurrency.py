"""
Transaction-safety gate for the Flywheel redemption path (board pack v3 p.13/14).

`decisioning.redeem()` documents in a comment that "FOR UPDATE here is what makes
concurrent redemptions safe" — but nothing in the suite ever ran two redemptions
at once to prove it. These are the invariants that cannot be shown with a mocked
session: they need real, simultaneous Postgres transactions, each on its own
AsyncSession, so the row locks and the campaign cap are genuinely contended.

Ported here when the retention module was merged into Flywheel; the same four
invariants previously guarded the retention redemption path.

Gate assertions:
  1. Concurrent redemptions never drive inventory negative.
  2. Concurrent spend never exceeds the campaign's approved discount cap.
  3. A duplicate idempotency key moves stock and money exactly once.
  4. The budget ledger reconciles with what was actually spent.

conftest.py pins DATABASE_URL to a throwaway `testdb`, so this module builds its
OWN engine against a real Postgres, created per-test (pytest-asyncio uses a fresh
event loop per test and asyncpg connections cannot cross loops). Skips cleanly
when no live database is reachable, so database-free CI stays green.

Run: docker exec sales_backend python -m pytest tests/test_flywheel_concurrency.py
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

PRICE = Decimal("20.00")
DISCOUNT_PCT = Decimal("10")
# 10% of a 20.00 unit = 2.00 discount per redemption.
PER_REDEMPTION_DISCOUNT = Decimal("2.00")


@pytest.fixture
async def sessions():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    engine = create_async_engine(_DSN, pool_size=20, max_overflow=10)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
            n = (await c.execute(text(
                "SELECT count(*) FROM pg_tables WHERE tablename = 'flywheel_offers'"))).scalar()
        if not n:
            await engine.dispose()
            pytest.skip("flywheel tables absent — run migrations 075+ first")
    except Exception as e:
        await engine.dispose()
        pytest.skip(f"live Postgres not reachable at {_DSN} ({e}) — gate not exercised")
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


class _Harness:
    """A disposable LIVE flywheel campaign with N issued offers, exact stock and
    an exact discount cap. Torn down afterwards."""

    def __init__(self, Session, stock: int, cap: Decimal, offers: int):
        self.S = Session
        self.stock, self.cap, self.n = stock, cap, offers
        self.campaign_id = None
        self.codes = []
        self.store_id = self.item_id = None
        self._prev_stock = None
        self._customer_ids = []

    async def setup(self):
        async with self.S() as db:
            row = (await db.execute(text("""
                SELECT inv.store_id, inv.item_id, inv.current_stock
                FROM inventory inv
                JOIN items i ON i.id = inv.item_id AND i.tenant_id = :t
                WHERE inv.current_stock > 0 AND i.unit_price_aed > 0
                ORDER BY inv.id LIMIT 1
            """), {"t": TENANT})).mappings().fetchone()
            assert row, "no seeded inventory to contend on"
            self.store_id, self.item_id = row["store_id"], row["item_id"]
            self._prev_stock = row["current_stock"]

            # Pin price so the discount per redemption is exactly 2.00.
            await db.execute(text("UPDATE items SET unit_price_aed = :p WHERE id = :i"),
                             {"p": PRICE, "i": self.item_id})
            await db.execute(text("""
                UPDATE inventory SET current_stock = :s, reserved_stock = 0
                WHERE store_id = :st AND item_id = :i
            """), {"s": self.stock, "st": self.store_id, "i": self.item_id})

            # activated_at is required by flywheel_campaign_active_has_timestamp
            # for any ACTIVE/COMPLETED/MEASURED campaign.
            self.campaign_id = (await db.execute(text("""
                INSERT INTO flywheel_campaigns
                    (tenant_id, name, objective, status, starts_on, ends_on, channel,
                     max_discount_pct, min_margin_pct, discount_budget_aed,
                     safety_stock_pct, policy_version, activated_at)
                VALUES (:t, :n, 'retain_at_risk', 'ACTIVE', :s, :e, 'email',
                        50, 0, :cap, 0, 'test', now())
                RETURNING id
            """), {"t": TENANT, "n": f"CONCURRENCY {uuid.uuid4().hex[:8]}",
                   "s": date.today(), "e": date.today() + timedelta(days=7),
                   "cap": self.cap})).scalar()

            expires = datetime.now(timezone.utc) + timedelta(days=3)
            for k in range(self.n):
                ref = f"conc-{uuid.uuid4().hex[:12]}"
                cust = (await db.execute(text("""
                    INSERT INTO flywheel_customers
                        (tenant_id, external_ref, display_name, home_store_id,
                         archetype, enrolled_on)
                    VALUES (:t, :ref, :name, :s, 'loyal_regular', CURRENT_DATE)
                    RETURNING id
                """), {"t": TENANT, "ref": ref, "name": f"Concurrency {ref[-6:]}",
                       "s": self.store_id})).scalar()
                self._customer_ids.append(cust)
                code = f"CONC-{uuid.uuid4().hex[:10].upper()}"
                await db.execute(text("""
                    INSERT INTO flywheel_offers
                        (tenant_id, campaign_id, customer_id, offer_code, action_type,
                         store_id, item_id, discount_pct, reserved_aed, status, expires_at)
                    VALUES (:t, :c, :cu, :code, 'PERCENT_DISCOUNT', :s, :i, :d,
                            :res, 'issued', :ex)
                """), {"t": TENANT, "c": self.campaign_id, "cu": cust, "code": code,
                       "s": self.store_id, "i": self.item_id, "d": DISCOUNT_PCT,
                       "res": PER_REDEMPTION_DISCOUNT, "ex": expires})
                self.codes.append(code)
            await db.commit()

    async def teardown(self):
        async with self.S() as db:
            await db.execute(text(
                "DELETE FROM flywheel_budget_ledger WHERE campaign_id = :c"),
                {"c": self.campaign_id})
            await db.execute(text(
                "DELETE FROM flywheel_redemptions WHERE tenant_id = :t AND offer_id IN "
                "(SELECT id FROM flywheel_offers WHERE campaign_id = :c)"),
                {"t": TENANT, "c": self.campaign_id})
            await db.execute(text("DELETE FROM flywheel_offers WHERE campaign_id = :c"),
                             {"c": self.campaign_id})
            await db.execute(text("DELETE FROM flywheel_campaigns WHERE id = :c"),
                             {"c": self.campaign_id})
            if self._customer_ids:
                await db.execute(text("DELETE FROM flywheel_customers WHERE id = ANY(:ids)"),
                                 {"ids": self._customer_ids})
            await db.execute(text("""
                UPDATE inventory SET current_stock = :s
                WHERE store_id = :st AND item_id = :i
            """), {"s": self._prev_stock, "st": self.store_id, "i": self.item_id})
            await db.commit()

    async def state(self):
        async with self.S() as db:
            stock = (await db.execute(text(
                "SELECT current_stock FROM inventory WHERE store_id = :st AND item_id = :i"),
                {"st": self.store_id, "i": self.item_id})).scalar()
            redeemed = (await db.execute(text(
                "SELECT COUNT(*) FROM flywheel_offers WHERE campaign_id = :c AND status = 'redeemed'"),
                {"c": self.campaign_id})).scalar()
            spent = (await db.execute(text("""
                SELECT COALESCE(SUM(discount_aed), 0) FROM flywheel_redemptions r
                JOIN flywheel_offers o ON o.id = r.offer_id
                WHERE o.campaign_id = :c
            """), {"c": self.campaign_id})).scalar()
            ledger = (await db.execute(text("""
                SELECT COALESCE(SUM(amount_aed), 0) FROM flywheel_budget_ledger
                WHERE tenant_id = :t AND campaign_id = :c AND entry_type = 'SPENT'
            """), {"t": TENANT, "c": self.campaign_id})).scalar()
            return {"stock": int(stock), "redeemed": int(redeemed),
                    "spent": Decimal(str(spent)), "ledger": Decimal(str(ledger))}


async def _redeem_one(Session, code: str, key: str):
    """One redemption in its OWN session/transaction. redeem() deliberately does
    not commit (the route co-commits the outbox), so the caller commits."""
    from app.services.flywheel import decisioning
    async with Session() as db:
        try:
            out = await decisioning.redeem(
                db, tenant_id=TENANT, offer_code=code, units=1,
                idempotency_key=key, actor_user_id=None)
            await db.commit()
            return out
        except Exception as e:
            await db.rollback()
            return {"error": str(e)}


async def test_concurrent_redemptions_never_go_negative(sessions):
    """10 concurrent redemptions against 4 units: exactly 4 apply, stock lands
    on 0 and never below."""
    h = _Harness(sessions, stock=4, cap=Decimal("10000"), offers=10)
    await h.setup()
    try:
        results = await asyncio.gather(*[
            _redeem_one(sessions, c, f"stock-{uuid.uuid4().hex}") for c in h.codes])
        st = await h.state()
        ok = [r for r in results if "error" not in r]
        assert st["stock"] >= 0, f"NEGATIVE STOCK: {st['stock']}"
        assert st["stock"] == 0, f"expected stock 0, got {st['stock']}"
        assert len(ok) == 4, f"expected 4 redemptions, got {len(ok)}"
        assert st["redeemed"] == 4
    finally:
        await h.teardown()


async def test_concurrent_spend_never_exceeds_campaign_cap(sessions):
    """The campaign cap fits exactly 3 redemptions (2.00 each); 10 fire at once.

    Guards the hard cap that decisioning.redeem() enforces inside the
    transaction — the control that stops a campaign outspending its own ceiling
    however much headroom the tenant pool has.
    """
    h = _Harness(sessions, stock=100, cap=Decimal("6.00"), offers=10)
    await h.setup()
    try:
        results = await asyncio.gather(*[
            _redeem_one(sessions, c, f"cap-{uuid.uuid4().hex}") for c in h.codes])
        st = await h.state()
        ok = [r for r in results if "error" not in r]
        assert st["spent"] <= h.cap, f"OVERSPEND: {st['spent']} > cap {h.cap}"
        assert len(ok) == 3, f"expected 3 redemptions within cap, got {len(ok)}"
        assert st["spent"] == Decimal("6.00")
    finally:
        await h.teardown()


async def test_duplicate_idempotency_key_applies_once(sessions):
    """The same key fired 8 times concurrently decrements stock once and
    charges once; every other caller gets the replay of the original."""
    h = _Harness(sessions, stock=50, cap=Decimal("10000"), offers=1)
    await h.setup()
    try:
        key = f"idem-{uuid.uuid4().hex}"
        before = await h.state()
        results = await asyncio.gather(*[
            _redeem_one(sessions, h.codes[0], key) for _ in range(8)])
        st = await h.state()
        applied = [r for r in results if r.get("applied")]
        assert applied, "no redemption applied"
        assert st["redeemed"] == 1
        assert before["stock"] - st["stock"] == 1, "stock moved more than once"
        assert st["spent"] == PER_REDEMPTION_DISCOUNT
    finally:
        await h.teardown()


async def test_budget_ledger_reconciles_with_redeemed_spend(sessions):
    """Ledger invariant: SPENT entries reconcile with the redemption rows.

    Skips when no active DISCOUNT budget exists for the tenant — the ledger is
    only written through budget_service.spend(), and fabricating a tenant-wide
    budget here would test the fixture rather than the code.
    """
    async with sessions() as db:
        has_budget = (await db.execute(text("""
            SELECT COUNT(*) FROM flywheel_budgets
            WHERE tenant_id = :t AND budget_type = 'DISCOUNT'
              AND period_start <= CURRENT_DATE AND period_end > CURRENT_DATE
        """), {"t": TENANT})).scalar()
    if not has_budget:
        pytest.skip("no active DISCOUNT budget for tenant — ledger path not exercised")

    h = _Harness(sessions, stock=100, cap=Decimal("10000"), offers=6)
    await h.setup()
    try:
        await asyncio.gather(*[
            _redeem_one(sessions, c, f"ledger-{uuid.uuid4().hex}") for c in h.codes])
        st = await h.state()
        # Guard against a vacuous pass: if nothing redeemed, 0 == 0 would "pass".
        assert st["redeemed"] > 0, "no redemption applied — nothing to reconcile"
        assert st["spent"] == PER_REDEMPTION_DISCOUNT * st["redeemed"]
        assert st["ledger"] == st["spent"], \
            f"LEDGER DRIFT: ledger {st['ledger']} != redeemed spend {st['spent']}"
    finally:
        await h.teardown()
