"""0001 baseline — the squash of init.sql + numbered migrations (E6-2).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-10

This single baseline reproduces the schema that the canonical pre-Alembic build
path (database/init.sql + database/migrations/*.sql, applied in order) produces.
It replays database/baseline/schema_baseline.sql — a faithful, GENERATED pg_dump
of that schema (see scripts/regenerate-schema-baseline.sh). So on an EMPTY
database, `alembic upgrade head` reproduces the full current schema; every further
schema change is a new revision stacked on top.

The baseline SQL is schema-only (no data): the demo CSV/user seeding stays in
db_seeder / init.sql, which are unaffected. Downgrade is intentionally unsupported
— you do not "un-baseline" a database; you restore from backup.
"""
import os
from typing import Sequence, Union

from alembic import context, op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _baseline_sql_path() -> str:
    """Locate database/baseline/schema_baseline.sql across dev/container layouts."""
    candidates = [
        "/app/database/baseline/schema_baseline.sql",
        os.path.join(os.getcwd(), "database", "baseline", "schema_baseline.sql"),
        os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "database", "baseline", "schema_baseline.sql",
        ),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise FileNotFoundError(
        "schema_baseline.sql not found — expected under database/baseline/. "
        "Run scripts/regenerate-schema-baseline.sh."
    )


def upgrade() -> None:
    with open(_baseline_sql_path(), "r", encoding="utf-8") as fh:
        sql = fh.read()

    # Run the multi-statement dump on its OWN psycopg2 connection (autocommit),
    # isolated from Alembic's version-tracking transaction. Two reasons:
    #   * the dump has literal `%` (in function bodies / RAISE messages) that
    #     SQLAlchemy's param path would misread as placeholders, and
    #   * driving a raw multi-statement script over Alembic's own connection
    #     desyncs the transaction it uses to record alembic_version.
    # A bare cursor.execute(sql) sends the script verbatim, exactly as psql does.
    import psycopg2

    url = context.config.get_main_option("sqlalchemy.url")  # postgresql+psycopg2://…
    dsn = url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()


def downgrade() -> None:
    raise NotImplementedError(
        "The baseline cannot be downgraded — restore from backup instead."
    )
