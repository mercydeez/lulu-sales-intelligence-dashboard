"""
SCALE-3 benchmark + functional proof for the bulk-ingest pipeline.
Run INSIDE the backend container (engine resolves postgres:5432 there):

    python scripts/bench_bulk_ingest.py --rows 2000000

What it proves, in order:
  1. generate  — synthetic CSV (stores×items×days, spread over ~13 months)
  2. ingest    — time the real pipeline (chunked COPY + ledger + rollups)
  3. resume    — re-ingest the SAME file: every chunk must be skipped (ledger
                 idempotency = crash-resume = duplicate-file no-op)
  4. parity    — SUM(units) raw staging == SUM(units) rollups (exact)
  5. latency   — 7-day revenue query: raw partitioned scan vs rollup read
  6. drift     — a malformed chunk is rejected, job continues (ledger 'failed')
Prints one JSON summary; paste the numbers into
docs/product/specs/EXTERNAL_DATA_AT_SCALE.md §6.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import uuid

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.services.database import engine  # noqa: E402
from app.services.ingest.bulk import ingest_csv_file  # noqa: E402

TENANT = 999  # scratch tenant so demo data is untouched


def generate_csv(path: str, rows: int) -> None:
    rng = random.Random(42)
    t0 = time.perf_counter()
    with open(path, "w", encoding="utf-8") as f:
        f.write("store_id,item_id,sale_date,units,revenue_aed,txn_count\n")
        day_count = 400  # ~13 months of partitions
        for i in range(rows):
            store = rng.randint(1, 10)
            item = rng.randint(1, 50)
            # deterministic-ish spread over days
            d = (i * 37 + rng.randint(0, 5)) % day_count
            y, rem = 2025 + (d // 365), d % 365
            month, dom = (rem // 31) + 1, (rem % 28) + 1
            units = rng.randint(1, 40)
            f.write(f"{store},{item},{y}-{month:02d}-{dom:02d},{units},{units * 3.5:.2f},1\n")
    print(f"[gen] {rows:,} rows in {time.perf_counter() - t0:.1f}s "
          f"({os.path.getsize(path) / 1e6:.0f} MB)", flush=True)


async def timed_query(sql: str, params: dict) -> tuple[float, float]:
    async with engine.connect() as conn:
        t0 = time.perf_counter()
        val = (await conn.execute(text(sql), params)).scalar()
        return time.perf_counter() - t0, float(val or 0)


async def main(rows: int) -> None:
    path = "/tmp/import_drop/bench.csv"
    os.makedirs("/tmp/import_drop", exist_ok=True)
    out: dict = {"rows": rows}

    # clean slate for the scratch tenant
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM external_sales WHERE tenant_id = :t"), {"t": TENANT})
        await conn.execute(text("DELETE FROM sales_rollup_daily WHERE tenant_id = :t"), {"t": TENANT})
        await conn.execute(text("DELETE FROM ingest_ledger WHERE tenant_id = :t"), {"t": TENANT})

    generate_csv(path, rows)

    # 2. ingest (timed)
    t0 = time.perf_counter()
    s1 = await ingest_csv_file(TENANT, "bench", path, uuid.uuid4().hex[:12])
    ingest_s = time.perf_counter() - t0
    assert s1["state"] == "done", s1
    assert s1["rows_loaded"] == rows, s1
    out["ingest_seconds"] = round(ingest_s, 1)
    out["rows_per_second"] = int(rows / ingest_s)
    print(f"[ingest] {rows:,} rows in {ingest_s:.1f}s = {out['rows_per_second']:,} rows/s", flush=True)

    # 3. resume/idempotency: same bytes → all chunks skipped, zero rows
    s2 = await ingest_csv_file(TENANT, "bench", path, uuid.uuid4().hex[:12])
    assert s2["rows_loaded"] == 0 and s2["chunks_loaded"] == 0, s2
    assert s2["chunks_skipped"] == s1["chunks_loaded"], s2
    out["resume_reingest"] = f"OK — {s2['chunks_skipped']} chunks skipped, 0 rows duplicated"
    print(f"[resume] {out['resume_reingest']}", flush=True)

    # 4. parity: raw staging vs rollup must agree exactly
    _, raw_units = await timed_query(
        "SELECT COALESCE(SUM(units),0) FROM external_sales WHERE tenant_id=:t", {"t": TENANT})
    _, ru_units = await timed_query(
        "SELECT COALESCE(SUM(units),0) FROM sales_rollup_daily WHERE tenant_id=:t", {"t": TENANT})
    assert raw_units == ru_units, (raw_units, ru_units)
    out["parity"] = f"OK — SUM(units) raw == rollup == {raw_units:,.0f}"
    print(f"[parity] {out['parity']}", flush=True)

    # 5. serving latency: last-7-days revenue, raw vs rollup (median of 5)
    async def median5(sql: str) -> float:
        times = []
        for _ in range(5):
            dt, _v = await timed_query(sql, {"t": TENANT})
            times.append(dt)
        return sorted(times)[2]

    raw_ms = await median5(
        "SELECT COALESCE(SUM(revenue_aed),0) FROM external_sales "
        "WHERE tenant_id=:t AND sale_date >= '2025-06-01' AND sale_date < '2025-06-08'")
    ru_ms = await median5(
        "SELECT COALESCE(SUM(revenue_aed),0) FROM sales_rollup_daily "
        "WHERE tenant_id=:t AND day >= '2025-06-01' AND day < '2025-06-08'")
    out["query_7d_raw_ms"] = round(raw_ms * 1000, 1)
    out["query_7d_rollup_ms"] = round(ru_ms * 1000, 1)
    print(f"[latency] 7d revenue: raw {out['query_7d_raw_ms']}ms vs rollup {out['query_7d_rollup_ms']}ms", flush=True)

    # 6. schema drift: malformed rows reject their chunk, job continues
    bad = "/tmp/import_drop/bench_bad.csv"
    with open(bad, "w", encoding="utf-8") as f:
        f.write("store_id,item_id,sale_date,units\n")
        f.write("1,1,2025-06-01,5\n")
        f.write("1,1,not-a-date,5\n")  # poisons chunk 0
    s3 = await ingest_csv_file(TENANT, "bench-bad", bad, uuid.uuid4().hex[:12])
    assert s3["chunks_failed"] == 1 and s3["state"] == "done_with_errors", s3
    out["schema_drift"] = "OK — bad chunk marked failed on ledger, job finished"
    print(f"[drift] {out['schema_drift']}", flush=True)

    # 600 GB extrapolation (110 B/row incl. index overhead ⇒ ~5.45B rows)
    rows_600gb = int(600e9 / 110)
    hours = rows_600gb / out["rows_per_second"] / 3600
    out["extrapolation_600gb"] = (
        f"~{rows_600gb / 1e9:.1f}B rows ≈ {hours:.0f}h single-stream on this dev box "
        f"(÷N for N parallel COPY streams on server NVMe)")
    print(f"[extrapolate] {out['extrapolation_600gb']}", flush=True)

    print("\n" + json.dumps(out, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2_000_000)
    args = ap.parse_args()
    asyncio.run(main(args.rows))
