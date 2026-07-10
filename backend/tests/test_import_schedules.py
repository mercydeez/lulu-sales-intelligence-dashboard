"""E2-2 — recurring imports on a schedule.

The feature's whole risk is a silent double-import: `sales_historical` is
append-only, so a nightly job that re-fetches an unchanged CSV would double the
tenant's sales every run and the number would look plausible. The content hash is
the correctness mechanism, not an optimisation, and these tests pin it.

The rest is honesty about scope: only `https` is implemented, and the API says so
(501) rather than storing a schedule that would never fire.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import csv_import as imp
from app.services import import_scheduler as sch


MIGRATION = (pathlib.Path(__file__).resolve().parents[2]
             / "database" / "migrations" / "064_krishna_import_schedules.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _code_only(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# The double-import guard.
# --------------------------------------------------------------------------

def test_the_payload_is_hashed_and_an_unchanged_one_is_skipped():
    code = _code_only(sch.run_schedule)
    assert "digest == sched['last_content_hash']" in code
    assert "'skipped_unchanged'" in code


def test_the_skip_happens_before_anything_is_written():
    """The hash check must precede the job row, or a skipped run still leaves an
    import_jobs record claiming it ran."""
    code = _code_only(sch.run_schedule)
    assert code.index("skipped_unchanged") < code.index("INSERT INTO import_jobs")


def test_the_hash_covers_the_raw_bytes():
    a = sch.content_hash(b"date,store\n2026-01-01,X\n")
    b = sch.content_hash(b"date,store\n2026-01-01,X\n")
    c = sch.content_hash(b"date,store\n2026-01-02,X\n")
    assert a == b and a != c
    assert len(a) == 64


def test_a_schedule_records_the_hash_only_on_a_successful_import():
    """Storing the hash on a failed run would make the next attempt skip the file
    it never actually imported."""
    code = _code_only(sch.run_schedule)
    ok_call = code.index("status='ok'")
    assert "new_hash=digest" in code[ok_call:ok_call + 200]


# --------------------------------------------------------------------------
# Honest scope.
# --------------------------------------------------------------------------

def test_all_three_transports_are_supported():
    # E2-2 completion (migration 067): sftp + imap are now implemented, not refused.
    assert set(sch.SUPPORTED_SOURCE_KINDS) == {"https", "sftp", "imap"}
    assert sch.UNSUPPORTED_SOURCE_KINDS == {}


def test_the_database_admits_only_the_three_real_transports():
    """Defence in depth: the CHECK still refuses anything we can't run
    (widened in migration 067, verified in test_import_transports.py)."""
    sql064 = _sql().lower()
    assert "check (source_kind in ('https'))" in sql064  # 064's original narrower CHECK
    # The widening + its own constraints are asserted in test_import_transports.py.


def test_creating_a_genuinely_unknown_transport_is_still_rejected():
    from app.routes import imports as routes
    code = _code_only(routes.create_schedule)
    # 501 machinery is retained for any future not-yet-built kind…
    assert "status_code=501" in code
    # …and an unknown kind is 422'd.
    assert "Unknown source_kind" in code


def test_a_failed_run_must_record_why():
    sql = _sql().lower()
    assert "import_schedules_failure_has_reason" in sql
    assert "length(btrim(last_error)) > 0" in sql


# --------------------------------------------------------------------------
# SSRF: the URL is tenant-supplied and our servers fetch it.
# --------------------------------------------------------------------------

def test_the_fetcher_goes_through_the_ssrf_guard():
    code = _code_only(sch.fetch_https)
    assert "is_safe_url" in code


def test_the_creation_route_also_refuses_an_unsafe_url():
    """Checked at creation so the operator learns immediately, and again at every
    run because DNS can be re-pointed afterwards."""
    from app.routes import imports as routes
    code = _code_only(routes.create_schedule)
    assert "is_safe_url" in code


def test_the_ssrf_guard_actually_rejects_the_dangerous_targets():
    from app.services.sage2.api_source import is_safe_url
    for bad in ("http://127.0.0.1/x.csv",
                "http://localhost/x.csv",
                "http://169.254.169.254/latest/meta-data",
                "file:///etc/passwd",
                "gopher://x/1"):
        assert not is_safe_url(bad), f"{bad} must be refused"


def test_the_download_is_bounded():
    code = _code_only(sch.fetch_https)
    assert "MAX_DOWNLOAD_BYTES" in code
    assert sch.MAX_DOWNLOAD_BYTES <= 50 * 1024 * 1024


# --------------------------------------------------------------------------
# Backoff, claiming, and reuse of the manual path.
# --------------------------------------------------------------------------

def test_backoff_is_exponential_and_capped():
    assert sch.backoff_minutes(60, 0) == 60      # healthy: the configured interval
    assert sch.backoff_minutes(60, 1) == 60      # first failure: no penalty yet
    assert sch.backoff_minutes(60, 2) == 120
    assert sch.backoff_minutes(60, 3) == 240
    assert sch.backoff_minutes(60, 99) == 60 * sch.MAX_BACKOFF_MULTIPLIER


def test_being_over_quota_is_not_a_failure():
    """Backing a schedule off exponentially because the tenant hit their monthly
    import limit would leave it crawling long after the quota reset."""
    code = _code_only(sch.run_schedule)
    assert "'skipped_quota'" in code
    assert "failures=0" in code.split("skipped_quota")[1][:120]


def test_due_schedules_are_claimed_with_skip_locked():
    """Several replicas run this loop; two must not run the same schedule."""
    code = _code_only(sch._claim_due_schedules)
    assert "FOR UPDATE SKIP LOCKED" in code
    assert "next_run_at = now() + make_interval" in code


def test_a_scheduled_import_reuses_the_manual_commit_path():
    """A second import implementation would be a second set of bugs — and would
    miss the quality report, the undo ledger and the quota."""
    code = _code_only(sch.run_schedule)
    assert "imp.validate_rows(" in code
    assert "imp.commit_import(" in code
    assert "import_job_id=job_id" in code, "scheduled rows must be reversible too (E2-4)"
    assert "reversible" in code


def test_a_failed_run_writes_no_rows():
    """The import's transaction is discarded whole; the failure is recorded in a
    fresh one, so it survives the rollback."""
    code = _code_only(sch.run_due_schedules)
    assert "ScheduleRunFailed" in code
    assert code.index("ScheduleRunFailed") < code.index("_finish(")


# --------------------------------------------------------------------------
# The mapping a schedule uses when nobody is at a keyboard.
# --------------------------------------------------------------------------

def test_default_mapping_is_exact_matches_only():
    m = imp.default_mapping("stores", ["name", "location"])
    assert m == {"name": "name", "location": "location"}


def test_default_mapping_does_not_guess_a_near_miss():
    """`store_name` is not `name`. Guessing could load the wrong column into
    `sales`, and a wrong number that looks right is the worst outcome here."""
    m = imp.default_mapping("stores", ["store_name", "loc"])
    assert m == {}


def test_an_unmapped_required_field_fails_the_run_by_name():
    code = _code_only(sch.run_schedule)
    assert "not mapped" in code
    assert "Payload headers were" in code, "say what we saw, so the operator can fix it"


def test_a_configured_mapping_wins_over_the_default():
    code = _code_only(sch.run_schedule)
    assert "sched['mapping'] or imp.default_mapping(" in code


def test_the_payload_format_is_decided_by_magic_bytes():
    """The URL's extension is a claim; the bytes are evidence."""
    code = _code_only(sch.parse_payload)
    assert "sniff_workbook_kind" in code


def test_the_interval_floor_is_enforced_in_the_database():
    sql = _sql().lower()
    assert "interval_minutes >= 15" in sql


def test_schedules_are_tenant_scoped_with_forced_rls():
    sql = _sql().lower()
    assert "enable row level security" in sql
    assert "force row level security" in sql


@pytest.mark.asyncio
async def test_parse_payload_rejects_binary_that_is_not_a_workbook():
    with pytest.raises(sch.FetchError, match="neither a spreadsheet nor UTF-8"):
        sch.parse_payload(b"\xff\xfe\x00\x01\x02binary junk")
