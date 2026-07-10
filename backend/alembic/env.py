"""Alembic environment (E6-2) — sync driver, config-sourced, model-aware.

The database URL comes from app settings (one source of truth, no secret in
alembic.ini). The app runtime uses asyncpg; Alembic uses the SYNC psycopg2 driver
instead, because the 0001 baseline replays a multi-statement schema dump (DDL, DO
blocks, functions) that asyncpg refuses through its prepared-statement path.
`postgresql+asyncpg://` is rewritten to `postgresql+psycopg2://` here.

`target_metadata` is the app's `Base.metadata` so `alembic check` / autogenerate
can diff the ORM models against the live schema for future incremental revisions.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- URL from app settings (never hardcoded), forced onto the sync driver ----
from app.config import get_settings  # noqa: E402

settings = get_settings()
sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", sync_url)

# --- Model metadata for autogenerate / drift --------------------------------
from app.models.sales import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
