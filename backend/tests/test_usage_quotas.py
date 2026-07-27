"""E8-3 — plan-scoped quota enforcement.

Enforcement turns a meter into a refusal, so the failure modes are asymmetric:

  * refusing a request the tenant was entitled to = lost work, angry customer;
  * allowing one extra request = a rounding error on the invoice.

So `enforce_quota` fails OPEN on an infrastructure error and CLOSED only on a
measured over-quota. These tests pin both directions, plus the two counting bugs
that would have made enforcement actively destructive the day it was switched on:

  1. imports were metered per ROW against a per-JOB limit (5,000-row CSV = 5,000);
  2. `forecast_jobs` and `api_requests` were advertised with limits but never
     recorded — a permanent 0 rendered as a measurement.
"""
import ast
import inspect
import textwrap
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services import usage_metering as um


def _code_only(fn) -> str:
    """A function's CODE, without its comments or docstring.

    Several of these routes explain in prose exactly which call they must NOT
    make, so a substring check over raw source would trip on the explanation.
    `ast.unparse` drops comments and we drop the docstring node by hand.
    """
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# Fakes: a db whose plan row and period counts we control.
# --------------------------------------------------------------------------

def _db(plan="free", counts=None):
    counts = counts or {}
    db = MagicMock()

    async def _execute(stmt, params=None):
        sql = str(stmt)
        res = MagicMock()
        if "FROM tenants" in sql:
            res.fetchone.return_value = MagicMock(plan=plan)
        else:  # the usage_events aggregate
            res.fetchall.return_value = [
                MagicMock(event_type=et, used=n) for et, n in counts.items()
            ]
        return res

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.fixture
def enforcing(monkeypatch):
    monkeypatch.setattr(um, "_enforcement_on", lambda: True)


@pytest.fixture
def metering_only(monkeypatch):
    monkeypatch.setattr(um, "_enforcement_on", lambda: False)


# --------------------------------------------------------------------------
# The counting bugs.
# --------------------------------------------------------------------------

def test_an_import_job_is_one_import_not_one_per_row():
    """The free plan allows 20 `imports` per period. If a 5,000-row CSV counted as
    5,000, turning enforcement on would have bricked the free tier on the first
    upload. The route must record quantity=1 and keep the row count in metadata."""
    from app.routes import imports as imports_route

    code = _code_only(imports_route.commit)
    assert "record_usage(tenant_id, 'import', quantity=1" in code, \
        "an import job must be metered as ONE import, not one per row"
    assert "quantity=persist['imported']" not in code, \
        "row count must never be the metered quantity"
    assert "'rows_imported': persist['imported']" in code, \
        "the row count is still worth keeping — in metadata"


def _event_literals_passed_to(func_name: str) -> set:
    """Every string literal passed as the event argument to `func_name(...)`
    anywhere under app/.

    Deliberately AST-based. A substring search for `"api_request"` finds the entry
    in usage_metering's own EVENT_TO_DIM map and therefore passes even when no
    route records the event — a guard that cannot fail is worse than none.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    found = set()
    for path in root.rglob("*.py"):
        if path.name == "usage_metering.py":
            continue  # the definitions live here, not the call sites
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name != func_name:
                continue
            # record_usage(tenant_id, "event", ...) / enforce_quota(db, tid, "event")
            for arg in node.args[1:3]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def test_the_dimensions_that_are_advertised_are_actually_recorded():
    """Every dimension with a published limit must have a real writer, or the usage
    summary shows a fabricated 0 next to a real limit.

    `forecast_jobs` and `api_requests` were exactly that before E8-3.
    """
    recorded = _event_literals_passed_to("record_usage")
    singular = {dim: ev for ev, dim in um.EVENT_TO_DIM.items()}
    missing = [
        dim for dim in um.METERED_EVENTS if singular[dim] not in recorded
    ]
    assert not missing, (
        f"these dimensions are published with a plan limit but nothing records "
        f"them, so they render as a permanent 0: {missing}"
    )


# --------------------------------------------------------------------------
# Fail open / fail closed.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_broken_meter_never_blocks_a_paid_action(enforcing):
    """DB down, table missing, whatever: we do not KNOW the tenant is over, and
    refusing on a guess is worse than one extra request."""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("relation usage_events does not exist"))

    assert await um.enforce_quota(db, 1, "sage_message") is None  # allowed, silently


@pytest.mark.asyncio
async def test_a_measured_over_quota_does_block(enforcing):
    db = _db(plan="free", counts={"sage_message": 100})   # free limit is 100
    with pytest.raises(HTTPException) as ei:
        await um.enforce_quota(db, 1, "sage_message")
    assert ei.value.status_code == 429


@pytest.mark.asyncio
async def test_under_the_limit_is_allowed(enforcing):
    db = _db(plan="free", counts={"sage_message": 99})
    meter = await um.enforce_quota(db, 1, "sage_message")
    assert meter["used"] == 99 and meter["remaining"] == 1


@pytest.mark.asyncio
async def test_enforcement_off_allows_an_over_quota_tenant(metering_only):
    db = _db(plan="free", counts={"sage_message": 10_000})
    assert await um.enforce_quota(db, 1, "sage_message") is not None  # metered, not blocked


@pytest.mark.asyncio
async def test_enterprise_is_unlimited_even_when_enforcing(enforcing):
    db = _db(plan="enterprise", counts={"sage_message": 10_000_000})
    meter = await um.enforce_quota(db, 1, "sage_message")
    assert meter["limit"] is None and meter["over_quota"] is False


@pytest.mark.asyncio
async def test_the_quota_is_plan_scoped(enforcing):
    """900 messages: over the free limit (100), under starter's (2,000)."""
    assert (await um.check_quota(_db("starter", {"sage_message": 900}), 1, "sage_message"))[0] is True
    with pytest.raises(HTTPException):
        await um.enforce_quota(_db("free", {"sage_message": 900}), 1, "sage_message")


# --------------------------------------------------------------------------
# The 429 has to be actionable.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_429_names_the_meter_and_when_it_resets(enforcing):
    db = _db(plan="free", counts={"import": 20})
    with pytest.raises(HTTPException) as ei:
        await um.enforce_quota(db, 1, "import")

    exc = ei.value
    d = exc.detail
    assert d["error"] == "quota_exceeded"
    assert d["dimension"] == "imports"       # plural dimension, not the event name
    assert d["plan"] == "free"
    assert d["used"] == 20 and d["limit"] == 20 and d["remaining"] == 0
    assert d["period"].startswith("month:")
    assert d["resets_at"]

    assert int(exc.headers["Retry-After"]) > 0
    assert exc.headers["X-Quota-Dimension"] == "imports"
    assert exc.headers["X-Quota-Limit"] == "20"
    assert exc.headers["X-Quota-Remaining"] == "0"
    assert exc.headers["X-Quota-Reset"] == d["resets_at"]


def test_retry_after_points_at_the_next_period_not_a_guess():
    now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
    secs = um.seconds_until_period_reset(now)
    end = um.current_period(now)["end"]
    assert secs == int((end - now).total_seconds())
    assert secs > 0


# --------------------------------------------------------------------------
# Which dimensions actually refuse.
# --------------------------------------------------------------------------

def test_exports_are_billed_but_never_blocked():
    """Both export surfaces are legal rights (data portability; compliance
    evidence). We meter them; we do not withhold them."""
    assert "exports" not in um.ENFORCED_DIMENSIONS
    assert "exports" in um.METERED_EVENTS


def test_the_data_rights_export_does_not_call_enforce_quota():
    from app.routes import data_rights

    code = _code_only(data_rights.export_my_tenant)
    assert "record_usage" in code
    assert "enforce_quota" not in code, \
        "data portability is a right; a billing meter must not be able to refuse it"


def test_that_guard_would_catch_a_real_enforce_call():
    """Negative control: the check above must fail on code that actually enforces,
    not merely on code that mentions it in a comment."""
    async def _leaky(db, tenant_id):
        # data portability is a right (this comment must not save it)
        await um.enforce_quota(db, tenant_id, "export")

    assert "enforce_quota" in _code_only(_leaky)


def test_the_summary_marks_each_dimension_as_enforced_or_not(monkeypatch):
    """A limit that never refuses must not render as a hard cap."""
    monkeypatch.setattr(um, "_enforcement_on", lambda: True)
    limits = um.usage_limits_for_plan("free")
    for dim in um.METERED_EVENTS:
        enforced = dim in um.ENFORCED_DIMENSIONS and limits[dim] is not None
        assert enforced == (dim != "exports"), dim


def test_enforced_dimensions_all_have_an_enforcer():
    """Claiming a dimension is enforced, with nothing calling enforce_quota for it,
    would publish a cap that never caps."""
    enforced = _event_literals_passed_to("enforce_quota")
    singular = {dim: ev for ev, dim in um.EVENT_TO_DIM.items()}
    missing = [dim for dim in um.ENFORCED_DIMENSIONS if singular[dim] not in enforced]
    assert not missing, (
        f"listed in ENFORCED_DIMENSIONS but nothing calls enforce_quota for them: {missing}"
    )


def test_exports_are_never_passed_to_enforce_quota():
    """The other half of the same contract: a dimension we promised not to block
    must have no enforcer anywhere."""
    assert "export" not in _event_literals_passed_to("enforce_quota")


def test_the_ast_guard_is_not_vacuous():
    """It must see the real call sites — if this returns an empty set, every guard
    built on it passes for free."""
    recorded = _event_literals_passed_to("record_usage")
    assert {"sage_message", "import", "export", "api_request", "forecast_job"} <= recorded


# --------------------------------------------------------------------------
# A refused request must not consume the quota that refused it.
# --------------------------------------------------------------------------

def test_the_public_api_enforces_before_it_records():
    from app.routes import public_api

    code = _code_only(public_api.get_api_context)
    assert code.index("enforce_quota(") < code.index("record_usage("), \
        "a 429'd request must not be metered as a consumed api_request"


def test_the_import_route_checks_quota_before_parsing_the_file():
    from app.routes import imports as imports_route

    code = _code_only(imports_route.commit)
    assert code.index("enforce_quota(") < code.index("_parse_source("), \
        "refusing after parsing a 5,000-row file is the same 429, slower"
