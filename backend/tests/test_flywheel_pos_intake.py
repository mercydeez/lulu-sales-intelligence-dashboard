"""
POS intake — the quality gate on a real retailer's feed.

The validator is pure, so the rules are tested directly without a database. The
batch behaviour that needs Postgres (staging, idempotent re-send) is exercised
against a live database and skips cleanly without one.

What these tests are really protecting: a bad feed does not announce itself. It
produces confident wrong numbers two steps later, in the holdout readout that
the whole pilot rests on.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.flywheel import pos_intake as pi

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
STORES = {1, 2, 3}
ITEMS = {10, 11}
TENANT = 1
_DSN = os.environ.get("RETENTION_TEST_DATABASE_URL",
                      "postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb")


def _row(**over):
    base = {
        "external_txn_id": f"TXN-{uuid.uuid4().hex[:8]}",
        "occurred_at": "2026-07-20T10:30:00Z",
        "loyalty_ref": "LOY-123",
        "store_id": 1, "item_id": 10, "units": 2, "amount_aed": "40.00",
    }
    base.update(over)
    return base


def check(row, index=0):
    return pi.validate_row(row, index=index, now=NOW,
                           known_stores=STORES, known_items=ITEMS)


# --- the happy path ---------------------------------------------------------

def test_a_good_row_is_accepted_and_typed():
    clean, findings = check(_row())
    assert clean is not None
    assert clean["units"] == 2
    assert clean["amount_aed"] == Decimal("40.00")   # Decimal, never float
    assert isinstance(clean["occurred_at"], datetime)
    assert clean["occurred_at"].tzinfo is not None    # never naive
    assert [f for f in findings if f["severity"] == "reject"] == []


# --- transaction identity ---------------------------------------------------

@pytest.mark.parametrize("bad", [None, "", "   "])
def test_missing_external_txn_id_is_refused(bad):
    """Without a stable source id, re-importing an export double-counts."""
    clean, findings = check(_row(external_txn_id=bad))
    assert clean is None
    assert findings[0]["code"] == "missing_external_txn_id"


def test_overlong_txn_id_is_refused():
    clean, findings = check(_row(external_txn_id="x" * 121))
    assert clean is None and findings[0]["code"] == "external_txn_id_too_long"


# --- time -------------------------------------------------------------------

def test_unparseable_timestamp_is_refused():
    clean, findings = check(_row(occurred_at="20/07/2026"))
    assert clean is None and findings[0]["code"] == "unparseable_occurred_at"


def test_future_timestamp_is_refused_beyond_skew():
    clean, _ = check(_row(occurred_at=(NOW + timedelta(days=3)).isoformat()))
    assert clean is None


def test_small_clock_skew_is_forgiven():
    """Tills drift. Refusing an hour of skew would reject good sales."""
    clean, _ = check(_row(occurred_at=(NOW + timedelta(hours=2)).isoformat()))
    assert clean is not None


def test_implausibly_old_timestamp_is_refused():
    clean, findings = check(_row(occurred_at="1998-01-01T00:00:00Z"))
    assert clean is None and findings[0]["code"] == "occurred_at_implausibly_old"


def test_naive_timestamps_are_treated_as_utc_not_rejected():
    clean, _ = check(_row(occurred_at="2026-07-20T10:30:00"))
    assert clean is not None and clean["occurred_at"].tzinfo is not None


# --- quantity and money -----------------------------------------------------

def test_zero_units_is_refused():
    clean, findings = check(_row(units=0))
    assert clean is None and findings[0]["code"] == "units_zero"


def test_negative_units_is_a_valid_return():
    clean, _ = check(_row(units=-1, amount_aed="-20.00"))
    assert clean is not None and clean["units"] == -1


def test_non_numeric_amount_is_refused():
    clean, findings = check(_row(amount_aed="AED 40"))
    assert clean is None and findings[0]["code"] == "amount_not_numeric"


def test_positive_sale_with_negative_amount_is_refused():
    clean, findings = check(_row(units=2, amount_aed="-40.00"))
    assert clean is None and findings[0]["code"] == "amount_sign_mismatch"


def test_return_with_positive_amount_is_refused():
    """The classic feed bug: returns exported as positives silently inflate revenue."""
    clean, findings = check(_row(units=-2, amount_aed="40.00"))
    assert clean is None and findings[0]["code"] == "amount_sign_mismatch"


# --- tenant scope -----------------------------------------------------------

def test_store_from_another_tenant_is_refused():
    clean, findings = check(_row(store_id=999))
    assert clean is None and findings[0]["code"] == "unknown_store"


def test_unknown_item_is_refused():
    clean, findings = check(_row(item_id=999))
    assert clean is None and findings[0]["code"] == "unknown_item"


def test_missing_store_is_a_warning_not_a_refusal():
    clean, findings = check(_row(store_id=None))
    assert clean is not None
    assert any(f["code"] == "no_store" and f["severity"] == "warn" for f in findings)


# --- PII --------------------------------------------------------------------

def test_raw_card_number_in_card_hash_is_refused():
    """A feed shipping PANs is a compliance incident; accepting one would make
    us the party that stored it."""
    clean, findings = check(_row(card_hash="4539578763621486", loyalty_ref=None))
    assert clean is None and findings[0]["code"] == "raw_card_number_refused"


def test_raw_card_number_in_loyalty_ref_is_refused():
    clean, findings = check(_row(loyalty_ref="4539578763621486"))
    assert clean is None and findings[0]["code"] == "raw_card_number_refused"


def test_a_numeric_loyalty_id_is_not_mistaken_for_a_card():
    """Loyalty ids are often numeric. Only a Luhn-valid 13-19 digit run is a PAN,
    otherwise the guard would reject legitimate members."""
    assert pi.looks_like_card_number("1234567890123") is False
    clean, _ = check(_row(loyalty_ref="1234567890123"))
    assert clean is not None


def test_luhn_recognises_a_real_card_shape():
    assert pi.looks_like_card_number("4539578763621486") is True
    assert pi.looks_like_card_number("4539 5787 6362 1486") is True


def test_anonymous_sale_is_accepted_with_a_warning():
    """A cash sale by an anonymous shopper is real data — it just can never
    resolve to a customer."""
    clean, findings = check(_row(loyalty_ref=None, card_hash=None))
    assert clean is not None
    assert any(f["code"] == "anonymous_transaction" for f in findings)


# --- live batch behaviour ---------------------------------------------------

@pytest.fixture
async def sessions():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    engine = create_async_engine(_DSN, pool_size=5, max_overflow=5)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
            n = (await c.execute(text(
                "SELECT count(*) FROM pg_tables WHERE tablename='flywheel_pos_staging'"))).scalar()
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
async def test_one_bad_row_does_not_reject_the_batch(sessions):
    """The central promise: a real first export has some bad rows, and the good
    ones must still land."""
    async with sessions() as db:
        store = (await db.execute(text(
            "SELECT id FROM stores WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar()
        item = (await db.execute(text(
            "SELECT id FROM items WHERE tenant_id = :t LIMIT 1"), {"t": TENANT})).scalar()
        tag = uuid.uuid4().hex[:8]
        rows = [
            {"external_txn_id": f"OK-{tag}-1", "occurred_at": "2026-07-20T10:00:00Z",
             "loyalty_ref": "LOY-1", "store_id": store, "item_id": item,
             "units": 1, "amount_aed": 10},
            {"external_txn_id": f"BAD-{tag}", "occurred_at": "not-a-date",
             "store_id": store, "item_id": item, "units": 1, "amount_aed": 10},
            {"external_txn_id": f"OK-{tag}-2", "occurred_at": "2026-07-20T11:00:00Z",
             "loyalty_ref": "LOY-2", "store_id": store, "item_id": item,
             "units": 1, "amount_aed": 12},
        ]
        try:
            out = await pos_intake_or_skip(db, rows)
            assert out["staged"] == 2
            assert out["rejected"] == 1
            assert "unparseable_occurred_at" in out["reject_codes"]

            # Re-sending the SAME export must not double-land anything.
            again = await pos_intake_or_skip(db, rows)
            assert again["staged"] == 0
            assert again["duplicates"] == 2
        finally:
            await db.rollback()


async def pos_intake_or_skip(db, rows):
    return await pi.intake_batch(db, tenant_id=TENANT, rows=rows)


@pytest.mark.asyncio
async def test_batch_size_is_capped(sessions):
    async with sessions() as db:
        with pytest.raises(ValueError, match="exceeds"):
            await pi.intake_batch(db, tenant_id=TENANT,
                                  rows=[_row() for _ in range(pi.MAX_BATCH + 1)])
