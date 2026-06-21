"""
Job queue (producer side) — Foresia.

FastAPI is the *producer*: it enqueues durable jobs into Redis-backed BullMQ
queues. The Node `worker/` service is the *consumer* that processes them
(webhook delivery with retries/backoff, proactive risk scans, digests).

Why BullMQ (a Node library) from Python: the official `bullmq` PyPI client
speaks the exact same Redis protocol and default key prefix (`bull`) as the
Node library, so a Python producer and a Node consumer interoperate over the
shared Redis with no glue. Heavy Python-only ML (forecast training) stays
in-process; the queue owns I/O-bound work, which is what it's good at.

Everything degrades gracefully: if `USE_QUEUE` is off or enqueue fails, the
caller falls back to its in-process path. Enqueuing never raises to the
request/stream path.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import get_settings, logger

settings = get_settings()

# Queue names — keep in sync with worker/src/queues.ts
Q_WEBHOOK = "webhook"
Q_RISK_SCAN = "risk-scan"
Q_REPORT = "report"
Q_DIGEST = "digest"

# Default per-job reliability options (BullMQ JobOptions). Exponential backoff
# with a capped retry count; keep recent completed/failed jobs for observability.
DEFAULT_JOB_OPTS: Dict[str, Any] = {
    "attempts": 5,
    "backoff": {"type": "exponential", "delay": 2000},
    "removeOnComplete": 1000,
    "removeOnFail": 5000,
}

# Lazily-created Queue instances, one per queue name (each holds a Redis conn).
_queues: Dict[str, Any] = {}


def _get_queue(name: str):
    """Get-or-create a BullMQ Queue bound to the shared Redis. Returns None if
    the bullmq client isn't importable (lets callers fall back cleanly)."""
    q = _queues.get(name)
    if q is not None:
        return q
    try:
        from bullmq import Queue
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("bullmq client unavailable (%s); queue disabled", e)
        return None
    q = Queue(name, {"connection": settings.redis_url})
    _queues[name] = q
    return q


async def enqueue(
    queue_name: str,
    job_name: str,
    data: Dict[str, Any],
    *,
    opts: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Enqueue a job. Returns the BullMQ job id, or None if the queue is
    disabled/unavailable (caller should then run the in-process fallback)."""
    if not settings.use_queue:
        return None
    queue = _get_queue(queue_name)
    if queue is None:
        return None
    try:
        job = await queue.add(job_name, data, opts or DEFAULT_JOB_OPTS)
        logger.info("enqueued %s/%s id=%s", queue_name, job_name, job.id)
        return job.id
    except Exception as e:
        logger.warning("enqueue %s/%s failed: %s", queue_name, job_name, e)
        return None


async def close_queues() -> None:
    """Close all open Queue connections (call on shutdown)."""
    for name, q in list(_queues.items()):
        try:
            await q.close()
        except Exception:
            pass
        _queues.pop(name, None)
