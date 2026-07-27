"""Platform Console — bespoke ("Rolls-Royce") request ledger routes.

Mounted at /api/admin/dev/bespoke. Developers-only: EVERY endpoint depends on
require_platform_developer (flag + allowlist, fail-closed — see
services/platform_access.py). Because the ledger is CROSS-TENANT control-plane
data, all DB work runs on the OWNER session (async_session), deliberately NOT
get_db — get_db binds the caller's tenant GUC and this surface must see across
tenants (and rows whose tenant does not exist yet).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services import bespoke
from app.services.database import async_session
from app.services.platform_access import require_platform_developer

router = APIRouter(tags=["Bespoke"])


class BespokeCreate(BaseModel):
    tenant_id: Optional[int] = None  # a request may predate the tenant
    title: str = Field(..., min_length=3)
    client_description: str = Field(..., min_length=3)
    priority: str = Field("medium", pattern="^(low|medium|high|vip)$")


class BespokeUpdate(BaseModel):
    status: Optional[str] = Field(
        None, pattern="^(requested|scoped|approved|building|delivered|declined)$")
    priority: Optional[str] = Field(None, pattern="^(low|medium|high|vip)$")
    scoping_notes: Optional[str] = None
    estimate: Optional[str] = None


@router.get("/dev/bespoke")
async def list_bespoke_requests(
    status: Optional[str] = None,
    tenant_id: Optional[int] = None,
    user: dict = Depends(require_platform_developer),
):
    """The ledger, optionally filtered by status and/or tenant."""
    if status is not None and status not in bespoke.TRANSITIONS:
        raise HTTPException(
            status_code=422,
            detail=(f"Unknown status {status!r}; valid statuses: "
                    f"{', '.join(sorted(bespoke.TRANSITIONS))}"))
    async with async_session() as db:
        rows = await bespoke.list_requests(db, status=status, tenant_id=tenant_id)
    return {"requests": rows}


@router.post("/dev/bespoke", status_code=201)
async def create_bespoke_request(
    body: BespokeCreate,
    user: dict = Depends(require_platform_developer),
):
    """Record a client's ask verbatim; it enters the pipeline as `requested`."""
    async with async_session() as db:
        row = await bespoke.create_request(
            db,
            tenant_id=body.tenant_id,
            title=body.title,
            client_description=body.client_description,
            priority=body.priority,
            created_by=user.get("email") or "platform_developer",
        )
        await db.commit()
    return row


@router.get("/dev/bespoke/{request_id}")
async def get_bespoke_request(
    request_id: int,
    user: dict = Depends(require_platform_developer),
):
    async with async_session() as db:
        row = await bespoke.get_request(db, request_id)
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"Bespoke request {request_id} not found")
    return row


@router.patch("/dev/bespoke/{request_id}")
async def update_bespoke_request(
    request_id: int,
    body: BespokeUpdate,
    user: dict = Depends(require_platform_developer),
):
    """Move a request through the pipeline. Illegal jumps and evidence-free
    claims (delivered without timestamp, declined without reason) are refused
    with a 409 naming the reason — nothing is written on refusal."""
    async with async_session() as db:
        existing = await bespoke.get_request(db, request_id)
        if existing is None:
            raise HTTPException(status_code=404,
                                detail=f"Bespoke request {request_id} not found")
        row, err = await bespoke.update_request(
            db, request_id,
            status=body.status,
            priority=body.priority,
            scoping_notes=body.scoping_notes,
            estimate=body.estimate,
            actor=user.get("email") or "platform_developer",
        )
        if err:
            raise HTTPException(status_code=409, detail=err)
        await db.commit()
    return row
