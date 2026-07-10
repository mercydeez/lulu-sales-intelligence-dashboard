"""
Production runtime split (Phase 2), updated for the E6-5 multi-worker fix.

The invariant tightened. It used to be "the API doesn't run migrations/seed/the
generator IN PRODUCTION". It is now stronger: the API never starts a CONTINUOUS
singleton in ANY environment — the generator, demo reset, cache warmer, forecast
trainer and partition maintenance all live in the dedicated `singletons` command,
so `gunicorn --workers N` cannot run N of each. The API lifespan runs only the
one loop that is safe across processes (import_scheduler), plus the one-shot
startup DDL (seed/migrate/employee), now serialized by a Postgres advisory lock.

All I/O is patched, so no live Postgres/Redis is required.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app import main as main_module


def _prod_settings(**kw):
    base = dict(
        environment="production",
        debug=False,
        jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
        secret_key="another-strong-production-secret-key-for-the-app-layer",
        database_url="postgresql+asyncpg://u:str0ngPwd@db:5432/d",
        redis_url="redis://:p@redis:6379",
        use_rls_role=True,
        rls_database_url="postgresql+asyncpg://app_rw:str0ngAppRw@db:5432/d",
    )
    base.update(kw)
    return Settings(**base)


@asynccontextmanager
async def _noop_lock(*a, **k):
    yield


async def _drive_lifespan(settings):
    """Run the API lifespan with all I/O patched; return the call trackers."""
    with patch.object(main_module, "settings", settings), \
         patch.object(main_module, "init_db", new=AsyncMock()), \
         patch.object(main_module, "init_redis", new=AsyncMock()), \
         patch.object(main_module, "close_db", new=AsyncMock()), \
         patch.object(main_module, "close_redis", new=AsyncMock()), \
         patch.object(main_module, "run_seed", new=AsyncMock()) as run_seed, \
         patch.object(main_module, "run_migrations", new=AsyncMock()) as run_migrations, \
         patch.object(main_module, "initialize_employee_system", new=AsyncMock()) as emp, \
         patch.object(main_module, "startup_lock", new=_noop_lock), \
         patch("app.services.import_scheduler.scheduler_loop", new=lambda: AsyncMock()()), \
         patch("app.services.database.async_session"):
        async with main_module.lifespan(MagicMock()):
            pass
        return {"run_seed": run_seed, "run_migrations": run_migrations, "employee": emp}


class TestProductionLifespan:
    async def test_prod_does_not_run_migrations(self):
        c = await _drive_lifespan(_prod_settings())
        c["run_migrations"].assert_not_called()

    async def test_prod_does_not_run_seed(self):
        c = await _drive_lifespan(_prod_settings())
        c["run_seed"].assert_not_called()


class TestDevLifespan:
    async def test_dev_runs_startup_work_but_not_the_generator(self):
        dev = Settings(
            environment="development",
            jwt_secret_key="a-strong-enough-dev-secret-key-32-characters",
            secret_key="another-strong-enough-dev-secret-key-32chars",
        )
        c = await _drive_lifespan(dev)
        # Dev API still applies migrations/seed at boot (under the advisory lock)…
        c["run_migrations"].assert_called()
        c["run_seed"].assert_called()

    def test_the_api_lifespan_never_references_a_continuous_singleton(self):
        """…but it never starts one, in ANY environment. This is the load-bearing
        change: the generator etc. are not even reachable from the API lifespan."""
        import inspect
        src = inspect.getsource(main_module.lifespan)
        for forbidden in ("DataGenerator", "run_demo_reset_loop", "run_cache_warmer",
                          "run_forecast_trainer", "partition_maintenance_loop"):
            assert forbidden not in src


class TestSingletonsCommand:
    """The generator now lives HERE, not in the API lifespan."""

    async def _run_singletons_briefly(self, settings):
        """Start the singletons _main with loop bodies patched to no-ops, capture
        which loops it decided to start, then stop it."""
        from app.commands import singletons

        gen_cls = MagicMock()
        gen_cls.return_value.start = AsyncMock(side_effect=lambda: _forever())
        with patch.object(singletons, "get_settings", return_value=settings), \
             patch.object(singletons, "init_db", new=AsyncMock()), \
             patch.object(singletons, "init_redis", new=AsyncMock()), \
             patch.object(singletons, "close_db", new=AsyncMock()), \
             patch.object(singletons, "close_redis", new=AsyncMock()), \
             patch.object(singletons, "_emit_heartbeat", new=AsyncMock()), \
             patch("app.services.data_generator.DataGenerator", gen_cls), \
             patch("app.services.demo_reset.run_demo_reset_loop", new=lambda: _forever()), \
             patch("app.services.cache_warmer.run_cache_warmer", new=lambda: _forever()), \
             patch("app.services.forecast_trainer.run_forecast_trainer", new=lambda: _forever()), \
             patch("app.services.partition_maintenance.partition_maintenance_loop", new=lambda: _forever()):
            import asyncio
            task = asyncio.create_task(singletons._main())
            await asyncio.sleep(0.05)   # let it start its loops
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return gen_cls

    async def test_singletons_starts_the_generator_in_demo(self):
        demo = Settings(
            environment="development",
            jwt_secret_key="a-strong-enough-dev-secret-key-32-characters",
            secret_key="another-strong-enough-dev-secret-key-32chars",
            demo_mode=True, live_generator_enabled=True,
        )
        gen_cls = await self._run_singletons_briefly(demo)
        gen_cls.assert_called()  # the generator WAS instantiated by singletons

    async def test_singletons_does_not_start_the_generator_in_non_demo(self):
        prod = _prod_settings(demo_mode=False, live_generator_enabled=False)
        gen_cls = await self._run_singletons_briefly(prod)
        gen_cls.assert_not_called()


class TestCommandModules:
    async def test_migrate_command_invokes_runner(self):
        from app.commands import migrate
        with patch.object(migrate, "init_db", new=AsyncMock()), \
             patch.object(migrate, "close_db", new=AsyncMock()), \
             patch.object(migrate, "run_migrations", new=AsyncMock()) as rm:
            rc = await migrate._main()
        assert rc == 0
        rm.assert_awaited_once()

    async def test_seed_command_refuses_in_real_prod(self):
        from app.commands import seed
        with patch.object(seed, "get_settings", return_value=_prod_settings()):
            rc = await seed._main()
        assert rc == 2  # refused: demo/sample off

    async def test_generator_command_refuses_without_demo(self):
        from app.commands import generator
        with patch.object(generator, "get_settings", return_value=_prod_settings()):
            rc = await generator._main()
        assert rc == 2  # refused: DEMO_MODE / LIVE_GENERATOR_ENABLED off

    async def test_seed_command_runs_in_demo(self):
        from app.commands import seed
        with patch.object(seed, "get_settings",
                          return_value=_prod_settings(demo_mode=True)), \
             patch.object(seed, "init_db", new=AsyncMock()), \
             patch.object(seed, "close_db", new=AsyncMock()), \
             patch.object(seed, "run_seed", new=AsyncMock()) as rs:
            rc = await seed._main()
        assert rc == 0
        rs.assert_awaited_once()


async def _forever():
    import asyncio
    await asyncio.Event().wait()
