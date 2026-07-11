"""
Tenant management API (multi-tenancy foundation).

Mounted at /api/tenants. Two distinct audiences share this router:

- TENANT-SCOPED self-service (branding, usage, billing profile): a tenant admin
  operating on their OWN tenant — gated by role, bound to current_user.tenant_id.
- CROSS-TENANT operator surfaces (list all tenants, platform metrics, tenant
  creation, lifecycle, support notes): Platform Console only. These gate on
  `require_platform_developer`, NEVER on role — `super_admin` is a tenant role
  that every self-signup owner holds (services/tenant_provisioning.py), so a
  role check here would hand every customer the whole customer list.
"""
import re
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.services.database import async_session
from app.services.plan_limits import usage_for_tenant
from app.services.uae_profile import EDITABLE_FIELDS, validate_profile
from app.services.tenant_lifecycle import change_tenant_status, STATES
from app.auth_deps import get_current_user
from app.services.platform_access import require_platform_developer
from app.config import logger

router = APIRouter(tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    plan: str = "free"
    brand_name: Optional[str] = None
    accent_color: Optional[str] = None


class BrandingUpdate(BaseModel):
    brand_name: Optional[str] = None
    logo_url: Optional[str] = None
    accent_color: Optional[str] = None


class BillingProfileUpdate(BaseModel):
    """UAE legal/billing profile (Phase 1). Every field optional → partial saves.
    Only fields the client actually sends are written (model_dump(exclude_unset))."""
    legal_name: Optional[str] = None
    legal_name_ar: Optional[str] = None
    trading_name: Optional[str] = None
    trn: Optional[str] = None
    trade_license_no: Optional[str] = None
    emirate: Optional[str] = None
    jurisdiction: Optional[str] = None
    free_zone_name: Optional[str] = None
    vat_registered: Optional[bool] = None
    registered_address: Optional[str] = None
    billing_address: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    preferred_language: Optional[str] = None
    industry_vertical: Optional[str] = None
    store_count: Optional[int] = None
    sku_count: Optional[int] = None
    procurement_type: Optional[str] = None
    billing_contact_name: Optional[str] = None
    billing_contact_email: Optional[str] = None
    billing_contact_phone: Optional[str] = None
    finance_contact_name: Optional[str] = None
    finance_contact_email: Optional[str] = None
    finance_contact_phone: Optional[str] = None


@router.patch("/branding")
async def update_branding(
    payload: BrandingUpdate,
    current_user: dict = Depends(get_current_user),
):
    """White-label branding (B4): a tenant admin updates their OWN tenant's
    brand name / logo / accent colour. Tenant-scoped — you can only edit the
    tenant your account belongs to."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = current_user.get("tenant_id") or 1

    fields, params = [], {"tid": tenant_id}
    for col in ("brand_name", "logo_url", "accent_color"):
        val = getattr(payload, col)
        if val is not None:
            fields.append(f"{col} = :{col}")
            params[col] = val
    if not fields:
        raise HTTPException(status_code=400, detail="No branding fields provided")

    async with async_session() as session:
        row = (await session.execute(text(f"""
            UPDATE tenants SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = :tid
            RETURNING id, name, brand_name, logo_url, accent_color
        """), params)).fetchone()
        await session.commit()
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return {
            "tenant_id": row.id,
            "name": row.name,
            "brand_name": row.brand_name,
            "logo_url": row.logo_url,
            "accent_color": row.accent_color,
        }


@router.get("/usage")
async def tenant_usage(current_user: dict = Depends(get_current_user)):
    """Plan + metered usage for the caller's OWN tenant (Track 5 metering).

    Admin-scoped and tenant-bound — you only ever see your own tenant's usage.
    Read-only and advisory: `any_over_quota` flags a tenant that has exceeded its
    plan, but nothing is blocked or charged here (billing is the deferred step)."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = current_user.get("tenant_id") or 1
    async with async_session() as session:
        return await usage_for_tenant(session, tenant_id)


@router.get("/usage/period")
async def tenant_usage_period(current_user: dict = Depends(get_current_user)):
    """Billing-period (Asia/Dubai calendar month) usage for the caller's own tenant
    (Phase 3). Counts append-only usage_events per metered dimension — Sage messages,
    forecast jobs, exports, imports, API requests — against the per-plan limits.
    Soft-enforced only when ENFORCE_USAGE_QUOTAS is on (see `enforced`)."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = current_user.get("tenant_id") or 1
    from app.services.usage_metering import usage_summary
    async with async_session() as session:
        return await usage_summary(session, tenant_id)


# --- UAE legal / billing profile (Phase 1) ----------------------------------
# A tenant admin reads/writes their OWN tenant's UAE profile only. Tenant-bound
# (current_user.tenant_id) + RLS (migration 041) — never cross-tenant.

_PROFILE_COLS = ", ".join(["tenant_id", *EDITABLE_FIELDS, "created_at", "updated_at"])


@router.get("/billing-profile")
async def get_billing_profile(current_user: dict = Depends(get_current_user)):
    """UAE legal/billing profile for the caller's own tenant. Returns an empty
    shell (all-null fields) if the tenant has not filled it in yet."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = current_user.get("tenant_id") or 1

    async with async_session() as session:
        row = (await session.execute(
            text(f"SELECT {_PROFILE_COLS} FROM tenant_billing_profile WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )).mappings().fetchone()

    if row is None:
        empty: Dict[str, Any] = {f: None for f in EDITABLE_FIELDS}
        empty.update({"tenant_id": tenant_id, "currency": "AED",
                      "timezone": "Asia/Dubai", "preferred_language": "en",
                      "vat_registered": True})
        return {"profile": empty, "exists": False,
                "legal_note": "Draft — requires review by a qualified UAE legal/tax "
                              "professional before production/customer use."}

    profile = dict(row)
    for k in ("created_at", "updated_at"):
        if profile.get(k) is not None:
            profile[k] = profile[k].isoformat()
    return {"profile": profile, "exists": True,
            "legal_note": "Draft — requires review by a qualified UAE legal/tax "
                          "professional before production/customer use."}


@router.put("/billing-profile")
async def upsert_billing_profile(
    payload: BillingProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Create or update the caller's own UAE legal/billing profile (partial save).
    Validates TRN/emirate/jurisdiction/currency etc. server-side before writing."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    tenant_id = current_user.get("tenant_id") or 1

    cleaned, error = validate_profile(payload.model_dump(exclude_unset=True))
    if error:
        raise HTTPException(status_code=422, detail=error)
    if not cleaned:
        raise HTTPException(status_code=400, detail="No profile fields provided")

    # Upsert: insert the row on first save, merge on subsequent ones.
    cols = list(cleaned.keys())
    insert_cols = ", ".join(["tenant_id", *cols])
    insert_vals = ", ".join([":tid", *[f":{c}" for c in cols]])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols] + ["updated_at = CURRENT_TIMESTAMP"])
    params = {"tid": tenant_id, **cleaned}

    async with async_session() as session:
        await session.execute(text(f"""
            INSERT INTO tenant_billing_profile ({insert_cols})
            VALUES ({insert_vals})
            ON CONFLICT (tenant_id) DO UPDATE SET {updates}
        """), params)
        await session.commit()
        row = (await session.execute(
            text(f"SELECT {_PROFILE_COLS} FROM tenant_billing_profile WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )).mappings().fetchone()

    logger.info(f"Tenant {tenant_id} updated UAE billing profile ({len(cols)} field(s))")
    from app.services.security_events import record_event
    await record_event("billing_profile_updated", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"UAE billing profile updated ({len(cols)} field(s))",
                       evidence={"fields": cols})  # field names only — never values
    profile = dict(row) if row else {}
    for k in ("created_at", "updated_at"):
        if profile.get(k) is not None:
            profile[k] = profile[k].isoformat()
    return {"profile": profile, "saved": True}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:63] or "tenant"


def _row_to_tenant(row) -> dict:
    return {
        "id": row[0],
        "slug": row[1],
        "name": row[2],
        "plan": row[3],
        "status": row[4],
        "brand_name": row[5],
        "accent_color": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
        "user_count": row[8],
    }


@router.get("")
async def list_tenants(current_user: dict = Depends(require_platform_developer)):
    """List all tenants (platform developers only — this is the entire customer list)."""
    async with async_session() as session:
        try:
            result = await session.execute(text("""
                SELECT t.id, t.slug, t.name, t.plan, t.status,
                       t.brand_name, t.accent_color, t.created_at,
                       (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) AS user_count
                FROM tenants t
                ORDER BY t.id
            """))
            tenants = [_row_to_tenant(r) for r in result.fetchall()]
            return {"tenants": tenants, "total": len(tenants)}
        except Exception as e:
            logger.error(f"List tenants error: {e}")
            return {"tenants": [], "total": 0}


@router.get("/metrics")
async def platform_metrics(current_user: dict = Depends(require_platform_developer)):
    """Cross-tenant operator metrics (platform developers only): tenant counts by
    status + plan, total users, and an estimated MRR from list prices (enterprise
    counted separately since it's custom-priced)."""
    from app.services.billing import PLAN_PRICES_AED
    async with async_session() as session:
        by_status = {r.status: r.n for r in (await session.execute(text(
            "SELECT status, COUNT(*) AS n FROM tenants GROUP BY status"))).fetchall()}
        by_plan = {r.plan: r.n for r in (await session.execute(text(
            "SELECT plan, COUNT(*) AS n FROM tenants GROUP BY plan"))).fetchall()}
        total_users = (await session.execute(text("SELECT COUNT(*) FROM users"))).scalar() or 0
        active_total = (await session.execute(text(
            "SELECT COUNT(*) FROM tenants WHERE status NOT IN ('cancelled','deleted')"))).scalar() or 0
        # MRR from active non-enterprise tenants on a priced plan.
        priced = (await session.execute(text("""
            SELECT plan, COUNT(*) AS n FROM tenants
            WHERE status NOT IN ('cancelled','deleted','suspended') GROUP BY plan
        """))).fetchall()
    mrr = 0.0
    enterprise_active = 0
    for r in priced:
        price = PLAN_PRICES_AED.get(r.plan)
        if price is None:
            enterprise_active += r.n
        else:
            mrr += float(price) * r.n
    return {
        "tenants_total": sum(by_status.values()),
        "tenants_active": int(active_total),
        "by_status": by_status, "by_plan": by_plan,
        "total_users": int(total_users),
        "estimated_mrr_aed": round(mrr, 2),
        "enterprise_active": enterprise_active,
        "note": "Estimated MRR from list prices; enterprise is custom-priced (counted separately). Draft.",
    }


@router.post("", status_code=201)
async def create_tenant(payload: TenantCreate, current_user: dict = Depends(require_platform_developer)):
    """Create a new tenant (platform developers only)."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tenant name is required")
    slug = _slugify(payload.slug or name)
    plan = payload.plan if payload.plan in {"free", "starter", "growth", "enterprise"} else "free"

    async with async_session() as session:
        try:
            exists = await session.execute(
                text("SELECT 1 FROM tenants WHERE slug = :slug"), {"slug": slug}
            )
            if exists.fetchone():
                raise HTTPException(status_code=409, detail=f"A tenant with slug '{slug}' already exists")

            result = await session.execute(
                text("""
                    INSERT INTO tenants (slug, name, plan, status, brand_name, accent_color)
                    VALUES (:slug, :name, :plan, 'active', :brand_name, :accent_color)
                    RETURNING id, slug, name, plan, status, brand_name, accent_color, created_at, 0
                """),
                {
                    "slug": slug,
                    "name": name,
                    "plan": plan,
                    "brand_name": payload.brand_name or name,
                    "accent_color": payload.accent_color or "#0f766e",
                },
            )
            row = result.fetchone()
            await session.commit()
            logger.info(f"Platform developer {current_user.get('email')} created tenant '{slug}'")
            return _row_to_tenant(row)
        except HTTPException:
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Create tenant error: {e}")
            raise HTTPException(status_code=500, detail="Failed to create tenant")


# --- Platform Console: tenant lifecycle + support notes (Phase 2) ------------
# Platform developers only. Cross-tenant by design — these are operator
# controls, not tenant self-service, and they read/write other tenants' rows.

class StatusChange(BaseModel):
    status: str
    reason: Optional[str] = None


class NoteCreate(BaseModel):
    note: str


@router.patch("/{tenant_id}/status")
async def change_status(tenant_id: int, payload: StatusChange,
                        current_user: dict = Depends(require_platform_developer)):
    """Transition a tenant's lifecycle state (suspend / reactivate / cancel / …).
    Validated against the allowed-transition graph and audited in
    tenant_status_events."""
    target = (payload.status or "").strip().lower()
    if target not in STATES:
        raise HTTPException(status_code=422,
                            detail=f"Unknown status. One of: {', '.join(sorted(STATES))}")
    async with async_session() as session:
        result, error = await change_tenant_status(
            session, tenant_id, target,
            reason=payload.reason,
            actor_id=current_user.get("id"),
            actor_email=current_user.get("email"),
        )
        if error:
            await session.rollback()
            code = 404 if error == "Tenant not found" else 409
            raise HTTPException(status_code=code, detail=error)
        await session.commit()
    logger.info(f"Platform developer {current_user.get('email')} set tenant {tenant_id} "
                f"-> {target} ({payload.reason or 'no reason'})")
    from app.services.security_events import record_event
    await record_event("tenant_status_changed", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=current_user.get("id"),
                       actor_email=current_user.get("email"),
                       detail=f"Tenant {tenant_id}: {result['from_status']} → {target}",
                       evidence={"from": result["from_status"], "to": target,
                                 "reason": payload.reason})
    from app.services.notifications import notify_tenant_admins
    _sev = "high" if target in ("suspended", "past_due", "payment_pending") else "medium"
    await notify_tenant_admins(tenant_id, type="lifecycle", severity=_sev,
                               title=f"Account status changed to {target.replace('_', ' ')}",
                               body=payload.reason or None, link="/settings/billing",
                               metadata={"from": result["from_status"], "to": target})
    return result


@router.get("/{tenant_id}/status-events")
async def list_status_events(tenant_id: int,
                             current_user: dict = Depends(require_platform_developer)):
    """Lifecycle transition history for a tenant (operator audit view)."""
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT from_status, to_status, reason, changed_email, created_at
            FROM tenant_status_events
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT 200
        """), {"tid": tenant_id})).mappings().fetchall()
    return {"events": [
        {**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]}


@router.get("/{tenant_id}/notes")
async def list_notes(tenant_id: int, current_user: dict = Depends(require_platform_developer)):
    """Operator support notes for a tenant."""
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, note, author_email, created_at
            FROM tenant_admin_notes
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT 200
        """), {"tid": tenant_id})).mappings().fetchall()
    return {"notes": [
        {**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]}


@router.post("/{tenant_id}/notes", status_code=201)
async def add_note(tenant_id: int, payload: NoteCreate,
                   current_user: dict = Depends(require_platform_developer)):
    """Add an operator support note to a tenant."""
    note = (payload.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    async with async_session() as session:
        exists = (await session.execute(
            text("SELECT 1 FROM tenants WHERE id = :tid"), {"tid": tenant_id})).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Tenant not found")
        await session.execute(text("""
            INSERT INTO tenant_admin_notes (tenant_id, note, author_id, author_email)
            VALUES (:tid, :note, :uid, :email)
        """), {"tid": tenant_id, "note": note,
               "uid": current_user.get("id"), "email": current_user.get("email")})
        await session.commit()
    return {"success": True}
