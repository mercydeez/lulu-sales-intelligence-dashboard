"""
Bulk external-data import API (SCALE-2). Admin-only, tenant-scoped.
docs/product/specs/EXTERNAL_DATA_AT_SCALE.md §3.

Two ways in:
  * multipart upload (small/medium files) — streamed to the drop dir, never
    buffered in memory;
  * JSON {"path": "name.csv"} naming a file ALREADY in the drop dir — the
    600 GB path: files arrive server-side (scp/S3 sync/mounted volume), the
    API only triggers ingestion. Paths are confined to the drop dir; anything
    else is rejected (no arbitrary server file reads).

Ingestion runs as a background task; progress is ledger-backed via
GET /api/imports/bulk/{job_id} and survives restarts/resumes.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import logger
from app.auth_deps import require_role
from app.services.ingest import ingest_csv_file, job_status

router = APIRouter()

# MUST live outside /app: dev uvicorn watches /app for reload, and arriving
# bulk files would trigger server restarts mid-ingest. Default is writable for
# the non-root app user; production mounts a real volume and sets
# IMPORT_DROP_DIR to it.
DROP_DIR = os.getenv("IMPORT_DROP_DIR", "/tmp/import_drop")


def _safe_drop_path(name: str) -> str:
    """Resolve a file name inside the drop dir; refuse escapes."""
    p = os.path.realpath(os.path.join(DROP_DIR, name))
    if not p.startswith(os.path.realpath(DROP_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="path must be inside the import drop directory")
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="file not found in drop directory")
    return p


class PathIngestRequest(BaseModel):
    path: str          # file name (or relative path) inside the drop dir
    source_name: str = "external"


def _queue(background: BackgroundTasks, tenant_id: int,
           source_name: str, path: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    background.add_task(ingest_csv_file, tenant_id, source_name, path, job_id)
    logger.info(f"[bulk] job {job_id} queued: tenant={tenant_id} source={source_name}")
    return {"job_id": job_id, "status_url": f"/api/imports/bulk/{job_id}"}


@router.post("/bulk")
async def start_bulk_import(
    body: PathIngestRequest,
    background: BackgroundTasks,
    user: dict = Depends(require_role("super_admin", "admin")),
):
    """Ingest a CSV already in the server drop dir (the 600 GB path: files
    arrive via scp/S3 sync/volume mount; this only triggers ingestion).
    Uploads live at /bulk/upload — FastAPI cannot parse a JSON body and a
    multipart file on one endpoint."""
    tenant_id = user.get("tenant_id") or 1
    return _queue(background, tenant_id, body.source_name, _safe_drop_path(body.path))


@router.post("/bulk/upload")
async def start_bulk_import_upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(require_role("super_admin", "admin")),
):
    """Multipart variant for small/medium files — streamed to the drop dir in
    1 MB blocks, never buffered whole."""
    tenant_id = user.get("tenant_id") or 1
    os.makedirs(DROP_DIR, exist_ok=True)
    dest = os.path.join(DROP_DIR, f"upload_{uuid.uuid4().hex[:12]}.csv")
    with open(dest, "wb") as out:
        while True:
            block = await file.read(1024 * 1024)
            if not block:
                break
            out.write(block)
    return _queue(background, tenant_id, file.filename or "upload", dest)


@router.get("/bulk/{job_id}")
async def get_bulk_import_status(
    job_id: str,
    user: dict = Depends(require_role("super_admin", "admin")),
):
    return await job_status(job_id)
