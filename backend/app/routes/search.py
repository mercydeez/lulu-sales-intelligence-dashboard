"""
Global search — backs the ⌘K command palette. Tenant-scoped (runs on the request
session under RLS) and store-access-aware. Returns lightweight, typed hits across
the entities a user navigates to most: stores and items. Pages/actions are matched
client-side in the palette.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.auth_deps import get_current_user, get_accessible_store_ids

router = APIRouter()


@router.get("")
async def global_search(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(8, ge=1, le=20),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search stores + items by name for the authenticated tenant."""
    term = (q or "").strip()
    if len(term) < 2:
        return {"query": term, "results": []}

    tenant_id = user.get("tenant_id") or 1
    like = f"%{term}%"
    allowed = get_accessible_store_ids(user)  # [] => all (super_admin)

    results = []

    # Stores (respect store-access scope)
    store_where = ["tenant_id = :tid", "name ILIKE :like"]
    params = {"tid": tenant_id, "like": like, "limit": limit}
    if allowed:
        store_where.append("id = ANY(:allowed)")
        params["allowed"] = allowed
    store_rows = (await db.execute(text(
        f"SELECT id, name, location FROM stores WHERE {' AND '.join(store_where)} "
        "ORDER BY name LIMIT :limit"), params)).mappings().all()
    for r in store_rows:
        results.append({
            "type": "store", "id": r["id"], "title": r["name"],
            "subtitle": r.get("location") or "Store", "href": f"/analytics?store={r['id']}",
        })

    # Items (catalogue is tenant-wide)
    item_rows = (await db.execute(text(
        "SELECT id, name, category FROM items WHERE tenant_id = :tid AND name ILIKE :like "
        "ORDER BY name LIMIT :limit"), {"tid": tenant_id, "like": like, "limit": limit})).mappings().all()
    for r in item_rows:
        results.append({
            "type": "item", "id": r["id"], "title": r["name"],
            "subtitle": r.get("category") or "Item", "href": f"/inventory?item={r['id']}",
        })

    return {"query": term, "results": results[: limit * 2]}
