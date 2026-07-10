"""
Data-subject rights API (Phase 12 — trust & legal). Mounted at /api/data-rights.

Admin-gated, tenant-scoped:
  * GET  /export          → download this tenant's data (portability)
  * POST /requests        → file an export/delete request (audited; delete is
                            human-approved, never executed here)
  * GET  /requests        → list this tenant's requests

A tenant admin only ever touches their OWN tenant's data — tenant_id comes from
the authenticated user, never from the request body.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import data_rights_service as dr
from app.routes.auth import get_current_user

router = APIRouter()


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required for data-rights operations")


class DataRequest(BaseModel):
    kind: str = Field(..., pattern="^(export|delete)$")
    scope: Optional[str] = Field(None, max_length=2000)


@router.get("/export")
async def export_my_tenant(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    data = await dr.export_tenant_data(db, tenant_id)
    from app.services.security_events import record_event
    await record_event("tenant_data_exported", tenant_id=tenant_id,
                       actor_user_id=user.get("id"), actor_email=user.get("email"),
                       detail=f"Tenant {tenant_id} data export generated",
                       evidence={"tables": list(data.get("tables", {}).keys())})
    # Usage metering (Phase 3): counted against the billing-period quota, but
    # deliberately NOT enforced (E8-3). Data portability is a right the tenant has
    # over their own data (GDPR Art. 20, UAE PDPL) — we may bill for it, we may not
    # refuse it because a meter is full. Every other export surface calls
    # enforce_quota; this one only records.
    from app.services.usage_metering import record_usage
    await record_usage(tenant_id, "export", metadata={"kind": "data_rights"})
    # Force a download with a stable filename.
    return JSONResponse(content=data, headers={
        "Content-Disposition": f'attachment; filename="tenant-{tenant_id}-export.json"'
    })


@router.post("/requests")
async def file_request(
    body: DataRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    created = await dr.create_request(
        db, tenant_id, body.kind, scope=body.scope,
        requested_by=user.get("id"), requested_email=user.get("email"),
    )
    from app.services.security_events import record_event
    await record_event("data_request_filed", tenant_id=tenant_id,
                       actor_user_id=user.get("id"), actor_email=user.get("email"),
                       detail=f"{body.kind} request filed for tenant {tenant_id}",
                       evidence={"request_id": created["id"], "kind": body.kind})
    msg = ("Deletion is reviewed and executed by an operator (human-approved) — "
           "see your account team." if body.kind == "delete"
           else "Export request recorded; use GET /export to download now.")
    return {**created, "message": msg}


@router.get("/requests")
async def my_requests(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    return {"requests": await dr.list_requests(db, tenant_id)}
