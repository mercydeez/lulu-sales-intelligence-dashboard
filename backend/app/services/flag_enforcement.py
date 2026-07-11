"""
Fail-open enforcement for per-tenant customization flags (Platform Console, B7).

`customization.resolve_effective` is the DB-backed flag engine (implemented by a
parallel change; it raises NotImplementedError until that merges). Every
enforcement call site (routes/ai.py, routes/public_api.py, routes/experience.py)
goes through this module so the failure policy lives in exactly one place:

- FAIL-OPEN on infrastructure: any exception from the engine (DB down, engine
  not merged yet, malformed data) means "no restriction" — the call site
  behaves as if the flag allows. A customization toggle may degrade the
  experience; it must never take the product down by accident.
- FAIL-CLOSED on access stays where it always was: the role/permission gates
  (require_ai_chat / require_voice_chat, API-key auth, RBAC) run BEFORE any
  flag check and remain the floor. Flags can only narrow what those gates
  already allowed, never widen it.
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from app.services import customization

# In-process TTL cache: {tenant_id: (expires_ts, flags)} — ADVISORY ONLY. Each
# worker process keeps its own copy, so after a console change another worker
# may serve flags up to TTL stale; that is acceptable (30s max) because these
# flags gate product surface, not access control (the role gates above are the
# fail-closed floor and are never cached here).
_TTL_SECONDS = 30.0
_cache: Dict[int, Tuple[float, dict]] = {}


async def effective_flags(tenant_id: int) -> Optional[dict]:
    """The tenant's effective flag map {key: {"value", "source"}}, or None.

    None means "the engine could not answer" (unmerged / DB unavailable /
    broken); callers must fall back to their defaults — fail-open.
    """
    now = time.monotonic()
    hit = _cache.get(tenant_id)
    if hit is not None and hit[0] > now:
        return hit[1]
    try:
        # Owner session: flag resolution is platform plumbing, not tenant data
        # access — RLS scoping happens at the data endpoints themselves.
        from app.services.database import async_session
        async with async_session() as db:
            flags = await customization.resolve_effective(db, tenant_id)
    except Exception:
        return None  # fail-open; never cache a failure — retry next request
    _cache[tenant_id] = (now + _TTL_SECONDS, flags)
    return flags


async def flag_allows(tenant_id: Optional[int], key: str, default: bool = True) -> bool:
    """Whether boolean flag `key` permits the action for this tenant.

    No tenant, no engine (effective_flags → None), or a malformed/missing
    entry → `default` (fail-open).
    """
    if tenant_id is None:
        return default
    flags = await effective_flags(tenant_id)
    if flags is None:
        return default
    entry = flags.get(key)
    if not isinstance(entry, dict) or "value" not in entry:
        return default
    return bool(entry["value"])


def invalidate(tenant_id: Optional[int] = None) -> None:
    """Drop cached flags for one tenant (or all when None). For tests and for
    console writes that want their own worker to reflect a change immediately."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)
