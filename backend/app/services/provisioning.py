"""E10-2 completion — the tenant isolation-tier PROVISIONING control plane.

The audit found E10-2 "partial: only a fail-closed 503 guard, provisioning not
built". This is the missing control plane: a governed lifecycle that moves a tenant
onto isolated infrastructure and is consulted by isolation.py, so a dedicated tier
goes from "never servable" to "servable only once provisioning is `active`".

WHAT IS REAL HERE, AND WHAT IS THE HONEST BOUNDARY.

`dedicated_schema` is implemented as a real, tested data-plane primitive
(migration 068's provision_tenant_schema): a private Postgres schema holding the
tenant's own copies of the core transactional tables. A write through that tenant's
routed session lands in their schema, physically separate from the shared tables —
proven in tests.

The boundary, stated because Postgres makes it unavoidable: a VIEW binds to the
schema of its tables AT CREATION time, not at query time. The ~32 shared analytics
views live in `public` and read `public` tables. So for a dedicated_schema tenant,
their RAW TRANSACTIONAL TABLES are isolated and routed, but the derived analytics
layer is not yet re-pointed at their schema — replicating that view/matview stack
per tenant (and migrating it forward) is the remaining data-plane step, documented
in docs/product/ISOLATION_TIERS.md. Because that would otherwise give a dedicated
tenant a correct-looking-but-wrong dashboard, session routing is applied ONLY when
`enable_dedicated_routing` is set — off by default, so nothing silently breaks.

`dedicated_db` (a fully separate database, built by the normal migrate job, with no
view-binding problem) is the operator-provisioned path: the control plane records
and governs it; creating the database + running migrations + wiring a per-tenant
engine is an infra runbook step. This module tracks that lifecycle honestly rather
than pretending a request handler creates a database.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, logger

VALID_TIERS = ("shared", "dedicated_schema", "dedicated_db")


def schema_name_for(tenant_id: int) -> str:
    return f"tenant_{tenant_id}"


async def get_provisioning(db: AsyncSession, tenant_id: int) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT tenant_id, tier, status, schema_name, db_ref, error,
               requested_by, requested_at, activated_at, deprovisioned_at
          FROM tenant_provisioning WHERE tenant_id = :t
    """), {"t": tenant_id})).mappings().fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("requested_at", "activated_at", "deprovisioned_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    return d


async def is_tier_active(db: AsyncSession, tenant_id: int, tier: str) -> bool:
    """True only if this tenant is provisioned AND active on `tier`. `shared` is
    always active (it needs no provisioning)."""
    if tier == "shared":
        return True
    row = (await db.execute(text("""
        SELECT 1 FROM tenant_provisioning
         WHERE tenant_id = :t AND tier = :tier AND status = 'active'
    """), {"t": tenant_id, "tier": tier})).fetchone()
    return row is not None


async def request_tier(db: AsyncSession, tenant_id: int, tier: str, *, actor: str) -> Dict[str, Any]:
    """Record intent to move a tenant to `tier`. Idempotent per tenant (UNIQUE)."""
    if tier not in VALID_TIERS:
        raise ValueError(f"Unknown tier {tier!r}")
    await db.execute(text("""
        INSERT INTO tenant_provisioning (tenant_id, tier, status, requested_by)
        VALUES (:t, :tier, 'requested', :by)
        ON CONFLICT (tenant_id) DO UPDATE
           SET tier = EXCLUDED.tier, status = 'requested',
               error = NULL, requested_by = EXCLUDED.requested_by,
               requested_at = now(), updated_at = now()
    """), {"t": tenant_id, "tier": tier, "by": actor})
    await db.commit()
    return await get_provisioning(db, tenant_id)


async def provision(db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
    """Execute the data-plane provisioning for the tenant's requested tier.

    dedicated_schema: create the private schema + isolated core tables (real).
    dedicated_db:     recorded only — the DB creation + migrate + engine wiring is
                      an operator/runbook step; we mark it 'provisioning' and return
                      the runbook pointer rather than pretend a handler made a DB.
    """
    rec = await get_provisioning(db, tenant_id)
    if not rec:
        raise ValueError("No provisioning requested for this tenant")
    tier = rec["tier"]

    if tier == "shared":
        await _mark(db, tenant_id, status="active", schema_name=None, db_ref=None)
        await _sync_tenant_tier(db, tenant_id, "shared")
        return await get_provisioning(db, tenant_id)

    if tier == "dedicated_schema":
        await _mark(db, tenant_id, status="provisioning")
        try:
            schema = (await db.execute(
                text("SELECT provision_tenant_schema(:t)"), {"t": tenant_id}
            )).scalar()
            await db.commit()
            await _mark(db, tenant_id, status="active", schema_name=schema, activate=True)
            await _sync_tenant_tier(db, tenant_id, "dedicated_schema")
            logger.info(f"Provisioned dedicated schema {schema!r} for tenant {tenant_id}")
        except Exception as exc:
            await db.rollback()
            await _mark(db, tenant_id, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        return await get_provisioning(db, tenant_id)

    if tier == "dedicated_db":
        # Honest: a separate database is an infra action (CREATE DATABASE + run the
        # migrate job against it + wire a per-tenant engine). We record intent and
        # the target ref; an operator completes it and flips status to active.
        db_ref = f"tenant_{tenant_id}_db"
        await _mark(db, tenant_id, status="provisioning", db_ref=db_ref)
        return {
            **(await get_provisioning(db, tenant_id)),
            "operator_action_required": (
                f"Create database {db_ref}, run `python -m app.commands.migrate` against it, "
                f"set its URL in the per-tenant routing config, then activate. "
                f"See docs/product/ISOLATION_TIERS.md."
            ),
        }

    raise ValueError(f"Unhandled tier {tier!r}")


async def deprovision(db: AsyncSession, tenant_id: int, *, force: bool = False) -> Dict[str, Any]:
    """Tear a tenant's dedicated infrastructure down and return them to shared."""
    rec = await get_provisioning(db, tenant_id)
    if not rec:
        raise ValueError("No provisioning record for this tenant")
    await _mark(db, tenant_id, status="deprovisioning")
    # Always drop a dedicated schema if one exists — defensively, regardless of the
    # current tier. A tenant switched dedicated_schema -> dedicated_db would
    # otherwise orphan the old schema; deprovision_tenant_schema is a no-op when
    # there's nothing to drop.
    await db.execute(text("SELECT deprovision_tenant_schema(:t, :force)"),
                     {"t": tenant_id, "force": force})
    await db.commit()
    await _mark(db, tenant_id, status="deprovisioned", deprovision=True)
    await _sync_tenant_tier(db, tenant_id, "shared")
    return await get_provisioning(db, tenant_id)


async def _mark(db: AsyncSession, tenant_id: int, *, status: str,
                schema_name: Optional[str] = "__keep__", db_ref: Optional[str] = "__keep__",
                error: Optional[str] = None, activate: bool = False,
                deprovision: bool = False) -> None:
    sets = ["status = :st", "updated_at = now()", "error = :err"]
    params: Dict[str, Any] = {"t": tenant_id, "st": status, "err": error}
    if schema_name != "__keep__":
        sets.append("schema_name = :sn"); params["sn"] = schema_name
    if db_ref != "__keep__":
        sets.append("db_ref = :dr"); params["dr"] = db_ref
    if activate:
        sets.append("activated_at = now()")
    if deprovision:
        sets.append("deprovisioned_at = now()")
    await db.execute(text(f"UPDATE tenant_provisioning SET {', '.join(sets)} WHERE tenant_id = :t"), params)
    await db.commit()


async def _sync_tenant_tier(db: AsyncSession, tenant_id: int, tier: str) -> None:
    """Keep tenants.isolation_tier in step with the provisioned reality, so
    isolation.enforce_tenant_isolation and the login gate see the truth."""
    await db.execute(text("UPDATE tenants SET isolation_tier = :tier WHERE id = :t"),
                     {"tier": tier, "t": tenant_id})
    await db.commit()


def dedicated_routing_enabled() -> bool:
    """Whether an active dedicated_schema tenant's session is actually routed to
    their schema via search_path. OFF by default: routing raw tables to the tenant
    schema while the shared analytics views still read public would give a
    correct-looking-but-wrong dashboard. Flip on only once the view stack is
    replicated per tenant (docs/product/ISOLATION_TIERS.md)."""
    return bool(getattr(get_settings(), "enable_dedicated_schema_routing", False))
