"""
Plan limits + usage metering (Track 5 — SaaS scaffolding).

Defines the per-plan quotas and computes a tenant's current usage against them.
This is **metering, not billing**: it surfaces how much of a plan a tenant is
using so the limits are visible and enforceable later — no charging, and no hard
block here (the public API stays open; `over_quota` is advisory). Wiring a
payment provider onto `tenants.plan` is the deferred go-to-market step.

`None` in a limit means "unlimited" (enterprise). The API-request meter uses the
lifetime `request_count` already tracked per key in `tenant_api_keys`; a rolling
monthly window is a later enhancement (it needs a usage-events table) and is
called out honestly in the endpoint response (`window: "lifetime"`).
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Ordered cheapest → richest. `None` => unlimited. Keys match the set accepted by
# routes/tenants.create_tenant: {free, starter, growth, enterprise}.
PLAN_LIMITS: Dict[str, Dict[str, Optional[int]]] = {
    "free":       {"api_requests": 10_000,    "api_keys": 2,    "users": 5},
    "starter":    {"api_requests": 100_000,   "api_keys": 5,    "users": 20},
    "growth":     {"api_requests": 1_000_000, "api_keys": 20,   "users": 100},
    "enterprise": {"api_requests": None,      "api_keys": None, "users": None},
}

_DEFAULT_PLAN = "free"


def limits_for_plan(plan: Optional[str]) -> Dict[str, Optional[int]]:
    """Return the limit map for a plan, falling back to free for unknown plans."""
    return PLAN_LIMITS.get((plan or "").lower(), PLAN_LIMITS[_DEFAULT_PLAN])


def _meter(used: int, limit: Optional[int]) -> Dict:
    """Build a single metered dimension: used / limit / remaining / over flag.

    `limit is None` => unlimited: remaining is null, never over quota."""
    if limit is None:
        return {"used": used, "limit": None, "remaining": None,
                "over_quota": False, "pct": 0.0}
    remaining = max(0, limit - used)
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "over_quota": used > limit,
        "pct": round((used / limit) * 100, 1) if limit else 0.0,
    }


async def usage_for_tenant(db: AsyncSession, tenant_id: int) -> Dict:
    """Compute a tenant's plan, limits, and current usage across the metered
    dimensions (API requests, active API keys, users). Read-only."""
    row = (await db.execute(text("""
        SELECT
          t.plan AS plan,
          COALESCE((SELECT SUM(request_count) FROM tenant_api_keys k
                    WHERE k.tenant_id = t.id), 0)                       AS api_requests,
          (SELECT COUNT(*) FROM tenant_api_keys k
           WHERE k.tenant_id = t.id AND k.revoked_at IS NULL)           AS api_keys,
          (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id)       AS users
        FROM tenants t
        WHERE t.id = :tid
    """), {"tid": tenant_id})).fetchone()

    if row is None:
        plan = _DEFAULT_PLAN
        used = {"api_requests": 0, "api_keys": 0, "users": 0}
    else:
        plan = row.plan or _DEFAULT_PLAN
        used = {
            "api_requests": int(row.api_requests or 0),
            "api_keys": int(row.api_keys or 0),
            "users": int(row.users or 0),
        }

    limits = limits_for_plan(plan)
    meters = {dim: _meter(used[dim], limits[dim]) for dim in ("api_requests", "api_keys", "users")}
    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "window": "lifetime",  # honest: rolling-month windowing is a later enhancement
        "usage": meters,
        "any_over_quota": any(m["over_quota"] for m in meters.values()),
    }
