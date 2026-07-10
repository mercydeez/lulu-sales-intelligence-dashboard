"""E6-2 guards: the Alembic baseline stays importable and the squash artifact
stays present. Full apply/drift is exercised by the CI `migrations` job against a
real Postgres; these are cheap, DB-free structural checks.
"""
import importlib.util
import os

_HERE = os.path.dirname(__file__)
_BACKEND = os.path.dirname(_HERE)
_REPO = os.path.dirname(_BACKEND)


def test_schema_baseline_file_exists_and_is_substantial():
    path = os.path.join(_REPO, "database", "baseline", "schema_baseline.sql")
    assert os.path.isfile(path), "the squash baseline must be committed"
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    # It is a real schema dump, not a stub.
    assert "CREATE TABLE" in sql
    assert sql.count("CREATE TABLE") > 50
    # Schema-only: no bulk data inserts leaked into the baseline.
    assert "COPY public." not in sql


def test_baseline_revision_is_well_formed():
    path = os.path.join(_BACKEND, "alembic", "versions", "0001_baseline_squash.py")
    spec = importlib.util.spec_from_file_location("baseline_rev", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0001_baseline"
    assert mod.down_revision is None  # it is the root
    assert callable(mod.upgrade)


def test_alembic_ini_hardcodes_no_secret():
    path = os.path.join(_BACKEND, "alembic.ini")
    with open(path, "r", encoding="utf-8") as fh:
        ini = fh.read()
    # The URL is sourced from app settings in env.py, never pinned in the ini.
    assert "sqlalchemy.url = postgresql" not in ini
    assert "salespass" not in ini
