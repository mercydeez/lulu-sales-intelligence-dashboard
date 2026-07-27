"""Platform Console — the bespoke ("Rolls-Royce") request ledger (B2).

Brand rule under test: HONESTY. The state machine refuses illegal jumps (a
request cannot teleport requested -> delivered), `delivered` always carries its
timestamp, `declined` always carries its reason, refusals happen BEFORE any
write, and the ledger is cross-tenant control-plane data — platform-developer
gated at the route layer, revoked from the tenant-request role at the DB layer.
"""
import ast
import inspect
import pathlib
import textwrap
from datetime import datetime, timezone

import pytest

from app.services import bespoke


def _find_migration(name: str) -> pathlib.Path:
    """Locate a migration by walking up — robust to the repo layout (backend/ and
    database/ siblings) AND the container layout (both under /app)."""
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("073_krishna_bespoke_requests.sql")


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def _stripped_sql() -> str:
    """The migration with comment lines removed — assertions must hold on the
    EXECUTABLE SQL, not on prose in comments."""
    lines = MIGRATION.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.lstrip().startswith("--")).lower()


class _ExplodingDB:
    """A session that proves 'refused BEFORE any DB work' — any touch fails."""

    async def execute(self, *a, **k):
        raise AssertionError("DB touched by a call that should have been refused first")

    async def commit(self):
        raise AssertionError("DB commit by a call that should have been refused first")


class _RecordingDB:
    """Captures writes so a legal update's SQL can be inspected without Postgres."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt, params=None):
        self.statements.append((str(stmt), params))
        return None


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def fetchone(self):
        return self._row


# --------------------------------------------------------------------------
# Migration 073 — the ledger table and its honesty invariants.
# --------------------------------------------------------------------------

def test_migration_creates_the_ledger_idempotently():
    sql = _stripped_sql()
    assert "create table if not exists bespoke_requests" in sql
    assert "drop constraint if exists" in sql  # guarded re-add, house style
    assert "create index if not exists ix_bespoke_requests_status" in sql
    assert "create index if not exists ix_bespoke_requests_tenant" in sql
    for status in ("requested", "scoped", "approved", "building", "delivered", "declined"):
        assert f"'{status}'" in sql
    # A request may predate its tenant, and must survive tenant deletion.
    assert "on delete set null" in sql


def test_a_delivered_claim_must_carry_its_timestamp():
    sql = _stripped_sql()
    assert "bespoke_delivered_has_timestamp" in sql
    assert "status <> 'delivered' or delivered_at is not null" in sql


def test_a_declined_claim_must_carry_its_reason():
    sql = _stripped_sql()
    assert "bespoke_declined_has_reason" in sql
    assert "status <> 'declined' or scoping_notes is not null" in sql


def test_the_tenant_request_role_is_revoked_from_the_ledger():
    """Migration 020's DEFAULT PRIVILEGES grant DML on every new table to app_rw
    (the tenant request-path role). This table is cross-tenant control-plane data,
    so those default grants MUST be revoked — otherwise a future tenant-facing
    query bug could read every client's bespoke asks."""
    sql = _stripped_sql()
    assert "revoke all on bespoke_requests from app_rw" in sql
    assert "revoke all on sequence bespoke_requests_id_seq from app_rw" in sql
    # Guarded: the role may not exist on a fresh dev volume.
    assert "if exists (select 1 from pg_roles where rolname = 'app_rw')" in sql


def test_no_rls_policy_on_purpose():
    """Control-plane table: gated by require_platform_developer in the route
    layer (same pattern as tenant_provisioning, 068) — deliberately no RLS."""
    assert "create policy" not in _stripped_sql()


# --------------------------------------------------------------------------
# The state machine — pure, no DB.
# --------------------------------------------------------------------------

STATUSES = sorted(bespoke.TRANSITIONS)

LEGAL_EDGES = [
    ("requested", "scoped"), ("requested", "declined"),
    ("scoped", "approved"), ("scoped", "declined"),
    ("approved", "building"), ("approved", "declined"),
    ("building", "delivered"), ("building", "declined"),
]


@pytest.mark.parametrize("frm,to", LEGAL_EDGES)
def test_every_legal_edge_is_allowed(frm, to):
    assert bespoke.transition_error(frm, to, has_reason=True) is None


@pytest.mark.parametrize("frm", STATUSES)
@pytest.mark.parametrize("to", STATUSES)
def test_the_full_transition_matrix(frm, to):
    if frm == to:
        pytest.skip("same-status is an idempotent no-op in update_request, not a transition")
    err = bespoke.transition_error(frm, to, has_reason=True)
    assert (err is None) == (to in bespoke.TRANSITIONS[frm]), (frm, to, err)


def test_a_request_cannot_teleport_to_delivered():
    err = bespoke.transition_error("requested", "delivered")
    assert err is not None and "Illegal transition" in err


@pytest.mark.parametrize("to", [s for s in STATUSES if s != "delivered"])
def test_delivered_is_terminal(to):
    err = bespoke.transition_error("delivered", to, has_reason=True)
    assert err is not None


def test_unknown_statuses_are_refused():
    assert "Unknown status" in bespoke.transition_error("requested", "shipped")


# --------------------------------------------------------------------------
# Declining requires a reason.
# --------------------------------------------------------------------------

def test_declining_without_a_reason_is_refused_purely():
    err = bespoke.transition_error("scoped", "declined", has_reason=False)
    assert err is not None and "scoping_notes" in err
    assert bespoke.transition_error("scoped", "declined", has_reason=True) is None


def _fake_row(**over):
    row = {"id": 7, "tenant_id": 3, "title": "Prayer-time aware staffing",
           "client_description": "as asked", "status": "scoped", "priority": "high",
           "scoping_notes": None, "estimate": None, "ai_suggestion": None,
           "delivered_at": None, "created_by": "dev@vendor", "updated_by": None,
           "created_at": "2026-07-11T00:00:00+00:00",
           "updated_at": "2026-07-11T00:00:00+00:00"}
    row.update(over)
    return row


@pytest.mark.asyncio
async def test_update_refuses_decline_without_reason_before_any_write(monkeypatch):
    async def fake_get(db, request_id):
        return _fake_row(scoping_notes=None)
    monkeypatch.setattr(bespoke, "get_request", fake_get)
    row, err = await bespoke.update_request(_ExplodingDB(), 7, status="declined", actor="dev@vendor")
    assert row is None and err is not None and "scoping_notes" in err


@pytest.mark.asyncio
async def test_decline_accepts_a_reason_already_on_the_row(monkeypatch):
    calls = []

    async def fake_get(db, request_id):
        return _fake_row(scoping_notes="Out of scope: bespoke hardware")

    async def fake_event(*a, **k):
        calls.append((a, k))
    monkeypatch.setattr(bespoke, "get_request", fake_get)
    monkeypatch.setattr("app.services.security_events.record_event", fake_event)
    db = _RecordingDB()
    row, err = await bespoke.update_request(db, 7, status="declined", actor="dev@vendor")
    assert err is None
    assert len(db.statements) == 1 and db.statements[0][1]["status"] == "declined"
    # The audit event names the request and the transition — proof, not vibes.
    assert calls and calls[0][0][0] == "bespoke_request_updated"
    assert "scoped -> declined" in calls[0][1]["detail"]
    assert calls[0][1]["severity"] == "medium"  # status change


# --------------------------------------------------------------------------
# update_request — refusals happen BEFORE any write; delivered gets stamped.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_illegal_jump_is_refused_after_read_but_before_write(monkeypatch):
    async def fake_get(db, request_id):
        return _fake_row(status="requested")
    monkeypatch.setattr(bespoke, "get_request", fake_get)
    row, err = await bespoke.update_request(_ExplodingDB(), 7, status="delivered", actor="dev@vendor")
    assert row is None and "Illegal transition" in err


@pytest.mark.asyncio
async def test_garbage_status_is_refused_before_even_reading():
    row, err = await bespoke.update_request(_ExplodingDB(), 7, status="shipped", actor="dev@vendor")
    assert row is None and "Unknown status" in err


@pytest.mark.asyncio
async def test_delivering_stamps_the_timestamp(monkeypatch):
    async def fake_get(db, request_id):
        return _fake_row(status="building")

    async def fake_event(*a, **k):
        pass
    monkeypatch.setattr(bespoke, "get_request", fake_get)
    monkeypatch.setattr("app.services.security_events.record_event", fake_event)
    db = _RecordingDB()
    row, err = await bespoke.update_request(db, 7, status="delivered", actor="dev@vendor")
    assert err is None
    sql = db.statements[0][0]
    assert "delivered_at = now()" in sql and "status = :status" in sql


def test_delivered_stamp_is_in_the_update_source():
    assert "delivered_at = now()" in _code(bespoke.update_request)


# --------------------------------------------------------------------------
# create_request — validated before DB, audited after.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_refuses_a_garbage_priority_before_db():
    with pytest.raises(ValueError, match="priority"):
        await bespoke.create_request(_ExplodingDB(), tenant_id=None, title="abc",
                                     client_description="abc", priority="urgent",
                                     created_by="dev@vendor")


@pytest.mark.asyncio
async def test_create_returns_the_row_and_records_an_audit_event(monkeypatch):
    events = []

    async def fake_event(*a, **k):
        events.append((a, k))
    monkeypatch.setattr("app.services.security_events.record_event", fake_event)

    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)

    class _DB:
        async def execute(self, stmt, params=None):
            return _Result(_fake_row(id=1, status="requested", priority=params["priority"],
                                     title=params["title"], created_at=now, updated_at=now))

    rec = await bespoke.create_request(_DB(), tenant_id=3, title="RFID dock",
                                       client_description="scan pallets at the dock",
                                       priority="vip", created_by="dev@vendor")
    assert rec["id"] == 1 and rec["status"] == "requested"
    assert rec["created_at"] == now.isoformat()  # timestamps serialized isoformat
    assert events and events[0][0][0] == "bespoke_request_created"
    assert events[0][1]["severity"] == "low"
    assert "1" in events[0][1]["detail"]


@pytest.mark.asyncio
async def test_list_refuses_an_unknown_status_filter():
    with pytest.raises(ValueError, match="Unknown status"):
        await bespoke.list_requests(_ExplodingDB(), status="shipped")


# --------------------------------------------------------------------------
# Routes — platform-developer gated, on the OWNER session (cross-tenant data).
# --------------------------------------------------------------------------

def test_every_endpoint_is_platform_developer_gated():
    from fastapi.routing import APIRoute
    from app.routes import bespoke as routes
    from app.services.platform_access import require_platform_developer
    api_routes = [r for r in routes.router.routes if isinstance(r, APIRoute)]
    assert len(api_routes) == 4
    for r in api_routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_platform_developer in deps, f"{r.path} {r.methods} is not platform-gated"


def test_routes_use_the_owner_session_not_get_db():
    """Cross-tenant control-plane data must NOT run on get_db (it binds the
    caller's tenant GUC); the module must use async_session and never import
    get_db."""
    from app.routes import bespoke as routes
    src = inspect.getsource(routes)
    assert "require_platform_developer" in src
    assert "async with async_session() as db" in src
    imported = {alias.name
                for node in ast.walk(ast.parse(src))
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    assert "async_session" in imported
    assert "get_db" not in imported


def test_create_endpoint_returns_201():
    from fastapi.routing import APIRoute
    from app.routes import bespoke as routes
    post = next(r for r in routes.router.routes
                if isinstance(r, APIRoute) and "POST" in r.methods)
    assert post.status_code == 201


def test_registered_in_the_registry_under_api_admin():
    from app.routes.registry import ROUTERS
    from app.routes import bespoke as routes
    mounts = [(prefix, tags) for router, prefix, tags in ROUTERS if router is routes.router]
    assert mounts == [("/api/admin", ["Bespoke"])]
