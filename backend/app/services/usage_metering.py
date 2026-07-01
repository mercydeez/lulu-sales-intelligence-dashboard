"""
Billing-period usage metering + soft quotas (UAE SaaS Phase 3).

Moves metering from the Track-5 *lifetime* totals to the CURRENT BILLING PERIOD —
the calendar month in Asia/Dubai. Events are appended to `usage_events` (migration
043); the summary counts them in-period and meters them against per-plan limits.

Enforcement is SOFT and OFF by default (meter now, enforce when the operator turns
it on) so the demo/MVP and existing tests are unaffected: set ENFORCE_USAGE_QUOTAS=
true to make `check_quota` return not-allowed once a non-unlimited limit is exceeded.
Enterprise (None limit) is always unlimited. UAE manual/enterprise plans stay custom.

LEGAL/BILLING: this is metering, not invoicing. No money moves here.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

try:  # py3.9+ stdlib; Asia/Dubai is a fixed +04:00 (no DST) so a fallback is exact.
    from zoneinfo import ZoneInfo
    _DUBAI = ZoneInfo("Asia/Dubai")
except Exception:  # pragma: no cover - tzdata missing
    _DUBAI = timezone(timedelta(hours=4))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.plan_limits import _meter, limits_for_plan  # reuse the meter shape

# Event types that are metered per billing period.
METERED_EVENTS = ("sage_messages", "forecast_jobs", "exports", "imports", "api_requests")

# Map a recorded event_type (singular) to its metered dimension (plural key).
EVENT_TO_DIM = {
    "sage_message": "sage_messages",
    "forecast_job": "forecast_jobs",
    "export": "exports",
    "import": "imports",
    "api_request": "api_requests",
}

# Per-plan billing-period limits for event-based usage. `None` => unlimited.
# Separate from plan_limits.PLAN_LIMITS (which holds point-in-time users/api_keys).
USAGE_LIMITS: Dict[str, Dict[str, Optional[int]]] = {
    "free":       {"sage_messages": 100,    "forecast_jobs": 50,    "exports": 10,   "imports": 20,   "api_requests": 10_000},
    "starter":    {"sage_messages": 2_000,  "forecast_jobs": 500,   "exports": 100,  "imports": 200,  "api_requests": 100_000},
    "growth":     {"sage_messages": 20_000, "forecast_jobs": 5_000, "exports": 1_000,"imports": 2_000,"api_requests": 1_000_000},
    "enterprise": {"sage_messages": None,   "forecast_jobs": None,  "exports": None, "imports": None, "api_requests": None},
}
_DEFAULT_PLAN = "free"


def usage_limits_for_plan(plan: Optional[str]) -> Dict[str, Optional[int]]:
    return USAGE_LIMITS.get((plan or "").lower(), USAGE_LIMITS[_DEFAULT_PLAN])


def current_period(now: Optional[datetime] = None) -> Dict[str, object]:
    """Current billing period = the calendar month in Asia/Dubai.
    Returns tz-aware UTC bounds [start, end) plus a 'YYYY-MM' label. Pure."""
    now = (now or datetime.now(timezone.utc)).astimezone(_DUBAI)
    start_local = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # First day of next month.
    if start_local.month == 12:
        end_local = start_local.replace(year=start_local.year + 1, month=1)
    else:
        end_local = start_local.replace(month=start_local.month + 1)
    return {
        "label": start_local.strftime("month:%Y-%m"),
        "start": start_local.astimezone(timezone.utc),
        "end": end_local.astimezone(timezone.utc),
        "timezone": "Asia/Dubai",
    }


async def record_usage(tenant_id: int, event_type: str, quantity: int = 1,
                       metadata: Optional[dict] = None) -> None:
    """Append a usage event. BEST-EFFORT and never raises — metering must not be
    able to break a product request. Opens its own short session."""
    try:
        import json
        from app.services.database import async_session
        async with async_session() as session:
            await session.execute(text("""
                INSERT INTO usage_events (tenant_id, event_type, quantity, metadata)
                VALUES (:tid, :etype, :qty, CAST(:meta AS JSONB))
            """), {"tid": tenant_id, "etype": event_type, "qty": max(0, int(quantity)),
                   "meta": json.dumps(metadata or {})})
            await session.commit()
    except Exception:
        # Swallow — a metering failure is never worth failing the user's action.
        pass


async def _period_counts(db: AsyncSession, tenant_id: int, period: Dict) -> Dict[str, int]:
    rows = (await db.execute(text("""
        SELECT event_type, COALESCE(SUM(quantity), 0) AS used
        FROM usage_events
        WHERE tenant_id = :tid AND created_at >= :start AND created_at < :end
        GROUP BY event_type
    """), {"tid": tenant_id, "start": period["start"], "end": period["end"]})).fetchall()
    raw = {r.event_type: int(r.used) for r in rows}
    # Fold singular event_type -> plural dimension.
    out = {dim: 0 for dim in METERED_EVENTS}
    for etype, used in raw.items():
        dim = EVENT_TO_DIM.get(etype)
        if dim:
            out[dim] += used
    return out


async def usage_summary(db: AsyncSession, tenant_id: int) -> Dict:
    """Billing-period usage for a tenant: plan, period window, per-event meters."""
    row = (await db.execute(
        text("SELECT plan FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )).fetchone()
    plan = (row.plan if row else None) or _DEFAULT_PLAN
    period = current_period()
    counts = await _period_counts(db, tenant_id, period)
    limits = usage_limits_for_plan(plan)
    meters = {dim: _meter(counts[dim], limits[dim]) for dim in METERED_EVENTS}
    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "window": period["label"],
        "period_start": period["start"].isoformat(),
        "period_end": period["end"].isoformat(),
        "timezone": period["timezone"],
        "usage": meters,
        "any_over_quota": any(m["over_quota"] for m in meters.values()),
        "enforced": _enforcement_on(),
    }


def _enforcement_on() -> bool:
    return os.getenv("ENFORCE_USAGE_QUOTAS", "false").strip().lower() in ("1", "true", "yes", "on")


async def check_quota(db: AsyncSession, tenant_id: int, event_type: str) -> Tuple[bool, Dict]:
    """Soft quota check for one dimension. Returns (allowed, meter).

    allowed is False only when enforcement is ON, the plan limit is not unlimited,
    and the in-period usage already meets/exceeds the limit. Enterprise (None) and
    enforcement-off are always allowed."""
    dim = EVENT_TO_DIM.get(event_type, event_type)
    plan_row = (await db.execute(
        text("SELECT plan FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )).fetchone()
    plan = (plan_row.plan if plan_row else None) or _DEFAULT_PLAN
    limit = usage_limits_for_plan(plan).get(dim)
    period = current_period()
    counts = await _period_counts(db, tenant_id, period)
    used = counts.get(dim, 0)
    meter = _meter(used, limit)
    if not _enforcement_on() or limit is None:
        return True, meter
    return used < limit, meter
