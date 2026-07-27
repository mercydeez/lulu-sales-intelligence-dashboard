"""Migration 075 — schema guarantees that must survive any future edit.

These assert on the SQL text rather than a live database, following the existing
migration-test convention in the suite (test_bespoke.py, test_einvoice_clearance.py).
They are a tripwire: if someone later relaxes RLS, drops a money column to
DOUBLE PRECISION, or removes an idempotency constraint, the build fails here
rather than in production six months later.

The repo has a documented anti-pattern of "vacuous source-grep tests" — checks
that pass whatever the code does. Each assertion below is written so that the
DEFECT it guards against would actually break it.
"""
import pathlib
import re

import pytest


def _find_migration(name: str) -> pathlib.Path:
    """Locate a migration by walking up — robust to the repo layout (backend/ and
    database/ siblings) AND the container layout (both under /app)."""
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("075_krishna_flywheel_retention.sql")
SQL = MIGRATION.read_text() if MIGRATION.is_file() else ""

#: The SQL with `--` comments AND single-quoted string literals stripped.
#: Column-type checks must run against this, not the raw text: the migration's
#: prose and its COMMENT ON bodies legitimately contain words like "real" and
#: "float". Matching those would be a false positive, and a test that cries wolf
#: is one the next reader learns to ignore.
SQL_CODE = re.sub(
    r"'(?:[^']|'')*'", "''",
    "\n".join(line.split("--")[0] for line in SQL.splitlines()),
)

#: Every Flywheel table. Kept explicit rather than derived from the SQL, so ADDING
#: a table without RLS also fails this file.
FLYWHEEL_TABLES = [
    "flywheel_customers", "flywheel_customer_consents", "flywheel_customer_events",
    "flywheel_purchase_attributions", "flywheel_model_versions", "flywheel_feature_snapshots",
    "flywheel_churn_predictions", "flywheel_offer_response_predictions", "flywheel_campaigns",
    "flywheel_campaign_transitions", "flywheel_campaign_audience", "flywheel_decisions",
    "flywheel_inventory_allocations", "flywheel_procurement_requisitions",
    "flywheel_transfer_recommendations", "flywheel_budgets", "flywheel_budget_ledger",
    "flywheel_approval_policies", "flywheel_approval_requests", "flywheel_approval_steps",
    "flywheel_offers", "flywheel_redemptions", "flywheel_outbox", "flywheel_contact_log",
    "flywheel_campaign_outcomes",
]


def test_migration_file_exists():
    assert MIGRATION.is_file(), f"074 migration not found at {MIGRATION}"


def test_migration_is_transactional():
    """A partially-applied schema is worse than none — 24 tables half-created
    would leave the app booting against an inconsistent database."""
    assert SQL.strip().startswith("--") or SQL.lstrip().startswith("BEGIN")
    assert "BEGIN;" in SQL and "COMMIT;" in SQL


@pytest.mark.parametrize("table", FLYWHEEL_TABLES)
def test_every_table_is_created(table):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in SQL


@pytest.mark.parametrize("table", FLYWHEEL_TABLES)
def test_every_table_carries_tenant_id(table):
    """Multi-tenancy is app-layer scoping PLUS RLS; both need the column."""
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SQL, re.DOTALL)
    assert match, f"could not parse the DDL for {table}"
    assert "tenant_id" in match.group(1), f"{table} has no tenant_id column"


@pytest.mark.parametrize("table", FLYWHEEL_TABLES)
def test_every_table_is_in_the_rls_loop(table):
    """The DO block enables RLS + FORCE for each listed table. A table added to
    the schema but forgotten here would be readable across tenants."""
    rls_block = SQL[SQL.index("FOREACH t IN ARRAY ARRAY["):]
    assert f"'{table}'" in rls_block, f"{table} is missing from the RLS array"


def test_rls_uses_force_and_the_shared_tenant_function():
    """FORCE matters: without it a table-owner connection bypasses the policy,
    which is exactly how the app connects when USE_RLS_ROLE is off."""
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "current_tenant_id()" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL


# ---------------------------------------------------------------------------
# Money must never be a float
# ---------------------------------------------------------------------------

def test_no_money_column_uses_a_binary_float_type():
    """FLOAT/REAL/DOUBLE PRECISION cannot represent 0.10 exactly. A ledger built
    on them drifts, and the drift is unrecoverable.

    Matched against SQL_CODE (comments stripped) and with word boundaries, so
    the word "real" in a comment cannot fail this — only an actual column type.
    """
    for banned in (r"DOUBLE\s+PRECISION", r"\bREAL\b", r"\bFLOAT\b"):
        assert not re.search(banned, SQL_CODE.upper()), \
            f"a binary float type ({banned}) appears in the Flywheel schema"


@pytest.mark.parametrize("column", [
    "allocated_aed", "reserved_aed", "committed_aed", "spent_aed", "released_aed",
    "amount_aed", "eiv_aed", "discount_aed", "net_value_aed", "total_cost_aed",
])
def test_money_columns_are_numeric(column):
    assert re.search(rf"{column}\s+NUMERIC", SQL), f"{column} is not NUMERIC"


# ---------------------------------------------------------------------------
# The financial and physical invariants, enforced by the database itself
# ---------------------------------------------------------------------------

def test_budget_cannot_be_overspent():
    """THE core financial invariant. Even a bug in budget_service.py cannot
    push reserved + spent past the approved allocation."""
    assert "flywheel_budget_within_allocation" in SQL
    assert re.search(r"reserved_aed\s*\+\s*spent_aed\s*<=\s*allocated_aed", SQL)


def test_allocation_cannot_be_overconsumed():
    """Physical counterpart: you cannot redeem more units than were allocated."""
    assert "flywheel_allocation_not_overconsumed" in SQL
    assert re.search(r"consumed_units\s*<=\s*allocated_units", SQL)


def test_redemption_idempotency_key_is_unique_per_tenant():
    """§17 — the anti-double-spend mechanism. Without this UNIQUE constraint a
    retried redemption charges twice and decrements stock twice."""
    assert re.search(
        r"UNIQUE\s*\(tenant_id,\s*idempotency_key\)", SQL), \
        "flywheel_redemptions is missing its idempotency uniqueness constraint"


def test_budget_ledger_idempotency_is_enforced_by_a_partial_unique_index():
    """Partial (WHERE NOT NULL) so entries without a key are still allowed —
    a plain UNIQUE would collapse every NULL-keyed row into one."""
    assert "uq_flywheel_ledger_idem" in SQL
    assert "WHERE idempotency_key IS NOT NULL" in SQL


def test_money_amounts_cannot_be_negative():
    """Negative amounts would let a 'reservation' silently increase the budget."""
    assert re.search(r"amount_aed\s+NUMERIC\(16,2\)\s+NOT NULL\s+CHECK \(amount_aed >= 0\)", SQL)


# ---------------------------------------------------------------------------
# Proof-carrying statuses — the repo's honesty convention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("constraint,reason", [
    ("flywheel_campaign_paused_has_reason",
     "an auto-paused campaign with no reason is not actionable"),
    ("flywheel_campaign_active_has_timestamp",
     "claiming ACTIVE without knowing when it went live breaks the audit trail"),
    ("flywheel_offer_redeemed_has_timestamp",
     "a redeemed offer must carry the moment of redemption"),
    ("flywheel_step_decided_has_actor",
     "a decided approval step must record who decided and when"),
    ("flywheel_req_converted_has_po",
     "a requisition claiming conversion must name the PO"),
    ("flywheel_outbox_published_has_timestamp",
     "published means delivered — it must carry the delivery moment"),
    ("flywheel_model_trained_has_timestamp",
     "a trained model must record when it was trained"),
])
def test_status_claims_carry_their_proof(constraint, reason):
    assert constraint in SQL, f"missing {constraint}: {reason}"


def test_an_approval_request_targets_exactly_one_subject():
    """A request pointing at both a campaign and a requisition — or neither —
    would make the approval chain ambiguous."""
    assert "flywheel_approval_one_subject" in SQL


def test_transfers_cannot_be_from_a_store_to_itself():
    assert "flywheel_transfer_distinct_stores" in SQL


# ---------------------------------------------------------------------------
# Reuse rather than fork (the audit's central decision)
# ---------------------------------------------------------------------------

def test_flywheel_references_existing_platform_tables():
    """Flywheel must EXTEND the platform, not shadow it. These FKs are the proof."""
    for reference in ("REFERENCES tenants(id)", "REFERENCES stores(id)",
                      "REFERENCES items(id)", "REFERENCES users(id)",
                      "REFERENCES suppliers(id)", "REFERENCES purchase_orders(id)",
                      "REFERENCES stock_transfers(id)"):
        assert reference in SQL, f"expected {reference}"


def test_no_parallel_inventory_or_sales_table_is_created():
    """The failure mode this guards: a `flywheel_inventory` table becoming a second
    answer to 'how much stock do we have', with the wrong one eventually winning."""
    for forbidden in ("CREATE TABLE IF NOT EXISTS flywheel_inventory (",
                      "CREATE TABLE IF NOT EXISTS flywheel_sales",
                      "CREATE TABLE IF NOT EXISTS flywheel_items",
                      "CREATE TABLE IF NOT EXISTS flywheel_stores"):
        assert forbidden not in SQL, f"Flywheel must not fork core data: {forbidden}"


def test_existing_tables_are_not_altered_or_dropped():
    """Migration 075 is additive. Touching a shared table would break the
    guarantee that every existing feature keeps working."""
    assert "DROP TABLE" not in SQL.upper()
    for shared in ("ALTER TABLE inventory ", "ALTER TABLE items ",
                   "ALTER TABLE stores ", "ALTER TABLE sales_historical ",
                   "ALTER TABLE promotions ", "ALTER TABLE purchase_orders "):
        assert shared not in SQL, f"074 must not alter the shared table in: {shared}"


# ---------------------------------------------------------------------------
# Seeded configuration
# ---------------------------------------------------------------------------

def test_approval_policies_are_seeded_as_configuration_not_hard_coded():
    """§15 — thresholds must be editable data, not code."""
    assert "INSERT INTO flywheel_approval_policies" in SQL
    for label in ("Marketing", "Inventory", "Procurement", "Finance", "CFO"):
        assert f"'{label}'" in SQL, f"no seeded {label} approval step"


def test_parallel_approval_steps_share_a_step_order():
    """Inventory and Procurement review both run at stage 2. If they were
    sequential, each would wait on the other for no reason.

    The seeded VALUES rows end `..., <step_order>, '<step_label>')`, so the
    order is (number, label) — matching (label, number) would silently find
    nothing and pass a weaker assertion than intended.
    """
    seed_block = SQL[SQL.index("INSERT INTO flywheel_approval_policies"):]
    stage_two = re.findall(r",\s*2,\s*'(Inventory|Procurement)'\)", seed_block)
    assert set(stage_two) == {"Inventory", "Procurement"}, (
        f"expected Inventory and Procurement to share stage 2, found {stage_two}")


def test_demo_budgets_are_seeded_idempotently():
    """Re-running the migration must not double a tenant's allocation."""
    assert "INSERT INTO flywheel_budgets" in SQL
    assert "ON CONFLICT (tenant_id, budget_type, period_start) DO NOTHING" in SQL


def test_outbox_has_a_partial_index_on_pending_rows():
    """The relay polls unpublished rows constantly; a full index would grow
    without bound as published events accumulate."""
    assert "ix_flywheel_outbox_pending" in SQL
    assert "WHERE published = FALSE" in SQL


def test_sequence_model_index_supports_ordered_event_reads():
    """The GRU reads (customer, occurred_at) in order — without this index that
    is a sort over the whole event table per training run."""
    assert "ix_flywheel_events_seq" in SQL
    assert "(tenant_id, customer_id, occurred_at)" in SQL
