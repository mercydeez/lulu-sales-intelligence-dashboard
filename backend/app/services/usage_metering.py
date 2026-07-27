"""
Billing-period usage metering + quotas (UAE SaaS Phase 3, enforcement E8-3).

Moves metering from the Track-5 *lifetime* totals to the CURRENT BILLING PERIOD —
the calendar month in Asia/Dubai. Events are appended to `usage_events` (migration
043); the summary counts them in-period and meters them against per-plan limits.

Enforcement is OFF by default (`ENFORCE_USAGE_QUOTAS`), so the demo/MVP and the
existing tests are unaffected. When on, `enforce_quota` raises 429 once a
non-unlimited plan limit is consumed. Enterprise (None limit) is always
unlimited; UAE manual/enterprise plans stay custom.

WHAT EACH DIMENSION COUNTS (E8-3 — these definitions are the contract):
  sage_messages  one message sent to Sage.
  imports        one import JOB, not one imported row. A 5,000-row CSV is 1.
  exports        one generated export/download.
  forecast_jobs  one forecast computed *on demand through the public API*. A
                 dashboard panel re-rendering its projection is NOT a job — the
                 free limit of 50/month would otherwise be spent by a few days of
                 ordinary browsing, and we would be billing for our own re-renders.
  api_requests   one authenticated call to /api/public/v1/*.

FAIL-OPEN, FAIL-CLOSED: a metering *infrastructure* failure (DB down, table
missing) must never block a paid action — `enforce_quota` allows the request.
An actual over-quota is a business decision and does block. The two are
deliberately not the same code path.

LEGAL/BILLING: this is metering, not invoicing. No money moves here.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

from fastapi import HTTPException

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

# Dimensions that actually REFUSE a request when enforcement is on. Everything
# else is metered and billed, but never blocked.
#
# `exports` is metered-only on purpose. Both of today's export surfaces are legal
# rights rather than product features — data portability (GDPR Art. 20 / UAE PDPL)
# and security-event evidence an admin may owe a regulator. We may bill for them;
# refusing them because a meter is full is not a position we want to defend. When
# a genuinely discretionary export ships, enforce it there and add it here.
ENFORCED_DIMENSIONS: frozenset = frozenset(
    {"sage_messages", "imports", "forecast_jobs", "api_requests"}
)


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
    on = _enforcement_on()
    meters = {}
    for dim in METERED_EVENTS:
        m = _meter(counts[dim], limits[dim])
        # Per-dimension truth: a limit that never refuses must not be rendered as
        # a hard cap. `exports` is billed, not blocked — see ENFORCED_DIMENSIONS.
        m["enforced"] = on and dim in ENFORCED_DIMENSIONS and limits[dim] is not None
        meters[dim] = m
    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "window": period["label"],
        "period_start": period["start"].isoformat(),
        "period_end": period["end"].isoformat(),
        "timezone": period["timezone"],
        "usage": meters,
        "any_over_quota": any(m["over_quota"] for m in meters.values()),
        "enforced": on,
        "enforced_dimensions": sorted(ENFORCED_DIMENSIONS) if on else [],
    }


def _enforcement_on() -> bool:
    """Typed config, not a bare os.getenv — so the flag is visible in Settings,
    validated once, and overridable in tests the same way every other flag is."""
    from app.config import get_settings
    return bool(get_settings().enforce_usage_quotas)


async def check_quota(db: AsyncSession, tenant_id: int, event_type: str) -> Tuple[bool, Dict]:
    """Soft quota check for one dimension. Returns (allowed, meter).

    allowed is False only when enforcement is ON, the plan limit is not unlimited,
    and the in-period usage already meets/exceeds the limit. Enterprise (None) and
    enforcement-off are always allowed."""
    allowed, meter, _plan = await _check(db, tenant_id, event_type)
    return allowed, meter


async def _check(db: AsyncSession, tenant_id: int, event_type: str) -> Tuple[bool, Dict, str]:
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
        return True, meter, plan
    return used < limit, meter, plan


def seconds_until_period_reset(now: Optional[datetime] = None) -> int:
    """How long until the quota refills — i.e. until the next billing period."""
    now = now or datetime.now(timezone.utc)
    end = current_period(now)["end"]
    return max(1, int((end - now).total_seconds()))


def quota_exceeded_error(dimension: str, plan: str, meter: Dict,
                         now: Optional[datetime] = None) -> HTTPException:
    """A 429 that tells the caller exactly which meter tripped and when it resets.

    'Upgrade to continue' with no number is useless to a machine and infuriating
    to a human, so both get the meter and the reset instant.
    """
    period = current_period(now)
    retry_after = seconds_until_period_reset(now)
    resets_at = period["end"].isoformat()
    return HTTPException(
        status_code=429,
        headers={
            "Retry-After": str(retry_after),
            "X-Quota-Dimension": dimension,
            "X-Quota-Limit": str(meter["limit"]),
            "X-Quota-Remaining": str(meter["remaining"]),
            "X-Quota-Reset": resets_at,
        },
        detail={
            "error": "quota_exceeded",
            "dimension": dimension,
            "plan": plan,
            "used": meter["used"],
            "limit": meter["limit"],
            "remaining": meter["remaining"],
            "period": period["label"],
            "resets_at": resets_at,
            "message": (
                f"Your {plan} plan allows {meter['limit']} {dimension.replace('_', ' ')} "
                f"per billing period, and {meter['used']} have been used. "
                f"The quota resets on {resets_at}."
            ),
        },
    )


async def enforce_quota(db: AsyncSession, tenant_id: int, event_type: str) -> Optional[Dict]:
    """Raise 429 if this tenant has consumed its plan's quota for `event_type`.

    Fails OPEN on an infrastructure error: if we cannot read the meter, we do not
    know the tenant is over, and refusing a paid action on a guess is worse than
    letting one extra request through. Only a *measured* over-quota refuses.
    """
    try:
        allowed, meter, plan = await _check(db, tenant_id, event_type)
    except Exception:
        return None  # metering is broken; the product keeps working

    if not allowed:
        raise quota_exceeded_error(EVENT_TO_DIM.get(event_type, event_type), plan, meter)
    return meter
