"""
Generic webhook alerting (E0-2).

Provider-agnostic on purpose: this module POSTs a JSON alert to ONE configured
webhook (`ALERT_WEBHOOK_URL`). Route that webhook to a founder phone/SMS/WhatsApp
through Better Stack, Healthchecks.io, PagerDuty, Twilio, or Slack — no provider
is hardcoded and no phone number lives in the code.

Safety properties:
  * OFF by default. Nothing is sent unless `ALERT_ENABLED=true` AND a webhook URL
    is configured — so tests and local dev never call the network.
  * Best-effort. A webhook timeout/error is logged and swallowed; it never
    propagates into a health endpoint or the request path.
  * Deduplicated. The same failing check does not spam an alert on every health
    poll — a Redis key (with a process-local fallback) suppresses repeats within
    `ALERT_DEDUP_TTL_SECONDS`.
  * Secret-safe. The webhook URL is never returned to any caller or logged in full.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings, logger

# Severity ranking (higher = more urgent). Used for the min-severity gate.
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# Process-local dedup fallback when Redis is unavailable: key -> monotonic expiry.
_LOCAL_DEDUP: dict[str, float] = {}


def severity_meets_threshold(severity: str, min_severity: str) -> bool:
    """True when `severity` is at least as urgent as `min_severity`. Unknown
    severities are treated as the lowest rank (won't pass a critical gate)."""
    return _SEVERITY_RANK.get((severity or "").lower(), -1) >= _SEVERITY_RANK.get(
        (min_severity or "critical").lower(), _SEVERITY_RANK["critical"]
    )


def _dedup_key(title: str, check: Optional[str], status: Optional[str], severity: str) -> str:
    raw = f"{severity}|{check or ''}|{status or ''}|{title}"
    return "alert:dedup:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def build_alert_payload(
    *,
    title: str,
    message: str,
    severity: str,
    environment: str,
    service: str = "retail-iq-backend",
    check: Optional[str] = None,
    status: Optional[str] = None,
    runbook: Optional[str] = None,
    request_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict:
    """The JSON body POSTed to the webhook. Pure + deterministic (timestamp
    injectable for tests). Contains NO secret — never the webhook URL."""
    return {
        "service": service,
        "environment": environment,
        "severity": severity,
        "title": title,
        "message": message,
        "check": check,
        "status": status,
        "runbook": runbook or "docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md",
        "request_id": request_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }


def alerting_status(settings=None) -> dict:
    """Config-only view of the alert path for health payloads. NEVER includes the
    URL — only whether a provider is wired."""
    s = settings or get_settings()
    configured = bool(s.alert_enabled and s.alert_webhook_url)
    return {
        "status": "configured" if configured else "missing",
        "provider": "webhook" if configured else "none",
    }


async def _dedup_allows(redis, key: str, ttl: int) -> bool:
    """True if this alert may be sent (first time within the TTL window). Uses
    Redis SET NX EX; falls back to a process-local map if Redis is unavailable so
    a Redis outage still can't cause an alert storm."""
    if redis is not None:
        try:
            # nx=True => only set if absent; returns True on first, None on repeat.
            ok = await redis.set(key, "1", nx=True, ex=ttl)
            return bool(ok)
        except Exception as e:
            logger.warning(f"alert dedup via Redis failed ({e}); using process-local fallback")
    now = time.monotonic()
    exp = _LOCAL_DEDUP.get(key)
    if exp and exp > now:
        return False
    _LOCAL_DEDUP[key] = now + ttl
    return True


async def send_alert(
    *,
    title: str,
    message: str,
    severity: str = "critical",
    check: Optional[str] = None,
    status: Optional[str] = None,
    runbook: Optional[str] = None,
    request_id: Optional[str] = None,
    settings=None,
    redis=None,
    http_client=None,
) -> dict:
    """Emit one alert through the configured webhook. Best-effort and safe:
    returns a small result dict and NEVER raises. `redis` and `http_client` can be
    injected for tests (no real network otherwise).

    Returns e.g. {"sent": True} or {"sent": False, "reason": "disabled"|
    "below_severity"|"deduplicated"|"webhook_error"}.
    """
    s = settings or get_settings()

    if not (s.alert_enabled and s.alert_webhook_url):
        logger.debug("alert suppressed: alerting disabled or no webhook configured")
        return {"sent": False, "reason": "disabled"}

    if not severity_meets_threshold(severity, s.alert_min_severity):
        return {"sent": False, "reason": "below_severity"}

    # Resolve a Redis client if not injected (best-effort; None is fine).
    if redis is None:
        try:
            from app.services.redis_client import get_redis
            redis = await get_redis()
        except Exception:
            redis = None

    key = _dedup_key(title, check, status, severity)
    if not await _dedup_allows(redis, key, int(s.alert_dedup_ttl_seconds)):
        return {"sent": False, "reason": "deduplicated"}

    payload = build_alert_payload(
        title=title, message=message, severity=severity,
        environment=(s.alert_environment or s.environment),
        check=check, status=status, runbook=runbook, request_id=request_id,
    )

    timeout = float(s.alert_webhook_timeout_seconds or 5)
    try:
        if http_client is not None:
            resp = await http_client.post(s.alert_webhook_url, json=payload, timeout=timeout)
        else:
            import httpx
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(s.alert_webhook_url, json=payload)
        code = getattr(resp, "status_code", 0)
        if 200 <= int(code) < 300:
            logger.info(f"alert delivered ({severity}) check={check} status={status}")
            return {"sent": True, "status_code": int(code)}
        logger.warning(f"alert webhook returned HTTP {code}")
        return {"sent": False, "reason": "webhook_error", "status_code": int(code)}
    except Exception as e:
        # Never let a webhook failure surface into the health/request path.
        logger.warning(f"alert webhook delivery failed: {type(e).__name__}")
        return {"sent": False, "reason": "webhook_error"}
