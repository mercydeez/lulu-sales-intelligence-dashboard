"""
Data Sources API.

Super-admin management of pluggable data sources ("connect your database").
Reading the dashboard FROM the active source is wired separately by the adapter
layer; this router is the registry: list / create / test / activate / delete.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.auth import require_role
from app.services import data_sources as ds
from app.config import logger, get_settings

router = APIRouter()

_VALID_TYPES = {"postgres", "mongo"}


def _require_connectors_enabled():
    """Connector testing opens outbound connections to operator-supplied hosts
    (SSRF/egress surface), so it is gated. Off by default in production."""
    if not get_settings().enable_data_source_connectors:
        raise HTTPException(
            status_code=403,
            detail="Data-source connectors are disabled. Set ENABLE_DATA_SOURCE_CONNECTORS=true to enable.",
        )


async def _audit(event: str, request: Request, user: dict, detail: str, severity: str = "low"):
    from app.services.security_events import record_event
    await record_event(event, severity=severity, category="audit", request=request,
                       tenant_id=user.get("tenant_id"), actor_user_id=user.get("id") or user.get("user_id"),
                       actor_email=user.get("email"), detail=detail)


class TestConfig(BaseModel):
    type: str = "postgres"
    connection: Optional[str] = None
    mapping: dict = Field(default_factory=dict)


class CreateSource(BaseModel):
    name: str
    type: str = "postgres"
    connection: Optional[str] = None
    mapping: dict = Field(default_factory=dict)


@router.get("")
async def list_data_sources(user: dict = Depends(require_role("super_admin", "regional_manager"))):
    return {"sources": await ds.list_sources(tenant_id=user.get("tenant_id") or 1)}


@router.post("/test")
async def test_unsaved(cfg: TestConfig, request: Request,
                       user: dict = Depends(require_role("super_admin", "regional_manager"))):
    """Test a connection/mapping before saving it (the form's 'Test' button)."""
    _require_connectors_enabled()
    ok, message = await ds.test_connection(cfg.type, cfg.connection, cfg.mapping)
    await _audit("data_source_tested", request, user,
                 f"Tested unsaved {cfg.type} source: {'ok' if ok else 'failed'}")
    return {"ok": ok, "message": message}


@router.post("", status_code=201)
async def create_data_source(body: CreateSource, request: Request,
                             user: dict = Depends(require_role("super_admin", "regional_manager"))):
    if body.type not in _VALID_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(_VALID_TYPES)}")
    if body.type == "postgres" and not body.connection:
        raise HTTPException(400, "A connection string is required for a postgres source")
    source = await ds.create_source(
        name=body.name.strip() or "Untitled source",
        source_type=body.type,
        connection=body.connection,
        mapping=body.mapping,
        user_id=user.get("id") or user.get("user_id"),
        tenant_id=user.get("tenant_id") or 1,
    )
    logger.info("Data source created: id=%s type=%s by user=%s", source["id"], body.type, user.get("email"))
    await _audit("data_source_created", request, user,
                 f"Created {body.type} source '{source['name']}' (id={source['id']})")
    return source


@router.post("/{source_id}/test")
async def test_saved(source_id: int, request: Request,
                     user: dict = Depends(require_role("super_admin", "regional_manager"))):
    _require_connectors_enabled()
    tenant_id = user.get("tenant_id") or 1
    source = await ds.get_source_with_connection(source_id, tenant_id=tenant_id)
    if not source:
        raise HTTPException(404, "Data source not found")
    ok, message = await ds.test_connection(source["type"], source.get("connection"), source["mapping"])
    await ds.record_test_result(source_id, ok, message, tenant_id=tenant_id)
    await _audit("data_source_tested", request, user,
                 f"Tested saved source id={source_id}: {'ok' if ok else 'failed'}")
    return {"ok": ok, "message": message}


@router.post("/{source_id}/activate")
async def activate(source_id: int, request: Request,
                   user: dict = Depends(require_role("super_admin", "regional_manager"))):
    tenant_id = user.get("tenant_id") or 1
    if not await ds.set_active(source_id, tenant_id=tenant_id):
        raise HTTPException(404, "Data source not found")
    logger.info("Data source activated: id=%s tenant=%s", source_id, tenant_id)
    await _audit("data_source_activated", request, user, f"Activated source id={source_id}")
    return {"ok": True, "active_id": source_id}


@router.delete("/{source_id}")
async def delete(source_id: int, request: Request,
                 user: dict = Depends(require_role("super_admin", "regional_manager"))):
    tenant_id = user.get("tenant_id") or 1
    ok, message = await ds.delete_source(source_id, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(400, message)
    await _audit("data_source_deleted", request, user, f"Deleted source id={source_id}", severity="medium")
    return {"ok": True, "message": message}
