"""
Health-check building blocks (E0-2).

Pure, unit-testable helpers (heartbeat parsing, status aggregation, readiness)
plus the async subsystem probes (DB, Redis, migrations, worker heartbeat, backup
manifest, alerting config). `full_health()` assembles the standard payload that
`/health/deep` returns. No secrets ever appear in the output (the webhook URL is
never included — only whether a provider is configured).

Status policy
-------------
* healthy   — DB, Redis, migrations, AND worker heartbeat are all OK.
* degraded  — core deps serve but something optional/soft is off: worker stale/
              missing, migrations pending, or backup/alerting not configured.
* unhealthy — a core dependency (DB or Redis) is down.

Readiness (`/health/ready`) is STRICTER than the status field: in production it
also requires a FRESH worker heartbeat and current migrations. In dev/test a
missing worker is reported honestly but does not block readiness.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.config import get_settings, logger

WORKER_HEARTBEAT_KEY = "health:worker:diagnostics"

# Backup manifest timestamp format written by scripts/backup-postgres.sh.
_MANIFEST_TS_FMT = "%Y%m%dT%H%M%SZ"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def parse_worker_heartbeat(raw, now: Optional[datetime] = None, stale_after_seconds: int = 120) -> dict:
    """Interpret the worker's Redis heartbeat value.

    raw: the JSON string/bytes/dict stored at WORKER_HEARTBEAT_KEY, or None.
      * None                 -> status "missing"
      * fresh timestamp      -> status "ok"
      * old timestamp        -> status "stale"
      * malformed/unparsable  -> status "unknown" (never raises)
    """
    now = now or _now()
    base = {
        "status": "missing",
        "last_seen_at": None,
        "age_seconds": None,
        "stale_after_seconds": int(stale_after_seconds),
    }
    if raw is None:
        return base
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        data = raw if isinstance(raw, dict) else json.loads(raw)
        ts_str = data.get("timestamp")
        if not ts_str:
            return {**base, "status": "unknown"}
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
        status = "ok" if age <= stale_after_seconds else "stale"
        out = {
            "status": status,
            "last_seen_at": ts.isoformat(),
            "age_seconds": round(age, 1),
            "stale_after_seconds": int(stale_after_seconds),
        }
        # Surface useful, non-secret scan/measure context when present.
        for k in ("service", "pid", "version", "last_scan_status", "last_scan_finished_at",
                  "last_measure_status", "last_measure_finished_at"):
            if k in data:
                out[k] = data[k]
        return out
    except Exception:
        return {**base, "status": "unknown"}


def aggregate_status(checks: dict) -> str:
    """Roll individual check results up into healthy | degraded | unhealthy."""
    db = (checks.get("database") or {}).get("status")
    redis = (checks.get("redis") or {}).get("status")
    migrations = (checks.get("migrations") or {}).get("status")
    worker = (checks.get("worker_heartbeat") or {}).get("status")

    if db != "ok" or redis != "ok":
        return "unhealthy"
    if migrations == "current" and worker == "ok":
        return "healthy"
    return "degraded"


def is_ready(checks: dict, environment: str, expect_worker: bool = True) -> bool:
    """Readiness decision. Strict in production (fresh worker + current
    migrations); lenient about a missing worker in dev/test."""
    db = (checks.get("database") or {}).get("status")
    redis = (checks.get("redis") or {}).get("status")
    migrations = (checks.get("migrations") or {}).get("status")
    worker = (checks.get("worker_heartbeat") or {}).get("status")
    config_ok = (checks.get("config") or {}).get("status", "ok") == "ok"

    if db != "ok" or redis != "ok" or not config_ok:
        return False
    if migrations != "current":
        return False
    production = environment in ("production", "staging")
    if production and expect_worker:
        # In prod the worker must be beating; missing/stale/unknown => not ready.
        return worker == "ok"
    return True


# ---------------------------------------------------------------------------
# Async subsystem probes
# ---------------------------------------------------------------------------
async def check_database(engine) -> dict:
    start = time.monotonic()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        logger.error(f"health: database check failed: {e}")
        return {"status": "error"}


async def check_redis(redis) -> dict:
    start = time.monotonic()
    try:
        if redis is None:
            return {"status": "error"}
        await redis.ping()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        logger.error(f"health: redis check failed: {e}")
        return {"status": "error"}


async def check_migrations() -> dict:
    try:
        from app.services.migration_runner import pending_migrations
        pending = await pending_migrations()
        if not pending:
            return {"status": "current"}
        return {"status": "pending", "pending_count": len(pending)}
    except Exception:
        return {"status": "unknown"}


async def check_worker_heartbeat(redis, now: Optional[datetime] = None, stale_after_seconds: Optional[int] = None) -> dict:
    s = get_settings()
    stale_after = int(stale_after_seconds if stale_after_seconds is not None else s.worker_heartbeat_stale_seconds)
    raw = None
    try:
        if redis is not None:
            raw = await redis.get(WORKER_HEARTBEAT_KEY)
    except Exception:
        return parse_worker_heartbeat(None, now, stale_after) | {"status": "unknown"}
    return parse_worker_heartbeat(raw, now, stale_after)


# The `singletons` sidecar (app/commands/singletons.py) writes this key. It is
# reported in /health/deep for visibility but does NOT gate readiness: the API
# serves fine when the sidecar is down — only the generator/partition-maintenance
# stop, which is an operational concern, not an API outage.
SINGLETONS_HEARTBEAT_KEY = "health:worker:singletons"


async def check_singletons_heartbeat(redis, now: Optional[datetime] = None, stale_after_seconds: Optional[int] = None) -> dict:
    s = get_settings()
    stale_after = int(stale_after_seconds if stale_after_seconds is not None else s.worker_heartbeat_stale_seconds)
    raw = None
    try:
        if redis is not None:
            raw = await redis.get(SINGLETONS_HEARTBEAT_KEY)
    except Exception:
        return parse_worker_heartbeat(None, now, stale_after) | {"status": "unknown"}
    return parse_worker_heartbeat(raw, now, stale_after)


def check_backup(settings=None, now: Optional[datetime] = None) -> dict:
    """READ-ONLY freshness read of the E0-1 backup manifest. Never writes/creates
    a backup — just reports what E0-1 produced."""
    s = settings or get_settings()
    now = now or _now()
    path = s.backup_manifest_path
    out = {"status": "missing", "manifest_path": path, "latest_backup_at": None, "age_seconds": None}
    try:
        if not path or not os.path.exists(path):
            return out
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts_raw = data.get("timestamp_utc") or data.get("timestamp") or data.get("created_at")
        if not ts_raw:
            return {**out, "status": "unknown"}
        try:
            ts = datetime.strptime(str(ts_raw), _MANIFEST_TS_FMT).replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
        stale = age > s.backup_stale_after_hours * 3600
        return {
            "status": "stale" if stale else "ok",
            "manifest_path": path,
            "latest_backup_at": ts.isoformat(),
            "age_seconds": round(age, 1),
        }
    except Exception:
        return {**out, "status": "unknown"}


def _residency_check(settings=None) -> dict:
    """E5-3 residency posture for /health/deep. Lazy import to avoid any cycle."""
    try:
        from app.services.data_residency import residency_health_check
        return residency_health_check(settings)
    except Exception:
        return {"status": "unknown"}


def check_alerting(settings=None) -> dict:
    """Config-only alerting status. Imports lazily to avoid a heavy import at
    module load. NEVER includes the webhook URL."""
    from app.services.alerting import alerting_status
    return alerting_status(settings)


async def full_health(engine, redis, settings=None, now: Optional[datetime] = None) -> dict:
    """Assemble the standard E0-2 health payload for /health/deep."""
    s = settings or get_settings()
    now = now or _now()

    checks = {
        "database": await check_database(engine),
        "redis": await check_redis(redis),
        "migrations": await check_migrations(),
        "worker_heartbeat": await check_worker_heartbeat(redis, now, s.worker_heartbeat_stale_seconds),
        # Informational only — see aggregate_status/is_ready, which do NOT read it.
        "singletons_heartbeat": await check_singletons_heartbeat(redis, now, s.worker_heartbeat_stale_seconds),
        "backup": check_backup(s, now),
        "alerting": check_alerting(s),
        "data_residency": _residency_check(s),
    }
    return {
        "status": aggregate_status(checks),
        "timestamp": _iso(now),
        "environment": s.environment,
        "checks": checks,
    }
