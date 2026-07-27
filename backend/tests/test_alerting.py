"""
E0-2 — generic webhook alerting. Pure + mocked HTTP/Redis; alerting is OFF by
default so NO test touches the network unless it injects a fake client.
"""
from types import SimpleNamespace

import pytest

from app.services import alerting


def _settings(**kw):
    return SimpleNamespace(
        alert_enabled=kw.get("enabled", True),
        alert_webhook_url=kw.get("url", "https://hook.example/xyz-secret"),
        alert_min_severity=kw.get("min_severity", "critical"),
        alert_dedup_ttl_seconds=kw.get("ttl", 300),
        alert_environment=kw.get("alert_env", None),
        environment=kw.get("environment", "production"),
        alert_webhook_timeout_seconds=kw.get("timeout", 5),
    )


class _FakeResp:
    def __init__(self, code=200):
        self.status_code = code


class _FakeClient:
    def __init__(self, code=200, raise_exc=None):
        self.code = code
        self.raise_exc = raise_exc
        self.calls = []

    async def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.raise_exc:
            raise self.raise_exc
        return _FakeResp(self.code)


class _FakeRedis:
    """Redis stub honouring SET NX EX semantics for dedup."""
    def __init__(self):
        self.store = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


# ---------------------------------------------------------------------------
# Pure config / severity / payload
# ---------------------------------------------------------------------------
def test_severity_threshold():
    assert alerting.severity_meets_threshold("critical", "critical") is True
    assert alerting.severity_meets_threshold("high", "critical") is False
    assert alerting.severity_meets_threshold("critical", "high") is True
    assert alerting.severity_meets_threshold("bogus", "critical") is False


def test_alerting_status_disabled_by_default():
    st = alerting.alerting_status(_settings(enabled=False))
    assert st == {"status": "missing", "provider": "none"}


def test_alerting_status_configured_never_leaks_url():
    st = alerting.alerting_status(_settings())
    assert st == {"status": "configured", "provider": "webhook"}
    assert "hook.example" not in str(st)  # URL never present


def test_build_payload_has_fields_and_no_url():
    p = alerting.build_alert_payload(
        title="t", message="m", severity="critical", environment="production",
        check="c", status="s", request_id="req-1",
    )
    for k in ("service", "environment", "severity", "title", "message", "check",
              "status", "runbook", "request_id", "timestamp"):
        assert k in p
    assert "hook.example" not in str(p)


# ---------------------------------------------------------------------------
# send_alert behaviour
# ---------------------------------------------------------------------------
async def test_disabled_by_default_sends_nothing():
    # Default app settings have alert_enabled=False -> no network, no client used.
    res = await alerting.send_alert(title="t", message="m", settings=_settings(enabled=False))
    assert res == {"sent": False, "reason": "disabled"}


async def test_below_min_severity_is_skipped():
    res = await alerting.send_alert(
        title="t", message="m", severity="high",
        settings=_settings(min_severity="critical"), redis=_FakeRedis(), http_client=_FakeClient(),
    )
    assert res["sent"] is False and res["reason"] == "below_severity"


async def test_sends_expected_payload_to_client():
    client = _FakeClient()
    res = await alerting.send_alert(
        title="DB down", message="database unreachable", severity="critical",
        check="database", status="error",
        settings=_settings(), redis=_FakeRedis(), http_client=client,
    )
    assert res["sent"] is True
    assert len(client.calls) == 1
    sent = client.calls[0]["json"]
    assert sent["title"] == "DB down" and sent["check"] == "database"
    assert sent["environment"] == "production"


async def test_dedup_suppresses_repeat_then_allows_after_window():
    redis = _FakeRedis()
    client = _FakeClient()
    s = _settings()
    first = await alerting.send_alert(title="X", message="m", check="database", status="error",
                                      settings=s, redis=redis, http_client=client)
    second = await alerting.send_alert(title="X", message="m", check="database", status="error",
                                       settings=s, redis=redis, http_client=client)
    assert first["sent"] is True
    assert second["sent"] is False and second["reason"] == "deduplicated"
    assert len(client.calls) == 1  # only the first actually POSTed
    # Simulate TTL expiry (Redis EX would drop the key) -> sends again.
    redis.store.clear()
    third = await alerting.send_alert(title="X", message="m", check="database", status="error",
                                      settings=s, redis=redis, http_client=client)
    assert third["sent"] is True
    assert len(client.calls) == 2


async def test_webhook_error_does_not_crash():
    client = _FakeClient(raise_exc=TimeoutError("slow"))
    res = await alerting.send_alert(
        title="t", message="m", settings=_settings(), redis=_FakeRedis(), http_client=client,
    )
    assert res["sent"] is False and res["reason"] == "webhook_error"


async def test_dedup_falls_back_when_redis_down():
    # redis=None (no client) -> process-local dedup still prevents a storm.
    client = _FakeClient()
    s = _settings(ttl=300)
    a = await alerting.send_alert(title="unique-title-1", message="m", check="redis", status="error",
                                  settings=s, redis=None, http_client=client)
    b = await alerting.send_alert(title="unique-title-1", message="m", check="redis", status="error",
                                  settings=s, redis=None, http_client=client)
    assert a["sent"] is True
    assert b["sent"] is False and b["reason"] == "deduplicated"
