"""Atelier Advisor routes (Platform Console) — mounted at /api/ai/atelier.

Developers-only chatbox: describe what a client wants in plain language, get back
configuration suggestions mapped to the customization catalog plus honest
"file it as bespoke work" gaps. Guarded by the platform-developer boundary
(services/platform_access.py) and the universal prompt-injection screen
(services/guardrails/entry.py) BEFORE any LLM sees the text.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.atelier_advisor import suggest
from app.services.guardrails.entry import screen_input
from app.services.platform_access import require_platform_developer
from app.services.security_events import record_event

router = APIRouter(tags=["Atelier"])


class SuggestRequest(BaseModel):
    description: str = Field(..., min_length=3, max_length=4000)
    tenant_id: Optional[int] = None


async def _tenant_context(tenant_id: Optional[int]) -> Optional[dict]:
    """Best-effort tenant context (plan + effective flag values) for the prompt.

    resolve_effective() is a NotImplementedError stub in this worktree — the
    customization-engine unit implements it in parallel; post-merge this starts
    returning real context. By design ANY failure here (stub, DB down, unknown
    tenant) degrades to None and the advisor proceeds without tenant context.
    """
    if tenant_id is None:
        return None
    try:
        from sqlalchemy import text

        from app.services.customization import resolve_effective
        from app.services.database import async_session

        async with async_session() as db:
            row = (await db.execute(
                text("SELECT plan FROM tenants WHERE id = :tid"), {"tid": tenant_id}
            )).fetchone()
            effective = await resolve_effective(db, tenant_id)
            return {
                "plan": row[0] if row else None,
                "effective": {k: (v or {}).get("value") for k, v in (effective or {}).items()},
            }
    except Exception:  # noqa: BLE001
        return None


@router.post("/suggest")
async def suggest_configuration(
    body: SuggestRequest,
    user: dict = Depends(require_platform_developer),
):
    """Map a plain-language client need onto the customization catalog."""
    # Prompt-injection screen runs FIRST — a flagged description never reaches
    # a prompt. screen_input returns a refusal string when a BLOCK rail trips.
    if screen_input(body.description, trace_id="atelier") is not None:
        raise HTTPException(status_code=422, detail="description was flagged by the input screen")

    tenant_context = await _tenant_context(body.tenant_id)
    result = await suggest(body.description, tenant_context=tenant_context)

    await record_event(
        "atelier_suggestion", category="audit", severity="low",
        tenant_id=body.tenant_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        detail=(
            f"engine={result['engine']}, {len(result['suggestions'])} suggestions, "
            f"{len(result['gaps'])} gaps"
        ),
    )
    return result
