"""Durable job tier — work that survives a process dying mid-run.

THE PROBLEM. Scoring 5,000 customers, measuring every campaign, issuing a batch
of offers — none of these fit in one transaction, and today they run as asyncio
tasks inside a process. A redeploy 40 minutes into a scoring run loses the run
with no way to resume, and nothing records that it was ever in flight. That is
tolerable for a demo and disqualifying for an operable product.

THE DESIGN. A Postgres-backed queue (flywheel_jobs, migration 078) claimed with
`FOR UPDATE SKIP LOCKED`, with two properties that plain "SELECT a pending row"
queues lack:

  LEASE. Claiming a job stamps a lease_expires_at. If the worker dies, the lease
  lapses and `reap()` returns the job to 'queued' for another worker. Without a
  lease, a crashed worker strands its job in 'running' forever — the single most
  common way a home-grown queue silently stops working.

  CHECKPOINT. A handler records its progress (a batch cursor, counts) as it goes.
  A resumed job reads the checkpoint and continues from the last completed batch
  instead of restarting. This is what turns "the redeploy lost 40 minutes" into
  "the redeploy cost one batch".

EXACTLY-ONCE, HONESTLY. At-least-once delivery plus idempotent handlers is the
only combination that is actually achievable — true exactly-once execution across
a crash is a myth. So:
  * enqueue is idempotent (a partial unique index: at most one live job per key);
  * claims are exclusive (SKIP LOCKED);
  * handlers are written to be safe to re-run a batch (scoring UPSERTs, offers
    check a delivery receipt). A job that is reclaimed after a crash may re-run
    its LAST in-flight batch, and that must be a no-op, not a double-charge.

WHERE IT RUNS. The worker loop lives in the singletons container (exactly one
process) — see commands/singletons.py. It could run in every API worker safely
(SKIP LOCKED partitions the work), but a background job processor competing with
request latency is a Horizon-3 decision; single-instance is the honest default.

NO NEW BROKER. The branch is named for BullMQ, but the backend is Python and the
one broker already in the stack (Redis) is not durable enough to be the system of
record for money-adjacent work. Postgres already holds the money; the queue lives
next to it so a job and the rows it touches commit or roll back together.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: How long a claim is valid before the reaper may reclaim it. Long enough that a
#: healthy worker renews it between batches; short enough that a crash is
#: recovered within a couple of minutes.
LEASE_SECONDS = 120

#: Exponential backoff base for a failed job's next attempt.
RETRY_BACKOFF_BASE_SECONDS = 15

VALID_KINDS = (
    "score_audience", "measure_campaign", "measure_all", "issue_offers",
    "shadow_score", "refresh_readouts", "train_model",
)


def _now() -> datetime:
    """UTC now. Isolated so tests can reason about it and so the whole module has
    one clock."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

async def enqueue(
    db: AsyncSession, *, tenant_id: int, kind: str,
    payload: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    trace_id: Optional[str] = None,
    max_attempts: int = 5,
    run_after: Optional[datetime] = None,
) -> Optional[int]:
    """Add a job. Returns its id, or None if an identical live job already exists.

    IDEMPOTENT. With an idempotency_key, enqueuing the same logical job twice — a
    double click, a retried request, two schedulers firing at once — returns the
    EXISTING job rather than creating a duplicate. The partial unique index does
    the enforcing; this is the graceful read of the conflict.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown job kind: {kind}")

    row = (await db.execute(
        text("""INSERT INTO flywheel_jobs
                   (tenant_id, kind, payload, idempotency_key, trace_id,
                    max_attempts, run_after)
                VALUES (:t, :k, CAST(:p AS JSONB), :key, :trace, :maxa,
                        COALESCE(:ra, now()))
                ON CONFLICT (tenant_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL
                          AND status IN ('queued', 'running', 'failed')
                    DO NOTHING
                RETURNING id"""),
        {"t": tenant_id, "k": kind, "p": json.dumps(payload or {}),
         "key": idempotency_key, "trace": trace_id, "maxa": max_attempts,
         "ra": run_after},
    )).fetchone()

    if row:
        logger.info("flywheel.job enqueued id=%s kind=%s tenant=%s", row[0], kind, tenant_id)
        return int(row[0])

    # DO NOTHING fired — a live job with this key already exists. Return its id so
    # the caller can watch the SAME job rather than believing it enqueued nothing.
    existing = (await db.execute(
        text("""SELECT id FROM flywheel_jobs
                 WHERE tenant_id = :t AND idempotency_key = :key
                   AND status IN ('queued', 'running', 'failed')
                 ORDER BY id DESC LIMIT 1"""),
        {"t": tenant_id, "key": idempotency_key},
    )).fetchone()
    return int(existing[0]) if existing else None


# ---------------------------------------------------------------------------
# Claim / checkpoint / complete / fail
# ---------------------------------------------------------------------------

async def claim(
    db: AsyncSession, *, worker_id: str, kinds: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically claim one ready job. Returns None if the queue is empty.

    'Ready' = queued or failed, run_after in the past, and NOT already leased by a
    live worker. `FOR UPDATE SKIP LOCKED` means two workers polling at once take
    disjoint jobs instead of one blocking on the other.
    """
    kind_clause = "AND kind = ANY(:kinds)" if kinds else ""
    params: Dict[str, Any] = {"worker": worker_id, "lease": LEASE_SECONDS}
    if kinds:
        params["kinds"] = kinds

    row = (await db.execute(
        text(f"""WITH nxt AS (
                    SELECT id FROM flywheel_jobs
                     WHERE status IN ('queued', 'failed')
                       AND run_after <= now()
                       {kind_clause}
                     ORDER BY run_after, id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                 )
                 UPDATE flywheel_jobs j
                    SET status = 'running',
                        claimed_by = :worker,
                        claimed_at = now(),
                        lease_expires_at = now() + make_interval(secs => :lease),
                        attempts = j.attempts + 1,
                        updated_at = now()
                   FROM nxt
                  WHERE j.id = nxt.id
              RETURNING j.id, j.tenant_id, j.kind, j.payload, j.checkpoint,
                        j.attempts, j.max_attempts, j.trace_id"""),
        params,
    )).fetchone()

    if not row:
        return None
    return {
        "id": int(row[0]), "tenant_id": int(row[1]), "kind": row[2],
        "payload": row[3] or {}, "checkpoint": row[4] or {},
        "attempts": int(row[5]), "max_attempts": int(row[6]), "trace_id": row[7],
    }


async def checkpoint(
    db: AsyncSession, *, job_id: int, checkpoint: Dict[str, Any],
    renew_lease: bool = True,
) -> None:
    """Persist progress AND renew the lease in one write.

    Renewing on every checkpoint is deliberate: a long job that checkpoints each
    batch keeps its lease fresh and is never reaped mid-run, while a job that
    stops checkpointing (hung, or dead) lets its lease lapse and becomes
    reclaimable. Progress and liveness are the same signal.
    """
    lease = ", lease_expires_at = now() + make_interval(secs => :lease)" if renew_lease else ""
    params: Dict[str, Any] = {"j": job_id, "cp": json.dumps(checkpoint)}
    if renew_lease:
        params["lease"] = LEASE_SECONDS
    await db.execute(
        text(f"""UPDATE flywheel_jobs
                    SET checkpoint = CAST(:cp AS JSONB), updated_at = now(){lease}
                  WHERE id = :j"""),
        params,
    )


async def complete(
    db: AsyncSession, *, job_id: int, result: Optional[Dict[str, Any]] = None,
) -> None:
    await db.execute(
        text("""UPDATE flywheel_jobs
                   SET status = 'succeeded', result = CAST(:r AS JSONB),
                       finished_at = now(), updated_at = now(),
                       lease_expires_at = NULL
                 WHERE id = :j"""),
        {"j": job_id, "r": json.dumps(result or {})},
    )


async def fail(
    db: AsyncSession, *, job_id: int, error: str, attempts: int, max_attempts: int,
) -> str:
    """Record a failure. Retries with backoff until max_attempts, then DEAD.

    A dead job is not deleted — a dead-letter you cannot inspect is a bug you
    cannot diagnose. It stays visible with its last error for an operator to
    triage or requeue.
    """
    if attempts >= max_attempts:
        await db.execute(
            text("""UPDATE flywheel_jobs
                       SET status = 'dead', last_error = :e,
                           finished_at = now(), updated_at = now(),
                           lease_expires_at = NULL
                     WHERE id = :j"""),
            {"j": job_id, "e": error[:2000]},
        )
        logger.error("flywheel.job DEAD id=%s after %s attempts: %s",
                     job_id, attempts, error[:200])
        return "dead"

    backoff = RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
    await db.execute(
        text("""UPDATE flywheel_jobs
                   SET status = 'failed', last_error = :e,
                       run_after = now() + make_interval(secs => :backoff),
                       lease_expires_at = NULL, updated_at = now()
                 WHERE id = :j"""),
        {"j": job_id, "e": error[:2000], "backoff": backoff},
    )
    logger.warning("flywheel.job retry id=%s attempt=%s/%s in %ss: %s",
                   job_id, attempts, max_attempts, backoff, error[:200])
    return "retry"


async def reap(db: AsyncSession, *, batch: int = 100) -> int:
    """Return jobs whose lease expired (their worker died) to the queue.

    This is what makes a mid-run crash recoverable. The reclaimed job re-enters
    the queue and a healthy worker resumes it FROM ITS CHECKPOINT — attempts is
    not incremented here (the crash was not the job's fault), only re-running is.
    """
    result = await db.execute(
        text("""UPDATE flywheel_jobs
                   SET status = 'queued', claimed_by = NULL,
                       lease_expires_at = NULL, updated_at = now(),
                       last_error = COALESCE(last_error, '') ||
                           ' [reaped: lease expired at ' || lease_expires_at || ']'
                 WHERE id IN (
                    SELECT id FROM flywheel_jobs
                     WHERE status = 'running'
                       AND lease_expires_at IS NOT NULL
                       AND lease_expires_at < now()
                     ORDER BY lease_expires_at
                     LIMIT :b
                     FOR UPDATE SKIP LOCKED
                 )"""),
        {"b": batch},
    )
    n = result.rowcount or 0
    if n:
        logger.warning("flywheel.job reaped %s stranded job(s)", n)
    return n


# ---------------------------------------------------------------------------
# Exactly-once delivery — consumer-side idempotency ledger
# ---------------------------------------------------------------------------

async def already_delivered(
    db: AsyncSession, *, tenant_id: int, consumer: str, event_key: str
) -> bool:
    """Has this consumer already acted on this event? A read for callers that
    want to branch before doing expensive work; `mark_delivered` is the atomic
    guard for the action itself."""
    row = (await db.execute(
        text("""SELECT 1 FROM flywheel_delivery_receipts
                 WHERE tenant_id = :t AND consumer = :c AND event_key = :k"""),
        {"t": tenant_id, "c": consumer, "k": event_key},
    )).fetchone()
    return row is not None


async def mark_delivered(
    db: AsyncSession, *, tenant_id: int, consumer: str, event_key: str,
    outcome: str = "processed", detail: Optional[str] = None,
) -> bool:
    """Claim the right to act on an event exactly once.

    Returns True if THIS caller won the claim (it should perform the side effect),
    False if the event was already processed (it must NOT). The uniqueness is
    enforced by the DB, so two workers racing on the same event resolve to exactly
    one winner — the loser's INSERT hits the conflict and returns False.

    The receipt MUST be written in the same transaction as the side effect it
    guards. Commit them together or a crash between them reintroduces the double
    action this exists to prevent.
    """
    row = (await db.execute(
        text("""INSERT INTO flywheel_delivery_receipts
                   (tenant_id, consumer, event_key, outcome, detail)
                VALUES (:t, :c, :k, :o, :d)
                ON CONFLICT (tenant_id, consumer, event_key) DO NOTHING
                RETURNING id"""),
        {"t": tenant_id, "c": consumer, "k": event_key, "o": outcome, "d": detail},
    )).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

#: kind -> async handler(db, job) -> result dict. A handler MUST checkpoint its
#: progress and be safe to re-run its last batch, because a reclaimed job resumes
#: from the checkpoint and may repeat the batch it was mid-way through.
Handler = Callable[[AsyncSession, Dict[str, Any]], Awaitable[Dict[str, Any]]]
_HANDLERS: Dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn
    return register


@handler("score_audience")
async def _score_audience(db: AsyncSession, job: Dict[str, Any]) -> Dict[str, Any]:
    """Score a tenant's customers in resumable batches.

    THE RESUMABILITY DEMO. Customers are scored id-ascending in batches; the
    checkpoint records the last id done and the running count. A worker killed
    after batch 3 leaves a checkpoint at (last_id, 300); the reclaimed job reads
    it and starts batch 4, so completed work is neither lost nor repeated. Scoring
    itself UPSERTs, so even a re-run of the in-flight batch is a no-op.
    """
    from app.services.flywheel import churn

    tenant_id = job["tenant_id"]
    batch_size = int(job["payload"].get("batch_size", 100))
    cp = job["checkpoint"] or {}
    last_id = int(cp.get("last_customer_id", 0))
    total = int(cp.get("scored", 0))

    while True:
        ids = [int(r[0]) for r in (await db.execute(
            text("""SELECT id FROM flywheel_customers
                     WHERE tenant_id = :t AND id > :last
                     ORDER BY id LIMIT :n"""),
            {"t": tenant_id, "last": last_id, "n": batch_size},
        )).fetchall()]
        if not ids:
            break

        await churn.score_customers(db, tenant_id=tenant_id, customer_ids=ids)
        last_id = ids[-1]
        total += len(ids)

        await checkpoint(db, job_id=job["id"],
                         checkpoint={"last_customer_id": last_id, "scored": total})
        # Commit each batch so progress is durable — the whole point is that a
        # crash after this line keeps these rows and this checkpoint.
        await db.commit()

    return {"scored": total, "as_of_last_id": last_id}


@handler("measure_all")
async def _measure_all(db: AsyncSession, job: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute every measurable campaign's readout, resumably."""
    from app.services.flywheel import readout

    tenant_id = job["tenant_id"]
    cp = job["checkpoint"] or {}
    done = set(cp.get("done_campaigns", []))

    campaigns = [int(r[0]) for r in (await db.execute(
        text("""SELECT id FROM flywheel_campaigns
                 WHERE tenant_id = :t AND status = ANY(:st) ORDER BY id"""),
        {"t": tenant_id, "st": list(readout.MEASURABLE_STATUSES)},
    )).fetchall()]

    for cid in campaigns:
        if cid in done:
            continue
        await readout.compute_and_store(db, tenant_id=tenant_id, campaign_id=cid)
        done.add(cid)
        await checkpoint(db, job_id=job["id"],
                         checkpoint={"done_campaigns": sorted(done)})
        await db.commit()

    return {"measured": len(done), "campaigns": len(campaigns)}


@handler("shadow_score")
async def _shadow_score(db: AsyncSession, job: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.flywheel import shadow
    tenant_id = job["tenant_id"]
    result = await shadow.score_pass(db, tenant_id=tenant_id,
                                     limit=int(job["payload"].get("limit", 2000)))
    await db.commit()
    return {"scored": result["scored"]}


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def run_one(db_factory, *, worker_id: str,
                  kinds: Optional[List[str]] = None) -> Optional[str]:
    """Claim and run at most one job. Returns its kind, or None if idle.

    Each job gets a fresh session so one job's failure cannot poison another's
    transaction. The handler owns its own commits (it checkpoints as it goes);
    this frame only records the terminal status.
    """
    async with db_factory() as db:
        job = await claim(db, worker_id=worker_id, kinds=kinds)
        await db.commit()
    if job is None:
        return None

    kind = job["kind"]
    fn = _HANDLERS.get(kind)
    if fn is None:
        async with db_factory() as db:
            await fail(db, job_id=job["id"], error=f"no handler for kind '{kind}'",
                       attempts=job["max_attempts"], max_attempts=job["max_attempts"])
            await db.commit()
        return kind

    try:
        async with db_factory() as db:
            result = await fn(db, job)
            await complete(db, job_id=job["id"], result=result)
            await db.commit()
        logger.info("flywheel.job done id=%s kind=%s", job["id"], kind)
    except Exception as exc:
        logger.exception("flywheel.job failed id=%s kind=%s", job["id"], kind)
        async with db_factory() as db:
            await fail(db, job_id=job["id"], error=repr(exc),
                       attempts=job["attempts"], max_attempts=job["max_attempts"])
            await db.commit()
    return kind


async def worker_loop(db_factory, *, worker_id: str,
                      poll_seconds: float = 2.0,
                      reap_every: int = 15) -> None:
    """Process jobs forever, reaping stranded ones periodically.

    Never lets an exception escape — a job processor that dies silently is worse
    than no processor, because the queue fills and nobody notices.
    """
    logger.info("flywheel.job worker '%s' started", worker_id)
    ticks = 0
    while True:
        try:
            if ticks % reap_every == 0:
                async with db_factory() as db:
                    await reap(db)
                    await db.commit()
            ran = await run_one(db_factory, worker_id=worker_id)
            # Only sleep when idle; drain the queue as fast as it fills.
            if ran is None:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            logger.info("flywheel.job worker '%s' stopping", worker_id)
            raise
        except Exception:
            logger.exception("flywheel.job worker pass failed; continuing")
            await asyncio.sleep(poll_seconds)
        ticks += 1


# ---------------------------------------------------------------------------
# Introspection (for the API / health)
# ---------------------------------------------------------------------------

async def queue_stats(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    rows = (await db.execute(
        text("""SELECT status, COUNT(*) FROM flywheel_jobs
                 WHERE tenant_id = :t GROUP BY status"""),
        {"t": tenant_id},
    )).fetchall()
    by_status = {r[0]: int(r[1]) for r in rows}
    return {
        "queued": by_status.get("queued", 0),
        "running": by_status.get("running", 0),
        "succeeded": by_status.get("succeeded", 0),
        "failed": by_status.get("failed", 0),
        "dead": by_status.get("dead", 0),
        "dead_letter": by_status.get("dead", 0),
    }


async def get_job(db: AsyncSession, *, tenant_id: int, job_id: int) -> Optional[Dict[str, Any]]:
    row = (await db.execute(
        text("""SELECT id, kind, status, attempts, max_attempts, checkpoint,
                       result, last_error, created_at, finished_at, trace_id
                  FROM flywheel_jobs
                 WHERE tenant_id = :t AND id = :j"""),
        {"t": tenant_id, "j": job_id},
    )).fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]), "kind": row[1], "status": row[2],
        "attempts": int(row[3]), "max_attempts": int(row[4]),
        "checkpoint": row[5] or {}, "result": row[6], "last_error": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "finished_at": row[9].isoformat() if row[9] else None,
        "trace_id": row[10],
    }
