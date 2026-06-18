"""
Data Sources API.

Super-admin management of pluggable data sources ("connect your database").
Reading the dashboard FROM the active source is wired separately by the adapter
layer; this router is the registry: list / create / test / activate / delete.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routes.auth import require_role
from app.services import data_sources as ds
from app.config import logger

router = APIRouter()

_VALID_TYPES = {"postgres", "mongo"}


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
async def list_data_sources(_user: dict = Depends(require_role("super_admin"))):
    return {"sources": await ds.list_sources()}


@router.post("/test")
async def test_unsaved(cfg: TestConfig, _user: dict = Depends(require_role("super_admin"))):
    """Test a connection/mapping before saving it (the form's 'Test' button)."""
    ok, message = await ds.test_connection(cfg.type, cfg.connection, cfg.mapping)
    return {"ok": ok, "message": message}


@router.post("", status_code=201)
async def create_data_source(body: CreateSource, user: dict = Depends(require_role("super_admin"))):
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
    )
    logger.info("Data source created: id=%s type=%s by user=%s", source["id"], body.type, user.get("email"))
    return source


@router.post("/{source_id}/test")
async def test_saved(source_id: int, _user: dict = Depends(require_role("super_admin"))):
    source = await ds.get_source_with_connection(source_id)
    if not source:
        raise HTTPException(404, "Data source not found")
    ok, message = await ds.test_connection(source["type"], source.get("connection"), source["mapping"])
    await ds.record_test_result(source_id, ok, message)
    return {"ok": ok, "message": message}


@router.post("/{source_id}/activate")
async def activate(source_id: int, _user: dict = Depends(require_role("super_admin"))):
    if not await ds.set_active(source_id):
        raise HTTPException(404, "Data source not found")
    logger.info("Data source activated: id=%s", source_id)
    return {"ok": True, "active_id": source_id}


@router.delete("/{source_id}")
async def delete(source_id: int, _user: dict = Depends(require_role("super_admin"))):
    ok, message = await ds.delete_source(source_id)
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message}
