"""E10-2 — honour the isolation tier a tenant was sold, or refuse to serve them.

Only `shared` (one schema, tenant_id + RLS) is implemented. `dedicated_schema`
and `dedicated_db` are recorded on the tenant but not built.

The tempting move is to store the tier, serve everyone from the shared pool, and
call the column "future-proofing". That is the failure mode this codebase keeps
finding and removing: a promise the system does not keep, invisible until an
auditor asks. A tenant who paid for a dedicated database and is silently sitting
in the shared one has been mis-sold, and no error was ever raised.

So: a tenant on an unsupported tier gets 503 with the tier named. Loud, immediate,
and true. The fix is to provision what was sold, or to correct the tier — not to
look the other way.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

SHARED = "shared"
KNOWN_TIERS = (SHARED, "dedicated_schema", "dedicated_db")

_DESCRIPTIONS = {
    "shared": "One database and schema, separated by tenant_id and Postgres RLS.",
    "dedicated_schema": "A dedicated Postgres schema for this tenant.",
    "dedicated_db": "A dedicated Postgres database for this tenant.",
}


def supported_tiers() -> tuple:
    return tuple(get_settings().supported_isolation_tiers)


def is_supported(tier: Optional[str]) -> bool:
    return (tier or SHARED) in supported_tiers()


def describe(tier: str) -> str:
    return _DESCRIPTIONS.get(tier, "Unknown isolation tier.")


def assert_supported(tier: Optional[str], tenant_id: Optional[int] = None) -> None:
    """Raise 503 if this deployment cannot deliver the tenant's isolation tier.

    503, not 500: the request is well-formed and the tenant is entitled to an
    answer — this deployment simply is not provisioned to give it to them. 403
    would say they are not allowed; they are, we just have not built it.
    """
    tier = tier or SHARED
    if is_supported(tier):
        return
    raise HTTPException(
        status_code=503,
        detail={
            "error": "isolation_tier_not_provisioned",
            "isolation_tier": tier,
            "message": (
                f"This tenant is recorded as {tier!r} isolation "
                f"({describe(tier)}) and this deployment can only serve "
                f"{', '.join(supported_tiers())}. Refusing to serve the tenant from "
                f"shared infrastructure they did not agree to."
            ),
            "supported": list(supported_tiers()),
        },
    )


async def tenant_isolation_tier(db: AsyncSession, tenant_id: int) -> str:
    row = (await db.execute(
        text("SELECT isolation_tier FROM tenants WHERE id = :tid"), {"tid": tenant_id}
    )).fetchone()
    return (row.isolation_tier if row else None) or SHARED


async def enforce_tenant_isolation(db: AsyncSession, tenant_id: int) -> str:
    tier = await tenant_isolation_tier(db, tenant_id)
    assert_supported(tier, tenant_id)
    return tier
