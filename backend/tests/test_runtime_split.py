"""
Phase 2 — production runtime split.

The API process must NOT run migrations / seed / the synthetic generator from its
lifespan in production. The dedicated command modules own that work. These tests
patch all I/O so no live Postgres/Redis is required.
"""
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


async def _drive_lifespan(settings):
    """Run the lifespan with all I/O patched; return the call trackers."""
    with patch.object(main_module, "settings", settings), \
         patch.object(main_module, "init_db", new=AsyncMock()), \
         patch.object(main_module, "init_redis", new=AsyncMock()), \
         patch.object(main_module, "close_db", new=AsyncMock()), \
         patch.object(main_module, "close_redis", new=AsyncMock()), \
         patch.object(main_module, "run_seed", new=AsyncMock()) as run_seed, \
         patch.object(main_module, "run_migrations", new=AsyncMock()) as run_migrations, \
         patch.object(main_module, "initialize_employee_system", new=AsyncMock()) as emp, \
         patch.object(main_module, "run_cache_warmer", new=AsyncMock()) as warm, \
         patch.object(main_module, "run_forecast_trainer", new=AsyncMock()) as train, \
         patch.object(main_module, "DataGenerator") as gen_cls, \
         patch("app.services.database.async_session"):
        gen_cls.return_value.start = AsyncMock()
        async with main_module.lifespan(MagicMock()):
            pass
        return {
            "run_seed": run_seed,
            "run_migrations": run_migrations,
            "employee": emp,
            "cache_warmer": warm,
            "forecast_trainer": train,
            "generator_cls": gen_cls,
        }


class TestProductionLifespan:
    async def test_prod_does_not_run_migrations(self):
        c = await _drive_lifespan(_prod_settings())
        c["run_migrations"].assert_not_called()

    async def test_prod_does_not_run_seed(self):
        c = await _drive_lifespan(_prod_settings())
        c["run_seed"].assert_not_called()

    async def test_prod_does_not_start_generator(self):
        c = await _drive_lifespan(_prod_settings())
        c["generator_cls"].assert_not_called()


class TestDevLifespan:
    async def test_dev_runs_startup_work(self):
        dev = Settings(
            environment="development",
            jwt_secret_key="a-strong-enough-dev-secret-key-32-characters",
            secret_key="another-strong-enough-dev-secret-key-32chars",
        )
        c = await _drive_lifespan(dev)
        c["run_migrations"].assert_called()
        c["run_seed"].assert_called()
        c["generator_cls"].assert_called()  # DataGenerator() instantiated


class TestDemoProdLifespan:
    async def test_demo_prod_starts_generator(self):
        c = await _drive_lifespan(_prod_settings(
            demo_mode=True, live_generator_enabled=True,
            run_migrations_on_startup=True, run_seed_on_startup=True,
        ))
        c["generator_cls"].assert_called()
        c["run_migrations"].assert_called()


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
