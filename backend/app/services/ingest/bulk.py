"""
Chunked, resumable bulk ingestion of external sales data (SCALE-2).
Architecture + capacity math: docs/product/specs/EXTERNAL_DATA_AT_SCALE.md.

Contract (what makes 600 GB feasible where db_seeder isn't):
  * The file is streamed, never loaded whole — memory is O(chunk).
  * Each chunk (CHUNK_ROWS rows) is content-addressed (sha256 of its bytes) and
    recorded in ingest_ledger. A chunk whose hash is already 'loaded' is
    skipped — so a crashed job RESUMES and a duplicate file NO-OPS.
  * Per chunk, ONE transaction covers: COPY into external_sales (partition
    ensured first) + incremental upsert of sales_rollup_daily + ledger mark
    'loaded'. Crash anywhere → the whole chunk rolls back → exactly-once.
  * Rollup increments are aggregated in memory per chunk, so serving-table
    write cost is O(distinct keys in chunk), not O(raw rows).

CSV contract (header required, extra columns rejected — schema drift must be
loud, not silently mis-mapped):
    store_id,item_id,sale_date,units[,revenue_aed][,txn_count]
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timezone
from typing import Dict, Iterator, List, Optional, TextIO, Tuple

from sqlalchemy import text

from app.config import logger
from app.services.database import engine

CHUNK_ROWS = 50_000

_REQUIRED = ["store_id", "item_id", "sale_date", "units"]
_OPTIONAL = ["revenue_aed", "txn_count"]

# In-process view of running jobs (authoritative state lives in ingest_ledger,
# which survives restarts; this only adds liveness for the status endpoint).
_active_jobs: Dict[str, Dict] = {}


def _parse_header(line: str) -> List[str]:
    cols = [c.strip().lower() for c in line.strip().split(",")]
    if cols[: len(_REQUIRED)] != _REQUIRED or any(
        c not in _OPTIONAL for c in cols[len(_REQUIRED):]
    ):
        raise ValueError(
            f"unexpected header {cols!r}; expected "
            f"{_REQUIRED} then optional {_OPTIONAL} in order"
        )
    return cols


def _chunks(fh: TextIO) -> Iterator[Tuple[int, bytes, List[str]]]:
    """Yield (chunk_no, raw_bytes, raw_lines) of up to CHUNK_ROWS data lines."""
    buf: List[str] = []
    chunk_no = 0
    for line in fh:
        if not line.strip():
            continue
        buf.append(line)
        if len(buf) >= CHUNK_ROWS:
            yield chunk_no, "".join(buf).encode("utf-8"), buf
            chunk_no += 1
            buf = []
    if buf:
        yield chunk_no, "".join(buf).encode("utf-8"), buf


def _parse_rows(
    raw_lines: List[str], cols: List[str], tenant_id: int, source_name: str
) -> Tuple[List[tuple], Dict[Tuple[int, int, date], List]]:
    """Parse a chunk strictly. Any bad row rejects the whole chunk (the ledger
    records the error; the job continues with the next chunk). Returns COPY
    records and the in-memory rollup increments."""
    has_rev = "revenue_aed" in cols
    has_txn = "txn_count" in cols
    records: List[tuple] = []
    rollup: Dict[Tuple[int, int, date], List] = {}
    reader = csv.reader(io.StringIO("".join(raw_lines)))
    for ln, row in enumerate(reader, start=1):
        if len(row) != len(cols):
            raise ValueError(f"row {ln}: {len(row)} fields, expected {len(cols)}")
        try:
            store = int(row[0]); item = int(row[1])
            day = date.fromisoformat(row[2].strip())
            units = float(row[3])
            rev = float(row[4]) if has_rev and row[4] != "" else None
            txn = int(row[5 if has_rev else 4]) if has_txn else 1
        except (ValueError, IndexError) as e:
            raise ValueError(f"row {ln}: {e}") from e
        records.append((tenant_id, source_name, store, item, day, units, rev, txn))
        key = (store, item, day)
        agg = rollup.setdefault(key, [0.0, 0.0, 0])
        agg[0] += units
        agg[1] += rev or 0.0
        agg[2] += txn
    return records, rollup


_UPSERT = text("""
    INSERT INTO sales_rollup_daily
        (tenant_id, store_id, item_id, day, units, revenue_aed, txn_count, updated_at)
    VALUES (:t, :s, :i, :d, :u, :r, :c, now())
    ON CONFLICT (tenant_id, store_id, item_id, day) DO UPDATE SET
        units       = sales_rollup_daily.units       + EXCLUDED.units,
        revenue_aed = sales_rollup_daily.revenue_aed + EXCLUDED.revenue_aed,
        txn_count   = sales_rollup_daily.txn_count   + EXCLUDED.txn_count,
        updated_at  = now()
""")


async def ingest_csv_file(
    tenant_id: int,
    source_name: str,
    file_path: str,
    job_id: str,
) -> Dict:
    """Ingest a CSV from a server-visible path. Returns a summary dict.
    Safe to re-run with the same file: loaded chunks are skipped via ledger."""
    summary = {
        "job_id": job_id, "source_name": source_name, "state": "running",
        "chunks_loaded": 0, "chunks_skipped": 0, "chunks_failed": 0,
        "rows_loaded": 0, "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _active_jobs[job_id] = summary
    try:
        with open(file_path, "r", encoding="utf-8", newline="") as fh:
            header = fh.readline()
            cols = _parse_header(header)
            for chunk_no, raw, lines in _chunks(fh):
                sha = hashlib.sha256(raw).hexdigest()
                try:
                    loaded = await _ingest_chunk(
                        tenant_id, source_name, job_id, chunk_no, sha, lines, cols
                    )
                except Exception as e:  # chunk-scoped: record, keep going
                    logger.warning(f"[bulk] chunk {chunk_no} failed: {e}")
                    await _mark_failed(tenant_id, source_name, job_id, chunk_no, sha, str(e))
                    summary["chunks_failed"] += 1
                    continue
                if loaded is None:
                    summary["chunks_skipped"] += 1
                else:
                    summary["chunks_loaded"] += 1
                    summary["rows_loaded"] += loaded
        summary["state"] = "done" if summary["chunks_failed"] == 0 else "done_with_errors"
    except Exception as e:  # file-scoped (bad header, unreadable path)
        logger.error(f"[bulk] job {job_id} aborted: {e}")
        summary["state"] = "aborted"
        summary["error"] = str(e)
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary


async def _ingest_chunk(
    tenant_id: int, source_name: str, job_id: str,
    chunk_no: int, sha: str, lines: List[str], cols: List[str],
) -> Optional[int]:
    """One chunk, one transaction. Returns rows loaded, or None if skipped."""
    records, rollup = _parse_rows(lines, cols, tenant_id, source_name)
    months = {d.replace(day=1) for (_, _, d) in rollup.keys()}

    async with engine.begin() as conn:
        # Claim the chunk. If these exact bytes already loaded → skip.
        row = (await conn.execute(text("""
            INSERT INTO ingest_ledger
                (tenant_id, source_name, job_id, chunk_no, chunk_sha256, status)
            VALUES (:t, :src, :job, :no, :sha, 'pending')
            ON CONFLICT ON CONSTRAINT uq_ingest_chunk DO UPDATE
                SET job_id = EXCLUDED.job_id
            RETURNING id, status
        """), {"t": tenant_id, "src": source_name, "job": job_id,
               "no": chunk_no, "sha": sha})).fetchone()
        if row.status == "loaded":
            return None

        for m in months:
            await conn.execute(
                text("SELECT ensure_external_sales_partition(:d)"), {"d": m})

        raw = await conn.get_raw_connection()
        await raw.driver_connection.copy_records_to_table(
            "external_sales",
            records=records,
            columns=["tenant_id", "source_name", "store_id", "item_id",
                     "sale_date", "units", "revenue_aed", "txn_count"],
        )

        await conn.execute(_UPSERT, [
            {"t": tenant_id, "s": s, "i": i, "d": d, "u": u, "r": r, "c": c}
            for (s, i, d), (u, r, c) in rollup.items()
        ])

        await conn.execute(text("""
            UPDATE ingest_ledger
               SET status = 'loaded', row_count = :n, completed_at = now(), error = NULL
             WHERE id = :id
        """), {"n": len(records), "id": row.id})
    return len(records)


async def _mark_failed(
    tenant_id: int, source_name: str, job_id: str,
    chunk_no: int, sha: str, error: str,
) -> None:
    """Record a failed chunk outside the (rolled-back) chunk transaction."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO ingest_ledger
                    (tenant_id, source_name, job_id, chunk_no, chunk_sha256,
                     status, error)
                VALUES (:t, :src, :job, :no, :sha, 'failed', :err)
                ON CONFLICT ON CONSTRAINT uq_ingest_chunk DO UPDATE
                    SET status = 'failed', error = EXCLUDED.error, job_id = EXCLUDED.job_id
            """), {"t": tenant_id, "src": source_name, "job": job_id,
                   "no": chunk_no, "sha": sha, "err": error[:500]})
    except Exception:
        logger.exception("[bulk] could not record failed chunk")


async def job_status(job_id: str) -> Dict:
    """Ledger-backed job status (survives restarts) + live state if running."""
    async with engine.connect() as conn:
        row = (await conn.execute(text("""
            SELECT COUNT(*) AS chunks,
                   COUNT(*) FILTER (WHERE status = 'loaded')  AS loaded,
                   COUNT(*) FILTER (WHERE status = 'failed')  AS failed,
                   COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                   COALESCE(SUM(row_count) FILTER (WHERE status = 'loaded'), 0) AS rows_loaded
              FROM ingest_ledger WHERE job_id = :job
        """), {"job": job_id})).fetchone()
    out = {
        "job_id": job_id, "chunks": row.chunks, "loaded": row.loaded,
        "failed": row.failed, "pending": row.pending,
        "rows_loaded": int(row.rows_loaded),
    }
    live = _active_jobs.get(job_id)
    if live:
        out["state"] = live["state"]
    return out
