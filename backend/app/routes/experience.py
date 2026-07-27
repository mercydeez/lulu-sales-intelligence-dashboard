"""
Role Experience API (Experience API v2 — Sage Copilot). Mounted at /api/experience.

Returns the caller's resolved experience config — persona pack, assistant mode,
homepage layout/zones, KPI descriptors, navigation manifest, quick actions, AI
display context, capabilities, decision scope — so the frontend renders the
entire role experience from configuration instead of duplicated pages or
hardcoded role checks.

Security: `resolve_config` strips the persona's server-only prompt fragment, so
no system-prompt text is ever returned here; AI authorization stays server-side
in `routes/ai.py`. `capabilities` are rendering hints only.

B7 (Platform Console): per-tenant customization flags are overlaid on the role
config — disabled `modules.*` flags strip their nav entries, assistant flags
NARROW the capability hints (never widen), and an explicit `assistant.mode`
override replaces the role's default surface. Fail-open: when the flag engine
is unavailable the role config ships unchanged.
"""
from fastapi import APIRouter, Depends

from app.auth_deps import get_current_user, get_accessible_store_ids
from app.services.flag_enforcement import effective_flags
from app.services.role_experience import resolve_config, VALID_ASSISTANT_MODES

router = APIRouter(tags=["Experience"])

# B7: per-tenant module flags → the nav entries they own, keyed by href (the
# stable route identifier shared by role_experience nav manifests and the
# frontend's config/nav.tsx). Only CLEAR matches are mapped; an href not named
# here is NEVER stripped — unmapped nav items are out of scope for module
# toggles, not implicitly disabled.
_MODULE_NAV_HREFS = {
    "modules.forecasting": {"/forecast-lab"},
    "modules.promotions": {"/promotions"},
    "modules.procurement": {"/procurement"},
    "modules.inventory": {"/inventory"},
    "modules.reports": {"/reports"},
    "modules.diagnostics": {"/insights"},  # the diagnostics findings feed page
}


def _flag_value(flags: dict, key: str, default):
    """The effective value of one flag entry ({"value","source"}), or default."""
    entry = flags.get(key)
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return default


def _apply_customizations(cfg: dict, flags: dict) -> None:
    """Overlay the tenant's customization flags onto the resolved role config.

    Mutates `cfg` (already a deep copy from resolve_config). Capabilities may
    only NARROW (role hint AND flag) — a flag can hide a surface the role had,
    never grant one the role lacked.
    """
    # (a) Disabled module flags strip their mapped nav entries. nav=None means
    #     "full built-in sidebar" (client-rendered) and is left untouched here.
    nav = cfg.get("nav")
    if isinstance(nav, list):
        disabled_hrefs = set()
        for key, hrefs in _MODULE_NAV_HREFS.items():
            if _flag_value(flags, key, True) is False:
                disabled_hrefs |= hrefs
        if disabled_hrefs:
            cfg["nav"] = [item for item in nav if item.get("href") not in disabled_hrefs]

    # (b) Assistant capability hints: narrow-only (never widen).
    caps = cfg.get("capabilities") or {}
    caps["ai_chat"] = caps.get("ai_chat", True) and bool(_flag_value(flags, "assistant.ai_chat", True))
    caps["voice"] = caps.get("voice", True) and bool(_flag_value(flags, "assistant.voice", True))
    cfg["capabilities"] = caps

    # (c) Only an explicit per-tenant OVERRIDE replaces the role's assistant
    #     surface; default/plan-sourced values leave the role's choice alone
    #     (the role config is itself the product default for that surface).
    mode = flags.get("assistant.mode")
    if isinstance(mode, dict) and mode.get("source") == "override" \
            and mode.get("value") in VALID_ASSISTANT_MODES:
        cfg["assistant_mode"] = mode["value"]


@router.get("")
async def get_experience(user: dict = Depends(get_current_user)):
    """The caller's role experience config (server-driven UI, v2)."""
    cfg = resolve_config(user.get("role"))
    # B7: overlay per-tenant customizations — fail-open: no engine, no change.
    tenant_id = user.get("tenant_id")
    flags = await effective_flags(tenant_id) if tenant_id is not None else None
    if flags is not None:
        _apply_customizations(cfg, flags)
    allowed = get_accessible_store_ids(user) or []
    cfg["context"] = {
        "accessible_store_count": len(allowed),
    }
    return cfg
