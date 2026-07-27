"""
SCIM 2.0 routes (E5-1c). Mounted at /api/scim.

Protocol endpoints (bearer-token auth, per tenant):
  /api/scim/v2/{tenant_slug}/ServiceProviderConfig | Schemas | ResourceTypes
  /api/scim/v2/{tenant_slug}/Users [ /{id} ]   (GET/POST/PUT/PATCH/DELETE)
  /api/scim/v2/{tenant_slug}/Groups [ /{id} ]  (GET/POST/PATCH/DELETE)

Admin token-management endpoints (normal JWT auth, admin only):
  /api/scim/admin/tokens  (list/create) + /{id}/rotate + /{id}/revoke

SCIM protocol endpoints authenticate with a tenant SCIM bearer token (NOT the
local JWT); admin endpoints use the existing auth dependency. No secrets are ever
returned except a raw token ONCE at create/rotate.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.database import get_db
from app.services import scim as scim_svc
from app.services.scim import SCIMError
from app.auth_deps import require_role

router = APIRouter()

SCIM_MEDIA = "application/scim+json"


def _scim_json(content, status=200):
    return JSONResponse(status_code=status, content=content, media_type=SCIM_MEDIA)


def _scim_err(e: SCIMError):
    return JSONResponse(status_code=e.status, content=e.body(), media_type=SCIM_MEDIA)


def _base_url(request: Request, tenant_slug: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/api/scim/v2/{tenant_slug}"


async def _authn(request: Request, tenant_slug: str, db: AsyncSession) -> int:
    """Authenticate the SCIM bearer token; returns tenant_id or raises SCIMError."""
    authz = request.headers.get("Authorization")
    tenant_id, _token = await scim_svc.authenticate_scim(db, tenant_slug, authz)
    return tenant_id


def _paging(request: Request):
    q = request.query_params
    try:
        start = max(1, int(q.get("startIndex", "1")))
    except ValueError:
        start = 1
    from app.config import get_settings
    cap = get_settings().scim_max_page_size
    try:
        count = int(q.get("count", str(cap)))
    except ValueError:
        count = cap
    count = max(0, min(count, cap))
    return start, count


# ===========================================================================
# Discovery endpoints
# ===========================================================================
@router.get("/v2/{tenant_slug}/ServiceProviderConfig")
async def service_provider_config(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _authn(request, tenant_slug, db)
        return _scim_json(scim_svc.service_provider_config())
    except SCIMError as e:
        return _scim_err(e)


@router.get("/v2/{tenant_slug}/Schemas")
async def schemas(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _authn(request, tenant_slug, db)
        return _scim_json(scim_svc.scim_list_response([scim_svc.user_schema()], 1, 1, 1))
    except SCIMError as e:
        return _scim_err(e)


@router.get("/v2/{tenant_slug}/ResourceTypes")
async def resource_types(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await _authn(request, tenant_slug, db)
        rts = scim_svc.resource_types(_base_url(request, tenant_slug))
        return _scim_json(scim_svc.scim_list_response(rts, len(rts), 1, len(rts)))
    except SCIMError as e:
        return _scim_err(e)


# ===========================================================================
# Users
# ===========================================================================
@router.get("/v2/{tenant_slug}/Users")
async def list_users(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        start, count = _paging(request)
        f = scim_svc.parse_username_filter(request.query_params.get("filter"))
        rows, total = await scim_svc.list_users(db, tenant_id, f, start, count)
        base = _base_url(request, tenant_slug)
        resources = [scim_svc.scim_user_resource(
            {"id": r["uid"], "email": r["email"], "first_name": r["first_name"],
             "last_name": r["last_name"], "status": r["status"], "role": r["role"]},
            {"scim_user_name": r["scim_user_name"], "external_id": r.get("external_id")}, base)
            for r in rows]
        return _scim_json(scim_svc.scim_list_response(resources, total, start, len(resources)))
    except SCIMError as e:
        return _scim_err(e)


@router.post("/v2/{tenant_slug}/Users")
async def create_user(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        body = await request.json()
        resource, status = await scim_svc.create_user(db, tenant_id, body, _base_url(request, tenant_slug))
        return _scim_json(resource, status)
    except SCIMError as e:
        return _scim_err(e)
    except Exception:
        logger.error("SCIM create_user failed")
        await scim_svc._audit(db, "scim_provisioning_failed", detail="create_user internal error", severity="medium")
        return _scim_err(SCIMError(400, "Invalid SCIM user payload", "invalidValue"))


@router.get("/v2/{tenant_slug}/Users/{user_id}")
async def get_user(tenant_slug: str, user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        return _scim_json(await scim_svc.get_user_resource(db, tenant_id, user_id, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.put("/v2/{tenant_slug}/Users/{user_id}")
async def replace_user(tenant_slug: str, user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        body = await request.json()
        return _scim_json(await scim_svc.replace_user(db, tenant_id, user_id, body, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.patch("/v2/{tenant_slug}/Users/{user_id}")
async def patch_user(tenant_slug: str, user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        body = await request.json()
        return _scim_json(await scim_svc.patch_user(db, tenant_id, user_id, body, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.delete("/v2/{tenant_slug}/Users/{user_id}")
async def delete_user(tenant_slug: str, user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        await scim_svc.delete_user(db, tenant_id, user_id)
        return Response(status_code=204)
    except SCIMError as e:
        return _scim_err(e)


# ===========================================================================
# Groups (minimal)
# ===========================================================================
@router.get("/v2/{tenant_slug}/Groups")
async def list_groups(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        start, count = _paging(request)
        return _scim_json(await scim_svc.list_groups(db, tenant_id, start, count, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.post("/v2/{tenant_slug}/Groups")
async def create_group(tenant_slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        body = await request.json()
        resource, status = await scim_svc.create_group(db, tenant_id, body, _base_url(request, tenant_slug))
        return _scim_json(resource, status)
    except SCIMError as e:
        return _scim_err(e)


@router.get("/v2/{tenant_slug}/Groups/{group_id}")
async def get_group(tenant_slug: str, group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        return _scim_json(await scim_svc.get_group_resource(db, tenant_id, group_id, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.patch("/v2/{tenant_slug}/Groups/{group_id}")
async def patch_group(tenant_slug: str, group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        body = await request.json()
        return _scim_json(await scim_svc.patch_group(db, tenant_id, group_id, body, _base_url(request, tenant_slug)))
    except SCIMError as e:
        return _scim_err(e)


@router.delete("/v2/{tenant_slug}/Groups/{group_id}")
async def delete_group(tenant_slug: str, group_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = await _authn(request, tenant_slug, db)
        await scim_svc.delete_group(db, tenant_id, group_id)
        return Response(status_code=204)
    except SCIMError as e:
        return _scim_err(e)


# ===========================================================================
# Admin token management (local JWT auth, admin only)
# ===========================================================================
class CreateTokenRequest(BaseModel):
    name: str
    expires_days: Optional[int] = None


async def _event(event_type, request, **kw):
    from app.services.security_events import record_event
    try:
        await record_event(event_type, request=request, **kw)
    except Exception:
        logger.debug("scim admin event failed (non-fatal)")


@router.get("/admin/tokens")
async def admin_list_tokens(request: Request, db: AsyncSession = Depends(get_db),
                            user: dict = Depends(require_role("super_admin", "admin", "owner"))):
    tenant_id = user.get("tenant_id") or 1
    tokens = await scim_svc.list_scim_tokens(db, tenant_id)
    # metadata only — never token_hash or raw token
    return {"tokens": [{
        "id": t["id"], "name": t["name"], "token_prefix": t.get("token_prefix"),
        "scopes": t["scopes"], "created_at": str(t["created_at"]),
        "last_used_at": str(t["last_used_at"]) if t.get("last_used_at") else None,
        "expires_at": str(t["expires_at"]) if t.get("expires_at") else None,
        "revoked_at": str(t["revoked_at"]) if t.get("revoked_at") else None,
    } for t in tokens]}


@router.post("/admin/tokens", status_code=201)
async def admin_create_token(body: CreateTokenRequest, request: Request, db: AsyncSession = Depends(get_db),
                             user: dict = Depends(require_role("super_admin", "admin", "owner"))):
    tenant_id = user.get("tenant_id") or 1
    created = await scim_svc.create_scim_token(db, tenant_id, body.name, user["id"], body.expires_days)
    await _event("scim_token_created", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SCIM token '{body.name}' created (id={created['row']['id']})")
    row = created["row"]
    # raw token returned ONCE — never stored, never logged
    return {"id": row["id"], "name": row["name"], "token": created["raw_token"],
            "token_prefix": row["token_prefix"], "scopes": row["scopes"],
            "expires_at": str(row["expires_at"]) if row.get("expires_at") else None,
            "warning": "Copy this token now — it will not be shown again."}


@router.post("/admin/tokens/{token_id}/rotate")
async def admin_rotate_token(token_id: int, request: Request, db: AsyncSession = Depends(get_db),
                             user: dict = Depends(require_role("super_admin", "admin", "owner"))):
    tenant_id = user.get("tenant_id") or 1
    try:
        created = await scim_svc.rotate_scim_token(db, tenant_id, token_id, user["id"])
    except SCIMError as e:
        return _scim_err(e)
    await _event("scim_token_rotated", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SCIM token {token_id} rotated -> {created['row']['id']}")
    row = created["row"]
    return {"id": row["id"], "name": row["name"], "token": created["raw_token"],
            "token_prefix": row["token_prefix"], "rotated_from": token_id,
            "warning": "Copy this token now — it will not be shown again."}


@router.post("/admin/tokens/{token_id}/revoke")
async def admin_revoke_token(token_id: int, request: Request, db: AsyncSession = Depends(get_db),
                             user: dict = Depends(require_role("super_admin", "admin", "owner"))):
    tenant_id = user.get("tenant_id") or 1
    try:
        await scim_svc.revoke_scim_token(db, tenant_id, token_id, user["id"])
    except SCIMError as e:
        return _scim_err(e)
    await _event("scim_token_revoked", request, severity="medium", category="audit",
                 tenant_id=tenant_id, actor_user_id=user["id"], actor_email=user.get("email"),
                 detail=f"SCIM token {token_id} revoked")
    return {"id": token_id, "revoked": True}
