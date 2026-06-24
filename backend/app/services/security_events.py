"""
Security event pipeline (Security Operations panel).

`record_event(...)` is the single entry point every security-relevant code path
calls. It is deliberately:
  * **best-effort** — wrapped so a logging failure can NEVER break a real request;
  * **owner-written** — inserts on the owner session so Row-Level Security can never
    *suppress* a security log (a security control that an attacker could silence by
    triggering RLS would be worthless);
  * **tenant-stamped** — every row carries tenant_id, so the read path (app_rw under
    RLS) shows each tenant only its own events;
  * **live** — also published to the Redis `security:stream` channel for the SSE feed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.config import logger, get_settings, request_id_ctx

# Default severity per event type. Anything not listed defaults to "medium".
_SEVERITY: Dict[str, str] = {
    "login_failed": "medium",
    "account_locked": "high",
    "permission_denied": "high",
    "role_denied": "high",
    "rate_limited": "medium",
    "csrf_failed": "high",
    "token_invalid": "medium",
    "token_blacklisted": "high",
    "token_tenant_mismatch": "critical",
    "api_key_invalid": "medium",
    "api_key_created": "low",
    "api_key_revoked": "medium",
    "password_changed": "low",
    "signup": "info",
}

# Sensitive-but-legitimate actions go in the "audit" lane; everything else is a "threat".
_AUDIT_TYPES = {"api_key_created", "api_key_revoked", "password_changed", "signup"}


def client_ip(request) -> Optional[str]:
    """Client IP, honoring X-Forwarded-For only behind a trusted proxy (mirrors
    the rate limiter — a spoofed header must not poison the security log either)."""
    if request is None:
        return None
    try:
        if get_settings().trust_proxy_headers:
            fwd = request.headers.get("X-Forwarded-For")
            if fwd:
                return fwd.split(",")[0].strip()
            real = request.headers.get("X-Real-IP")
            if real:
                return real
        return request.client.host if request.client else None
    except Exception:
        return None


async def record_event(
    event_type: str,
    severity: Optional[str] = None,
    *,
    category: Optional[str] = None,
    tenant_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    ip_address: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    detail: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    request=None,
) -> None:
    """Persist a security event (owner session) and publish it live. Never raises."""
    try:
        import json
        from app.services.database import async_session, tenant_context

        sev = severity or _SEVERITY.get(event_type, "medium")
        cat = category or ("audit" if event_type in _AUDIT_TYPES else "threat")

        if tenant_id is None:
            try:
                tenant_id = tenant_context.get()
            except Exception:
                tenant_id = 1

        if request is not None:
            ip_address = ip_address or client_ip(request)
            method = method or getattr(request, "method", None)
            try:
                path = path or request.url.path
            except Exception:
                pass
        try:
            req_id = request_id_ctx.get()
        except Exception:
            req_id = None

        payload = {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "severity": sev,
            "category": cat,
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "ip_address": ip_address,
            "method": method,
            "path": path,
            "detail": detail,
            "evidence": evidence or {},
            "request_id": req_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }

        # WRITE on the owner session so RLS can never suppress the log.
        async with async_session() as s:
            await s.execute(text("""
                INSERT INTO security_events
                  (tenant_id, event_type, severity, category, actor_user_id,
                   actor_email, ip_address, method, path, detail, evidence, request_id)
                VALUES
                  (:tenant_id, :event_type, :severity, :category, :actor_user_id,
                   :actor_email, :ip_address, :method, :path, :detail,
                   CAST(:evidence AS JSONB), :request_id)
            """), {**payload, "evidence": json.dumps(evidence or {})})
            await s.commit()

        # PUBLISH live (best-effort) for the SSE feed.
        try:
            from app.services.redis_client import publish_security_event
            await publish_security_event(payload)
        except Exception:
            pass

        # ALERT (best-effort): email / webhook for qualifying-severity events.
        try:
            from app.services.security_notify import dispatch as alert_dispatch
            await alert_dispatch(payload)
        except Exception:
            pass

        if sev in ("high", "critical"):
            logger.warning(f"🛡️ SECURITY [{sev}] {event_type}: {detail or ''} (ip={ip_address})")
    except Exception as e:
        # A security log must never break the request it is observing.
        logger.debug(f"record_event skipped ({event_type}): {e}")
