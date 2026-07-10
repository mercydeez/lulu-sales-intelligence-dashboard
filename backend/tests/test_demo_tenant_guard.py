"""E0-8: synthetic sales can never touch a real tenant.

The guarantee has three layers (config refuses, generator refuses, Postgres
rejects). These tests cover the two that live in Python; migration 057's trigger
is exercised by the `migrations` CI job against a real database.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.data_generator import DataGenerator, DemoScopeError
from app.services.demo_reset import (
    DemoResetRefused,
    _assert_is_demo_tenant,
    seconds_until_next_reset,
)


DEMO_TENANT = 1
REAL_TENANT = 7


def _scoped_generator(store_ids=(1, 2, 3), item_ids=(10, 11), tenant_id=DEMO_TENANT):
    """A generator with its tenant scope already loaded (no DB needed)."""
    gen = DataGenerator(tenant_id=tenant_id)
    gen.store_ids = list(store_ids)
    gen.item_ids = list(item_ids)
    return gen


# ---------------------------------------------------------------------------
# The generator stamps every row it writes
# ---------------------------------------------------------------------------

def test_written_row_carries_demo_tenant_and_synthetic_flag():
    gen = _scoped_generator()
    row = gen._new_stream_row(store_id=2, item_id=11, sales_value=42)

    assert row.tenant_id == DEMO_TENANT
    assert row.is_synthetic is True
    assert row.sales == 42


def test_row_for_a_real_tenants_store_is_refused():
    """Store 99 belongs to nobody in scope — the generator must not write it."""
    gen = _scoped_generator(store_ids=(1, 2, 3))

    with pytest.raises(DemoScopeError, match="outside demo tenant"):
        gen._new_stream_row(store_id=99, item_id=11, sales_value=5)


def test_row_for_an_out_of_scope_item_is_refused():
    gen = _scoped_generator(item_ids=(10, 11))

    with pytest.raises(DemoScopeError, match="outside demo tenant"):
        gen._new_stream_row(store_id=1, item_id=500, sales_value=5)


# ---------------------------------------------------------------------------
# The generator only ever draws ids it loaded from the demo tenant
# ---------------------------------------------------------------------------

def test_pick_store_item_never_leaves_the_loaded_scope():
    gen = _scoped_generator(store_ids=(4, 5), item_ids=(20, 21))

    for _ in range(200):
        store_id, item_id = gen._pick_store_item()
        assert store_id in (4, 5)
        assert item_id in (20, 21)


def test_pick_store_item_before_scope_load_is_fatal():
    """The old code fell back to random.randint(1, 10). It must fail loudly instead."""
    gen = DataGenerator(tenant_id=DEMO_TENANT)

    with pytest.raises(DemoScopeError, match="scope not loaded"):
        gen._pick_store_item()


# ---------------------------------------------------------------------------
# Refusals: empty scope, and running outside demo mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_demo_scope_refuses_rather_than_guessing_ids():
    gen = DataGenerator(tenant_id=DEMO_TENANT)

    async def _empty_scope():
        gen.store_ids, gen.item_ids = [], []
        raise DemoScopeError("demo tenant 1 owns 0 stores / 0 items")

    with patch.object(gen, "_load_tenant_scope", side_effect=_empty_scope):
        with patch("app.services.data_generator.settings") as s:
            s.demo_mode = True
            s.live_generator_enabled = True
            with pytest.raises(DemoScopeError):
                await gen.start()

    assert gen.is_running is False


@pytest.mark.asyncio
async def test_generator_refuses_to_start_outside_demo_mode():
    gen = _scoped_generator()

    with patch("app.services.data_generator.settings") as s:
        s.demo_mode = False
        s.live_generator_enabled = True
        with pytest.raises(DemoScopeError, match="requires DEMO_MODE"):
            await gen.start()

    assert gen.is_running is False


# ---------------------------------------------------------------------------
# The reset only ever deletes from the demo tenant
# ---------------------------------------------------------------------------

def _session_returning(row):
    """AsyncMock session whose execute() resolves to a sync SQLAlchemy-style Result."""
    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = row
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_reset_refuses_a_tenant_that_is_not_slugged_demo():
    session = _session_returning(("acme-hypermarket",))

    with pytest.raises(DemoResetRefused, match="not 'demo'"):
        await _assert_is_demo_tenant(session, REAL_TENANT)


@pytest.mark.asyncio
async def test_reset_refuses_a_missing_tenant():
    session = _session_returning(None)

    with pytest.raises(DemoResetRefused, match="does not exist"):
        await _assert_is_demo_tenant(session, 999)


@pytest.mark.asyncio
async def test_reset_accepts_the_demo_tenant():
    session = _session_returning(("demo",))

    await _assert_is_demo_tenant(session, DEMO_TENANT)  # does not raise


# ---------------------------------------------------------------------------
# The other synthetic writer: POST /stream/generate-returns
#
# It is reachable by any authenticated user and used to select stores with an
# unfiltered `select(Store)`, so a user of one tenant could fabricate returns on
# another tenant's stores. It must now refuse outside demo mode.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_returns_is_refused_outside_demo_mode():
    from fastapi import HTTPException

    from app.routes import stream

    fake_settings = MagicMock(demo_mode=False, live_generator_enabled=True, demo_tenant_id=1)

    # generate_returns does `from app.config import get_settings` at call time,
    # so the patch has to land on app.config, not on the stream module.
    with patch("app.config.get_settings", return_value=fake_settings):
        with pytest.raises(HTTPException) as exc:
            await stream.generate_returns(count=50, db=AsyncMock(), current_user={"id": 1})

    assert exc.value.status_code == 403
    assert "demo mode" in exc.value.detail


def test_generate_returns_scopes_stores_and_items_to_the_demo_tenant():
    """Guard against a regression to the unfiltered `select(Store)`."""
    import inspect

    from app.routes import stream

    src = inspect.getsource(stream.generate_returns)
    assert "Store.tenant_id == demo_tenant" in src
    assert "Item.tenant_id == demo_tenant" in src
    assert "is_synthetic=True" in src


# ---------------------------------------------------------------------------
# Nightly scheduling arithmetic
# ---------------------------------------------------------------------------

def test_next_reset_is_later_today_when_the_hour_has_not_passed():
    now = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
    assert seconds_until_next_reset(now, hour_utc=22) == 13 * 3600


def test_next_reset_rolls_to_tomorrow_once_the_hour_has_passed():
    now = datetime(2026, 7, 10, 23, 0, tzinfo=timezone.utc)
    assert seconds_until_next_reset(now, hour_utc=22) == 23 * 3600
