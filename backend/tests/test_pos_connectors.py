"""E2-1 — POS connector framework + reference (`mock`) adapter, honestly gated.

The lifecycle is built (connect → nightly sync → basket grain), but the properties
these tests defend are the honest ones:

  1. A real vendor is REFUSED until it is in IMPLEMENTED_VENDORS *and* its OAuth
     credentials are present — recognising a vendor is not integrating it. Credentials
     are read by ENV-VAR name, never from the DB.
  2. The connector NEVER writes sales_fact_view (ADR-010): revenue stays sourced from
     the daily grain; the basket grain is parallel. Ingestion is idempotent, so a
     replayed window duplicates nothing.
  3. The `mock` vendor tags its rows is_synthetic and confines them to the demo tenant.

The live round-trip (connect mock → sync → 6 receipts / 18 lines land → re-sync
ingests 0 → sales_fact_view unchanged) is verified against the running stack in the
commit; these are the cheap DB-free structural + behavioural guards.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import pos_connectors as pos


def _find_migration(name: str) -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("070_krishna_pos_connectors.sql")


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# Vendor gating.
# --------------------------------------------------------------------------

def test_only_mock_is_implemented():
    assert pos.IMPLEMENTED_VENDORS == {pos.MOCK_VENDOR}
    assert pos.POS_VENDORS == {"square", "foodics", "omnivore", "lightspeed"}


def test_mock_is_always_available():
    assert pos.is_vendor_available("mock") is True


def test_real_vendor_refused_even_with_credentials(monkeypatch):
    monkeypatch.setenv("FOODICS_CLIENT_ID", "c")
    monkeypatch.setenv("FOODICS_CLIENT_SECRET", "s")
    assert pos.is_vendor_available("foodics") is False


def test_unknown_vendor_is_not_available():
    assert pos.is_vendor_available("clover") is False


def test_vendor_status_is_honest():
    st = pos.vendor_status()
    assert set(st) == {"mock", "square", "foodics", "omnivore", "lightspeed"}
    assert st["mock"]["usable"] is True and st["mock"]["implemented"] is True
    for v in ("square", "foodics", "omnivore", "lightspeed"):
        assert st[v]["usable"] is False and st[v]["implemented"] is False
        assert "not integrated" in st[v]["note"]


def test_credentials_read_by_env_name_not_db():
    code = _code(pos.is_vendor_available)
    assert "_env(" in code
    assert "SELECT" not in code and "execute" not in code  # never a DB read for a secret


# --------------------------------------------------------------------------
# Connect: mock connects; a real vendor is refused before any DB write.
# --------------------------------------------------------------------------

class _ExplodingDB:
    async def execute(self, *a, **k):
        raise AssertionError("DB touched while connecting an unavailable vendor")

    async def commit(self):
        raise AssertionError("DB commit while connecting an unavailable vendor")


@pytest.mark.asyncio
async def test_begin_oauth_refuses_unintegrated_vendor_before_db():
    conn, err = await pos.begin_oauth(_ExplodingDB(), tenant_id=1, vendor="square",
                                      redirect_uri="https://x", actor="a")
    assert conn is None and "not available" in err and "not yet integrated" in err


@pytest.mark.asyncio
async def test_begin_oauth_rejects_unknown_vendor():
    conn, err = await pos.begin_oauth(_ExplodingDB(), tenant_id=1, vendor="clover",
                                      redirect_uri="https://x", actor="a")
    assert conn is None and "Unknown POS vendor" in err


def test_authorize_url_only_realised_for_mock():
    url = pos.oauth_authorize_url("mock", redirect_uri="https://x", state="s")
    assert url.startswith("https://connect.mock.local/oauth/authorize")
    with pytest.raises(RuntimeError, match="not integrated"):
        pos.oauth_authorize_url("square", redirect_uri="https://x", state="s")


# --------------------------------------------------------------------------
# The pull adapter refuses a real vendor (defence in depth).
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapter_pull_refuses_real_vendor():
    with pytest.raises(RuntimeError, match="not integrated"):
        await pos._adapter_pull(_ExplodingDB(), "foodics", tenant_id=1,
                                window_start=None, window_end=None)


# --------------------------------------------------------------------------
# ADR-010: the connector never feeds the revenue grain; it writes the basket grain.
# --------------------------------------------------------------------------

def test_write_targets_only_the_basket_grain():
    code = _code(pos._write_receipts)
    assert "INTO transactions" in code
    assert "INTO transaction_lines" in code
    # Never the revenue grain, or a connected POS would double-count.
    assert "sales_fact_view" not in code
    assert "sales_stream_raw" not in code
    assert "sales_historical" not in code


def test_ingestion_is_idempotent_by_construction():
    """A replayed window must not duplicate — the header insert relies on the DB's
    UNIQUE(tenant, source, txn_ref) via ON CONFLICT DO NOTHING."""
    code = _code(pos._write_receipts)
    assert "ON CONFLICT" in code and "DO NOTHING" in code
    assert "if txn_id is None:" in code  # a conflicted receipt is skipped, not re-lined


def test_mock_rows_are_synthetic():
    code = _code(pos._write_receipts)
    assert "is_synthetic = vendor == MOCK_VENDOR" in code or "vendor == MOCK_VENDOR" in code


def test_sync_records_a_run_and_never_settles_revenue():
    code = _code(pos.sync_connection)
    assert "INTO pos_sync_runs" in code
    assert "sales_fact_view" not in code


# --------------------------------------------------------------------------
# Migration guards.
# --------------------------------------------------------------------------

def test_migration_scopes_by_rls_and_guards_connected():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "enable row level security" in ddl and "force row level security" in ddl
    assert ddl.count("tenant_isolation") >= 2  # both tables
    # A connected connection must name its account.
    assert "pos_connections_connected_has_account" in ddl
    assert "status <> 'connected' or external_account_ref is not null" in ddl
    # Idempotency + one connection per vendor per tenant.
    assert "unique (tenant_id, vendor)" in ddl


def test_migration_credentials_are_env_names_not_secrets():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "credential_env" in ddl
    # No plaintext-secret columns.
    for forbidden in ("client_secret", "access_token ", "oauth_token", "password"):
        assert forbidden not in ddl


# --------------------------------------------------------------------------
# Route + scheduler wiring.
# --------------------------------------------------------------------------

def test_every_route_requires_admin():
    from app.routes import pos as routes
    for fn in (routes.vendors, routes.connections, routes.connect, routes.sync,
               routes.runs, routes.delete_connection):
        assert "_require_admin(user)" in _code(fn)


def test_router_registered_under_api_pos():
    from app.routes.registry import ROUTERS
    assert any(prefix == "/api/pos" for _, prefix, _ in ROUTERS)


def test_nightly_sync_runs_in_the_singletons_process():
    """The pull must live in the single-instance container, not per web worker, or a
    tenant's receipts would be pulled N times."""
    import app.commands.singletons as sg
    src = inspect.getsource(sg._main)
    assert "pos_sync_loop" in src
    assert "settings.pos_sync_enabled" in src


def test_pos_sync_is_configurable():
    from app.config import get_settings
    s = get_settings()
    assert hasattr(s, "pos_sync_enabled")
    assert hasattr(s, "pos_sync_interval_seconds")
