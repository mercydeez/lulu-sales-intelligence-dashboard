"""
SCALE-4: bulk-ingest pipeline tests.

Pure tests (no DB) cover the parsing/chunking/aggregation contract — the part
that decides what bytes become what rows. The end-to-end invariants
(ledger resume, rollup parity, drift handling, 19k rows/s throughput) run in
the container via scripts/bench_bulk_ingest.py and, gated on RUN_DB_TESTS=1,
in CI's stack-smoke job below.
"""
import io
import os
from datetime import date

import pytest

from app.services.ingest.bulk import (
    CHUNK_ROWS, _chunks, _parse_header, _parse_rows,
)


# ── header contract ──────────────────────────────────────────────────────────
def test_header_minimal_and_full():
    assert _parse_header("store_id,item_id,sale_date,units\n") == [
        "store_id", "item_id", "sale_date", "units"]
    assert _parse_header("store_id,item_id,sale_date,units,revenue_aed,txn_count\n")[-1] == "txn_count"


def test_header_rejects_wrong_order_and_unknown_columns():
    with pytest.raises(ValueError):
        _parse_header("item_id,store_id,sale_date,units\n")     # order matters
    with pytest.raises(ValueError):
        _parse_header("store_id,item_id,sale_date,units,price\n")  # unknown col


# ── row parsing + in-chunk rollup aggregation ────────────────────────────────
def test_parse_rows_aggregates_rollup_increments():
    cols = ["store_id", "item_id", "sale_date", "units", "revenue_aed", "txn_count"]
    lines = [
        "1,7,2026-07-01,12,42.00,3\n",
        "1,7,2026-07-01,8,28.00,2\n",   # same key → aggregated
        "2,7,2026-07-02,5,17.50,1\n",
    ]
    records, rollup = _parse_rows(lines, cols, tenant_id=42, source_name="t")
    assert len(records) == 3
    assert records[0][:2] == (42, "t")  # tenant + source stamped on every row
    u, r, c = rollup[(1, 7, date(2026, 7, 1))]
    assert (u, r, c) == (20.0, 70.0, 5)
    assert rollup[(2, 7, date(2026, 7, 2))] == [5.0, 17.5, 1]


def test_parse_rows_strict_on_bad_row():
    cols = ["store_id", "item_id", "sale_date", "units"]
    with pytest.raises(ValueError, match="row 2"):
        _parse_rows(["1,1,2026-07-01,5\n", "1,1,not-a-date,5\n"], cols, 1, "t")
    with pytest.raises(ValueError, match="fields"):
        _parse_rows(["1,1,2026-07-01\n"], cols, 1, "t")  # missing field


def test_parse_rows_optional_revenue_defaults():
    cols = ["store_id", "item_id", "sale_date", "units"]
    records, rollup = _parse_rows(["3,9,2026-01-05,4\n"], cols, 1, "t")
    assert records[0][6] is None          # revenue_aed nullable
    assert records[0][7] == 1             # txn_count defaults to 1
    assert rollup[(3, 9, date(2026, 1, 5))] == [4.0, 0.0, 1]


# ── chunking ─────────────────────────────────────────────────────────────────
def test_chunks_split_and_preserve_bytes():
    n = CHUNK_ROWS + 7
    body = "".join(f"1,1,2026-07-01,{i}\n" for i in range(n))
    chunks = list(_chunks(io.StringIO(body)))
    assert [c[0] for c in chunks] == [0, 1]
    assert len(chunks[0][2]) == CHUNK_ROWS and len(chunks[1][2]) == 7
    # chunk bytes are exactly the source lines → sha256 is content-addressed
    assert b"".join(c[1] for c in chunks).decode() == body


def test_chunks_skip_blank_lines():
    chunks = list(_chunks(io.StringIO("1,1,2026-07-01,1\n\n\n1,1,2026-07-01,2\n")))
    assert len(chunks) == 1 and len(chunks[0][2]) == 2


# ── end-to-end (DB) — CI stack-smoke job only ────────────────────────────────
@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="needs live DB stack")
@pytest.mark.asyncio
async def test_ingest_resume_and_parity_end_to_end(tmp_path):
    """Same file twice: second run all-skipped; raw == rollup exactly."""
    import uuid
    from sqlalchemy import text
    from app.services.database import engine
    from app.services.ingest.bulk import ingest_csv_file

    tenant = 998  # scratch
    f = tmp_path / "e2e.csv"
    f.write_text(
        "store_id,item_id,sale_date,units,revenue_aed,txn_count\n"
        + "".join(f"{s},{i},2026-03-0{d},10,35.00,2\n"
                  for s in (1, 2) for i in (5, 6) for d in (1, 2, 3)))

    async with engine.begin() as conn:
        for tbl in ("external_sales", "sales_rollup_daily", "ingest_ledger"):
            await conn.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t"), {"t": tenant})

    s1 = await ingest_csv_file(tenant, "e2e", str(f), uuid.uuid4().hex[:12])
    assert s1["state"] == "done" and s1["rows_loaded"] == 12

    s2 = await ingest_csv_file(tenant, "e2e", str(f), uuid.uuid4().hex[:12])
    assert s2["rows_loaded"] == 0 and s2["chunks_skipped"] == s1["chunks_loaded"]

    async with engine.connect() as conn:
        raw = (await conn.execute(text(
            "SELECT SUM(units) FROM external_sales WHERE tenant_id=:t"), {"t": tenant})).scalar()
        ru = (await conn.execute(text(
            "SELECT SUM(units) FROM sales_rollup_daily WHERE tenant_id=:t"), {"t": tenant})).scalar()
    assert raw == ru == 120
