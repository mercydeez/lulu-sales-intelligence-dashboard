"""
Security Operations API — real-time security telemetry for the SOC panel.

Reads `security_events` (migration 030) on the request path (app_rw under RLS), so
every endpoint is automatically scoped to the caller's tenant; an explicit
`tenant_id` filter is also applied as defense in depth. Admin-only.

  GET  /api/security/summary  — windowed KPIs (severity/type counts, threats, IPs)
  GET  /api/security/events   — filterable, paginated event list
  GET  /api/security/kpi      — compact posture tile for the main dashboard
The live feed is the SSE endpoint /stream/security (routes/stream.py).
"""
import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.services.database import get_db
from app.auth_deps import get_current_user

router = APIRouter()

# Which event types count as active threats vs blocked-attack noise.
THREAT_TYPES = (
    "permission_denied", "role_denied", "csrf_failed", "token_blacklisted",
    "token_tenant_mismatch", "api_key_invalid", "rate_limited",
    "login_failed", "account_locked", "token_invalid",
)
BLOCKED_TYPES = (
    "permission_denied", "role_denied", "csrf_failed", "rate_limited",
    "token_blacklisted", "token_invalid", "token_tenant_mismatch", "api_key_invalid",
)


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin", "regional_manager"):
        raise HTTPException(status_code=403, detail="Admin role required for security data")


def _tenant(user: dict) -> int:
    return user.get("tenant_id") or 1


@router.get("/summary")
async def security_summary(
    hours: int = Query(24, ge=1, le=720),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Windowed security KPIs for the authenticated tenant."""
    _require_admin(user)
    tid = _tenant(user)
    p = {"tid": tid, "hours": hours}
    base = "FROM security_events WHERE tenant_id = :tid AND occurred_at >= now() - make_interval(hours => :hours)"

    by_sev = {r.severity: r.n for r in (await db.execute(text(
        f"SELECT severity, COUNT(*) AS n {base} GROUP BY severity"), p)).mappings().all()}
    by_type = {r.event_type: r.n for r in (await db.execute(text(
        f"SELECT event_type, COUNT(*) AS n {base} GROUP BY event_type ORDER BY n DESC"), p)).mappings().all()}

    total = sum(by_sev.values())
    threats_active = (by_sev.get("critical", 0) or 0) + (by_sev.get("high", 0) or 0)
    failed_logins = (by_type.get("login_failed", 0) or 0) + (by_type.get("account_locked", 0) or 0)
    blocked = sum(by_type.get(t, 0) or 0 for t in BLOCKED_TYPES)

    distinct_ips = (await db.execute(text(
        f"SELECT COUNT(DISTINCT ip_address) AS n {base} AND ip_address IS NOT NULL"), p)).scalar() or 0

    top_ips = [dict(r) for r in (await db.execute(text(
        f"SELECT ip_address, COUNT(*) AS events {base} AND ip_address IS NOT NULL "
        "GROUP BY ip_address ORDER BY events DESC LIMIT 5"), p)).mappings().all()]

    # Simple, explainable posture score: start at 100, subtract weighted penalties.
    score = 100 - min(100, (by_sev.get("critical", 0) or 0) * 25
                       + (by_sev.get("high", 0) or 0) * 8
                       + (by_sev.get("medium", 0) or 0) * 2)
    status = "alert" if score < 60 else ("watch" if score < 90 else "ok")

    return {
        "window_hours": hours,
        "total_events": total,
        "by_severity": {s: by_sev.get(s, 0) for s in ("critical", "high", "medium", "low", "info")},
        "by_type": by_type,
        "threats_active": threats_active,
        "failed_logins": failed_logins,
        "blocked_requests": blocked,
        "distinct_ips": distinct_ips,
        "top_ips": top_ips,
        "posture_score": score,
        "status": status,
    }


@router.get("/events")
async def security_events(
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    category: Optional[str] = None,
    hours: int = Query(168, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Filterable, paginated security event feed for the authenticated tenant."""
    _require_admin(user)
    where = ["tenant_id = :tid", "occurred_at >= now() - make_interval(hours => :hours)"]
    p: dict = {"tid": _tenant(user), "hours": hours, "limit": limit}
    if severity in ("critical", "high", "medium", "low", "info"):
        where.append("severity = :severity"); p["severity"] = severity
    if event_type:
        where.append("event_type = :etype"); p["etype"] = event_type
    if category in ("threat", "audit"):
        where.append("category = :cat"); p["cat"] = category
    rows = (await db.execute(text(
        "SELECT id, occurred_at, event_type, severity, category, actor_email, "
        "ip_address, method, path, detail, evidence "
        f"FROM security_events WHERE {' AND '.join(where)} "
        "ORDER BY occurred_at DESC LIMIT :limit"), p)).mappings().all()
    return {"data": [dict(r) for r in rows], "count": len(rows)}


@router.get("/events/export")
async def export_events(
    category: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    hours: int = Query(720, ge=1, le=8760),
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the tenant's audit/security events as CSV or JSON (compliance/PDPL
    evidence). Tenant-scoped under RLS; defaults to the audit lane window of 30 days.
    Sensitive values are never logged into these events, so the export is safe."""
    _require_admin(user)
    where = ["tenant_id = :tid", "occurred_at >= now() - make_interval(hours => :hours)"]
    p: dict = {"tid": _tenant(user), "hours": hours}
    if category in ("threat", "audit"):
        where.append("category = :cat"); p["cat"] = category
    if severity in ("critical", "high", "medium", "low", "info"):
        where.append("severity = :severity"); p["severity"] = severity
    if event_type:
        where.append("event_type = :etype"); p["etype"] = event_type
    rows = (await db.execute(text(
        "SELECT occurred_at, event_type, severity, category, actor_email, "
        "ip_address, method, path, detail, evidence "
        f"FROM security_events WHERE {' AND '.join(where)} "
        "ORDER BY occurred_at DESC LIMIT 10000"), p)).mappings().all()

    # E8-3: meter the export so the `exports` dimension reflects reality. NOT
    # enforced — this is compliance evidence an admin may owe a regulator, and a
    # billing meter is not a reason to withhold it (same stance as /data-rights/export).
    from app.services.usage_metering import record_usage
    await record_usage(_tenant(user), "export",
                       metadata={"kind": "security_events", "format": fmt, "rows": len(rows)})

    label = category or "events"
    if fmt == "json":
        body = json.dumps([{**dict(r), "occurred_at": r["occurred_at"].isoformat()}
                           for r in rows], default=str, indent=2)
        return StreamingResponse(iter([body]), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="audit-{label}.json"'})

    buf = io.StringIO()
    cols = ["occurred_at", "event_type", "severity", "category", "actor_email",
            "ip_address", "method", "path", "detail"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r["occurred_at"].isoformat()] + [r[c] for c in cols[1:]])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{label}.csv"'})


@router.get("/kpi")
async def security_kpi(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compact 24h posture tile for the main dashboard KPI grid."""
    _require_admin(user)
    tid = _tenant(user)
    p = {"tid": tid}
    base = "FROM security_events WHERE tenant_id = :tid AND occurred_at >= now() - INTERVAL '24 hours'"
    sev = {r.severity: r.n for r in (await db.execute(text(
        f"SELECT severity, COUNT(*) AS n {base} GROUP BY severity"), p)).mappings().all()}
    threats = (sev.get("critical", 0) or 0) + (sev.get("high", 0) or 0)
    score = 100 - min(100, (sev.get("critical", 0) or 0) * 25
                      + (sev.get("high", 0) or 0) * 8 + (sev.get("medium", 0) or 0) * 2)
    return {
        "posture_score": score,
        "threats_active": threats,
        "events_24h": sum(sev.values()),
        "status": "alert" if score < 60 else ("watch" if score < 90 else "ok"),
    }
