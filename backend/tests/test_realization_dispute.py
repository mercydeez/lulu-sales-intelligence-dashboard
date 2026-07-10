"""E8-5 — disputing a confirmed value realization.

Outcome pricing bills a share of value the customer *confirmed* we created. That
makes the confirmation theirs to give and theirs to take back. The properties that
matter:

  1. a disputed line leaves the billable total immediately;
  2. the statement SAYS what it excluded, rather than quietly shrinking;
  3. the original confirmed amount survives the dispute, so resolving it restores
     the agreed figure instead of a re-keyed one;
  4. the party being billed raises the dispute; the party billing resolves it.

The DB-level checks are exercised in test_realization_dispute_sql (below) against
the migration text, since the constraints — not the Python — are what actually
stop a reasonless dispute.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import outcome_pricing as svc


MIGRATION = (pathlib.Path(__file__).resolve().parents[2]
             / "database" / "migrations" / "062_krishna_realization_dispute.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _code_only(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# The migration.
# --------------------------------------------------------------------------

def test_the_migration_exists_and_widens_the_status_domain():
    sql = _sql().lower()
    assert "'disputed'" in sql
    assert "status in ('pending', 'confirmed', 'dismissed', 'disputed')" in sql


def test_a_dispute_without_a_reason_is_impossible_at_the_db_level():
    """A reason-less dispute is unresolvable. Enforced by CHECK, not by a docstring."""
    sql = _sql().lower()
    assert "value_realizations_dispute_needs_reason" in sql
    assert "length(btrim(dispute_reason)) > 0" in sql, "a whitespace reason is no reason"


def test_a_disputed_row_must_keep_the_amount_that_was_billed():
    sql = _sql().lower()
    assert "value_realizations_dispute_keeps_amount" in sql
    assert "status <> 'disputed' or confirmed_value_aed is not null" in sql


def test_the_migration_is_rerunnable():
    """Every DDL statement guards itself, so re-applying is a no-op rather than an error."""
    sql = _sql().lower()
    assert sql.count("drop constraint if exists") >= 3
    assert "add column if not exists" in sql
    assert "create index if not exists" in sql


# --------------------------------------------------------------------------
# Billing impact — the property the whole feature exists for.
# --------------------------------------------------------------------------

def test_the_billable_total_counts_only_confirmed_rows():
    code = _code_only(svc.confirmed_value_total)
    assert "FILTER (WHERE status = 'confirmed')" in code
    assert "FILTER (WHERE status = 'disputed')" in code, \
        "the disputed total must be measured so the statement can disclose it"


def test_the_statement_discloses_the_exclusion():
    """An invoice quietly short by the disputed amount is how a billing dispute
    becomes a trust problem."""
    code = _code_only(svc.statement)
    for field in ("disputed_value_aed", "disputed_count", "disputed_value_excluded"):
        assert field in code


def test_build_statement_bills_only_what_it_was_given():
    """Sanity: the pure fee math is unchanged — disputes act by never reaching it."""
    plan = {"base_fee_aed": 1000, "value_share_pct": 10, "savings_guarantee_multiple": 0}
    assert svc.build_statement(50_000, plan)["variable_fee_aed"] == 5_000.0
    # A disputed 20k simply never enters `confirmed_value`.
    assert svc.build_statement(30_000, plan)["variable_fee_aed"] == 3_000.0


# --------------------------------------------------------------------------
# The state machine.
# --------------------------------------------------------------------------

def test_only_a_confirmed_row_can_be_disputed():
    code = _code_only(svc.dispute_realization)
    assert "status = 'confirmed'" in code, \
        "a pending or dismissed line was never billed — there is nothing to contest"


def test_disputing_preserves_the_confirmed_amount():
    """The customer is arguing with a specific number; erasing it makes the dispute
    unarguable and the resolution un-restorable."""
    code = _code_only(svc.dispute_realization)
    assert "confirmed_value_aed = NULL" not in code
    assert "RETURNING id, status, confirmed_value_aed, dispute_reason" in code


def test_an_empty_reason_is_refused_before_it_reaches_the_db():
    code = _code_only(svc.dispute_realization)
    assert "reason.strip()" in code or "(reason or '').strip()" in code


@pytest.mark.asyncio
async def test_resolve_rejects_an_unknown_resolution():
    assert await svc.resolve_dispute(None, 1, 1, resolution="maybe",
                                     note=None, user="x") is None


def test_accepting_a_dispute_clears_the_value_and_dismisses():
    """Accepted = the customer was right, so the value is not real and is not billed."""
    code = _code_only(svc.resolve_dispute)
    assert "status = 'dismissed', confirmed_value_aed = NULL" in code


def test_rejecting_a_dispute_restores_the_original_amount():
    """Rejected = the value stands. It re-enters the billable total at the amount
    that was already on the row — no re-keying, no new number."""
    code = _code_only(svc.resolve_dispute)
    assert "status = 'confirmed'" in code
    assert "confirmed_value_aed = :val" not in code, "the amount must not be re-supplied"


def test_resolving_only_acts_on_an_open_dispute():
    code = _code_only(svc.resolve_dispute)
    assert "AND status = 'disputed'" in code


def test_resolution_names_the_dispute_not_the_value():
    """'accepted'/'rejected' describe the customer's objection. 'confirmed'/'dismissed'
    would read as if the objection produced a confirmation."""
    sig = inspect.signature(svc.resolve_dispute)
    assert "resolution" in sig.parameters
    code = _code_only(svc.resolve_dispute)
    assert "('accepted', 'rejected')" in code


# --------------------------------------------------------------------------
# Who may do what.
# --------------------------------------------------------------------------

def test_the_billed_party_raises_the_dispute():
    from app.routes import outcome_pricing as routes
    code = _code_only(routes.dispute_realization)
    assert "_require_admin(user)" in code


def test_only_the_vendor_resolves_the_dispute():
    """Letting the billed party decide the outcome would make the state decorative."""
    from app.routes import outcome_pricing as routes
    code = _code_only(routes.resolve_dispute)
    assert "super_admin" in code
    assert "_require_admin(user)" not in code


def test_disputed_is_not_settable_through_the_generic_status_endpoint():
    from app.routes import outcome_pricing as routes
    code = _code_only(routes.set_realization)
    assert "'disputed'" in code and "422" in code


def test_both_transitions_are_audited():
    from app.routes import outcome_pricing as routes
    assert "value_realization_disputed" in _code_only(routes.dispute_realization)
    assert "value_realization_dispute_resolved" in _code_only(routes.resolve_dispute)
