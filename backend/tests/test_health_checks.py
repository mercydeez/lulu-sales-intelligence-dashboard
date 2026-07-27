"""
E0-2 — health-check building blocks. Pure + mocked; no DB, no network, no Redis
server. Runs in the normal backend CI job.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services import health_checks as hc


NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Worker heartbeat parsing
# ---------------------------------------------------------------------------
def _hb(ts: datetime) -> str:
    return json.dumps({"service": "diagnostics-worker", "status": "ok",
                       "timestamp": ts.isoformat(), "pid": 1, "last_scan_status": "ok"})


def test_heartbeat_fresh_is_ok():
    out = hc.parse_worker_heartbeat(_hb(NOW - timedelta(seconds=10)), now=NOW, stale_after_seconds=120)
    assert out["status"] == "ok"
    assert out["age_seconds"] == 10.0
    assert out["last_scan_status"] == "ok"


def test_heartbeat_old_is_stale():
    out = hc.parse_worker_heartbeat(_hb(NOW - timedelta(seconds=300)), now=NOW, stale_after_seconds=120)
    assert out["status"] == "stale"
    assert out["age_seconds"] == 300.0


def test_heartbeat_missing_is_missing():
    out = hc.parse_worker_heartbeat(None, now=NOW)
    assert out["status"] == "missing"
    assert out["last_seen_at"] is None


def test_heartbeat_malformed_is_unknown_not_crash():
    assert hc.parse_worker_heartbeat("not json{{", now=NOW)["status"] == "unknown"
    assert hc.parse_worker_heartbeat(json.dumps({"no": "timestamp"}), now=NOW)["status"] == "unknown"
    # bytes are accepted too
    assert hc.parse_worker_heartbeat(_hb(NOW).encode(), now=NOW)["status"] == "ok"


# ---------------------------------------------------------------------------
# Status aggregation
# ---------------------------------------------------------------------------
def _checks(db="ok", redis="ok", migrations="current", worker="ok"):
    return {
        "database": {"status": db},
        "redis": {"status": redis},
        "migrations": {"status": migrations},
        "worker_heartbeat": {"status": worker},
    }


def test_all_core_ok_is_healthy():
    assert hc.aggregate_status(_checks()) == "healthy"


def test_db_error_is_unhealthy():
    assert hc.aggregate_status(_checks(db="error")) == "unhealthy"


def test_redis_error_is_unhealthy():
    assert hc.aggregate_status(_checks(redis="error")) == "unhealthy"


def test_stale_worker_is_degraded_not_unhealthy():
    assert hc.aggregate_status(_checks(worker="stale")) == "degraded"


def test_pending_migrations_is_degraded():
    assert hc.aggregate_status(_checks(migrations="pending")) == "degraded"


# ---------------------------------------------------------------------------
# Readiness policy
# ---------------------------------------------------------------------------
def test_prod_stale_worker_not_ready():
    checks = {**_checks(worker="stale"), "config": {"status": "ok"}}
    assert hc.is_ready(checks, "production") is False


def test_prod_missing_worker_not_ready():
    checks = {**_checks(worker="missing"), "config": {"status": "ok"}}
    assert hc.is_ready(checks, "production") is False


def test_dev_missing_worker_still_ready():
    checks = {**_checks(worker="missing"), "config": {"status": "ok"}}
    assert hc.is_ready(checks, "development") is True


def test_db_error_never_ready():
    checks = {**_checks(db="error"), "config": {"status": "ok"}}
    assert hc.is_ready(checks, "development") is False


def test_pending_migrations_not_ready():
    checks = {**_checks(migrations="pending"), "config": {"status": "ok"}}
    assert hc.is_ready(checks, "production") is False


# ---------------------------------------------------------------------------
# Backup manifest freshness (file-based, read-only)
# ---------------------------------------------------------------------------
class _S:
    """Minimal settings stand-in."""
    def __init__(self, **kw):
        self.backup_manifest_path = kw.get("path", "/nonexistent/latest.json")
        self.backup_stale_after_hours = kw.get("stale_hours", 30)
        self.environment = "testing"
        self.alert_enabled = kw.get("alert_enabled", False)
        self.alert_webhook_url = kw.get("alert_webhook_url", None)


def test_backup_missing_manifest_is_missing():
    out = hc.check_backup(_S(path="/nope/latest.json"), now=NOW)
    assert out["status"] == "missing"


def test_backup_fresh_manifest_is_ok(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"timestamp_utc": (NOW - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")}))
    out = hc.check_backup(_S(path=str(p)), now=NOW)
    assert out["status"] == "ok"
    assert out["age_seconds"] == pytest.approx(3600, abs=2)


def test_backup_old_manifest_is_stale(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"timestamp_utc": (NOW - timedelta(hours=40)).strftime("%Y%m%dT%H%M%SZ")}))
    out = hc.check_backup(_S(path=str(p), stale_hours=30), now=NOW)
    assert out["status"] == "stale"


# ---------------------------------------------------------------------------
# Async probes with stubs (no real DB/Redis)
# ---------------------------------------------------------------------------
class _FakeConn:
    async def execute(self, q):
        return None


class _FakeCM:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def connect(self):
        return _FakeCM()


class _BrokenEngine:
    def connect(self):
        raise RuntimeError("db down")


class _FakeRedis:
    async def ping(self):
        return True


async def test_check_database_ok_and_error():
    assert (await hc.check_database(_FakeEngine()))["status"] == "ok"
    assert (await hc.check_database(_BrokenEngine()))["status"] == "error"


async def test_check_redis_ok_and_none():
    assert (await hc.check_redis(_FakeRedis()))["status"] == "ok"
    assert (await hc.check_redis(None))["status"] == "error"
