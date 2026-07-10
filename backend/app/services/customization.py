"""Per-tenant customization — the FLAG CATALOG and effective-config resolution.

This is the "Rolls-Royce spec sheet": every knob a client can have turned for them,
in one typed catalog. Per-tenant overrides live in the (previously dormant)
`tenants.settings` JSONB under the 'customizations' key; nothing else may write that
namespace. Effective value resolution is layered, most specific wins:

    catalog default  ->  plan floor/ceiling (plan_min)  ->  tenant override

CONTRACT NOTE (parallel development): the catalog keys, entry shape and function
signatures below are the pinned interface — the Atelier advisor (atelier_advisor.py)
prompts from FLAG_CATALOG, and flag ENFORCEMENT call sites (routes/ai.py,
routes/experience.py, routes/public_api.py) call resolve_effective()/flag_value().
Change a key name here and you change it everywhere.

HONESTY RULE: a flag that nothing enforces is a Potemkin toggle. Every key carries
`enforced_by` naming the code that honours it; 'planned' marks catalog entries whose
enforcement has not landed yet, and the console UI must render that honestly.

Plan gating: `plan_min` names the lowest plan that may enable the flag (order:
free < starter < growth < enterprise). resolve/set refuse an override that the
tenant's plan does not reach — the plan is the floor of what can be sold, the
override is the bespoke exception ON TOP of a qualifying plan, not a bypass.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

# Plan ladder used by plan_min checks (mirrors services/billing.py plans).
PLAN_ORDER = ["free", "starter", "growth", "enterprise"]

# The single JSONB namespace inside tenants.settings that this module owns.
SETTINGS_NAMESPACE = "customizations"

# ---------------------------------------------------------------------------
# The catalog. Entry shape (pinned):
#   key: {
#     "label": str, "description": str,
#     "category": "modules" | "assistant" | "interface" | "integrations" | "limits",
#     "type": "bool" | "enum" | "int",
#     "default": Any,
#     "options": [..]            # enum only
#     "min"/"max": int           # int only
#     "plan_min": str | None,    # lowest plan allowed to enable/raise this
#     "enforced_by": str,        # code path that honours it, or "planned"
#   }
# ---------------------------------------------------------------------------
FLAG_CATALOG: Dict[str, Dict[str, Any]] = {
    # --- modules: whole product areas a client can have hidden/shown -------
    "modules.forecasting": {
        "label": "Forecasting & Forecast Lab", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Demand forecasts, Ramadan model, Forecast Lab pages.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },
    "modules.promotions": {
        "label": "Promotions & Pricing", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Promotion planning, uplift/cannibalisation analytics.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },
    "modules.procurement": {
        "label": "Procurement & Suppliers", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Purchase orders, goods receipts, supplier invoices.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },
    "modules.inventory": {
        "label": "Inventory Management", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Stock levels, reorder points, transfers.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },
    "modules.reports": {
        "label": "Reports & Exports", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Scheduled and ad-hoc reports, CSV/Excel exports.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },
    "modules.diagnostics": {
        "label": "Diagnostics & Findings", "category": "modules", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Root-cause findings feed from the diagnostics worker.",
        "enforced_by": "routes/experience.py (nav + zones)",
    },

    # --- assistant: Sage behaviour -----------------------------------------
    "assistant.ai_chat": {
        "label": "Sage AI chat", "category": "assistant", "type": "bool",
        "default": True, "plan_min": None,
        "description": "The Sage assistant panel and /api/ai/chat endpoints.",
        "enforced_by": "routes/ai.py require_ai_chat",
    },
    "assistant.voice": {
        "label": "Voice chat", "category": "assistant", "type": "bool",
        "default": False, "plan_min": "growth",
        "description": "Speech-to-text / text-to-speech on top of Sage.",
        "enforced_by": "routes/ai.py require_voice_chat",
    },
    "assistant.mode": {
        "label": "Assistant surface", "category": "assistant", "type": "enum",
        "default": "panel", "options": ["panel", "copilot", "hidden"], "plan_min": None,
        "description": "How Sage appears: right-rail panel, proactive copilot feed, or hidden.",
        "enforced_by": "routes/experience.py (assistant_mode)",
    },

    # --- interface: look & behaviour ---------------------------------------
    "interface.default_theme": {
        "label": "Default theme", "category": "interface", "type": "enum",
        "default": "system", "options": ["light", "dark", "system"], "plan_min": None,
        "description": "Theme new users of this tenant start with (they can still toggle).",
        "enforced_by": "planned",
    },
    "interface.compact_tables": {
        "label": "Compact tables", "category": "interface", "type": "bool",
        "default": False, "plan_min": None,
        "description": "Denser row spacing across data tables.",
        "enforced_by": "planned",
    },
    "interface.landing_page": {
        "label": "Landing page", "category": "interface", "type": "enum",
        "default": "dashboard", "options": ["dashboard", "sales", "inventory"], "plan_min": None,
        "description": "Where users land after login.",
        "enforced_by": "planned",
    },

    # --- integrations: external surfaces -----------------------------------
    "integrations.public_api": {
        "label": "Public API", "category": "integrations", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Per-tenant kill-switch for the API-key public API (lsk_ keys).",
        "enforced_by": "routes/public_api.py",
    },
    "integrations.webhooks": {
        "label": "Outbound webhooks", "category": "integrations", "type": "bool",
        "default": True, "plan_min": None,
        "description": "Tenant-configured outbound event webhooks.",
        "enforced_by": "planned",
    },
    "integrations.pos": {
        "label": "POS connector", "category": "integrations", "type": "bool",
        "default": False, "plan_min": "growth",
        "description": "POS vendor connections + nightly basket-grain sync (E2-1).",
        "enforced_by": "planned",
    },
    "integrations.payments": {
        "label": "Payment collection", "category": "integrations", "type": "bool",
        "default": False, "plan_min": "growth",
        "description": "Hosted-checkout payment intents for invoices (E8-2).",
        "enforced_by": "planned",
    },
    "integrations.einvoicing": {
        "label": "E-invoicing", "category": "integrations", "type": "bool",
        "default": False, "plan_min": "growth",
        "description": "UAE e-invoice submission/clearance harness (E10-4).",
        "enforced_by": "planned",
    },
    "integrations.imports_scheduled": {
        "label": "Scheduled imports (SFTP/IMAP)", "category": "integrations", "type": "bool",
        "default": False, "plan_min": "starter",
        "description": "Recurring imports over HTTPS/SFTP/IMAP (E2-2).",
        "enforced_by": "planned",
    },

    # --- limits: numeric overrides (0 = use the plan default) --------------
    "limits.sage_messages_per_day": {
        "label": "Sage messages / day", "category": "limits", "type": "int",
        "default": 0, "min": 0, "max": 100000, "plan_min": None,
        "description": "Per-tenant override of the plan's Sage quota. 0 = plan default.",
        "enforced_by": "planned",
    },
    "limits.export_rows": {
        "label": "Max export rows", "category": "limits", "type": "int",
        "default": 50000, "min": 1000, "max": 1000000, "plan_min": None,
        "description": "Ceiling on rows per report/CSV export.",
        "enforced_by": "planned",
    },
    "limits.api_rate_multiplier": {
        "label": "API rate multiplier", "category": "limits", "type": "int",
        "default": 1, "min": 1, "max": 10, "plan_min": "growth",
        "description": "Multiplies the per-key public-API rate limit for this tenant.",
        "enforced_by": "planned",
    },
}


def catalog() -> List[Dict[str, Any]]:
    """The catalog as a list for the API/UI, key embedded."""
    return [{"key": k, **v} for k, v in FLAG_CATALOG.items()]


def validate_value(key: str, value: Any) -> Tuple[bool, Optional[str]]:
    """Validate a proposed override value against the catalog entry. Pure."""
    entry = FLAG_CATALOG.get(key)
    if entry is None:
        return False, f"Unknown customization key {key!r}"
    t = entry["type"]
    if t == "bool":
        if not isinstance(value, bool):
            return False, f"{key} expects a boolean"
    elif t == "enum":
        if value not in entry.get("options", []):
            return False, f"{key} must be one of {entry.get('options')}"
    elif t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return False, f"{key} expects an integer"
        lo, hi = entry.get("min"), entry.get("max")
        if lo is not None and value < lo:
            return False, f"{key} must be >= {lo}"
        if hi is not None and value > hi:
            return False, f"{key} must be <= {hi}"
    return True, None


def plan_allows(key: str, plan: Optional[str]) -> bool:
    """Whether a tenant on `plan` may have this flag enabled/raised. Pure."""
    entry = FLAG_CATALOG.get(key) or {}
    need = entry.get("plan_min")
    if not need:
        return True
    try:
        return PLAN_ORDER.index(plan or "free") >= PLAN_ORDER.index(need)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# DB-backed resolution — IMPLEMENTED by the customization-engine change; the
# signatures are the pinned contract for enforcement call sites, which must treat
# any exception (including NotImplementedError before that change lands) as
# "no override" and fall back to catalog defaults. Fail-open on infrastructure,
# fail-closed on access — the gate in front of the console does the latter.
# ---------------------------------------------------------------------------

def _as_override_map(raw: Any) -> Dict[str, Any]:
    """Coerce whatever the driver hands back for settings->'customizations' into a
    dict. asyncpg normally decodes JSONB to dict; a str (no codec) is parsed; any
    other shape (null, list, scalar, corrupt text) is treated as 'no overrides' —
    defensive, never raises."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


async def get_overrides(db, tenant_id: int) -> Dict[str, Any]:
    """The raw override map from tenants.settings->'customizations'."""
    raw = (await db.execute(
        text("SELECT settings->'customizations' FROM tenants WHERE id = CAST(:t AS integer)"),
        {"t": tenant_id},
    )).scalar()
    return _as_override_map(raw)


async def resolve_effective(db, tenant_id: int) -> Dict[str, Dict[str, Any]]:
    """{key: {"value": Any, "source": "default"|"plan"|"override"}} for every
    catalog key, after layering defaults -> plan gating -> overrides."""
    row = (await db.execute(
        text("SELECT plan, settings->'customizations' FROM tenants WHERE id = CAST(:t AS integer)"),
        {"t": tenant_id},
    )).fetchone()
    plan = row[0] if row else None
    overrides = _as_override_map(row[1] if row else None)
    effective: Dict[str, Dict[str, Any]] = {}
    for key, entry in FLAG_CATALOG.items():
        default = entry["default"]
        if key in overrides:
            candidate = overrides[key]
            ok, _err = validate_value(key, candidate)
            if not ok:
                # Invalid-typed stored value: ignored, treated as absent.
                effective[key] = {"value": default, "source": "default"}
            elif not plan_allows(key, plan):
                # The plan is a floor — an override never bypasses it.
                effective[key] = {"value": default, "source": "plan"}
            else:
                effective[key] = {"value": candidate, "source": "override"}
        else:
            effective[key] = {"value": default, "source": "default"}
    return effective


async def flag_value(db, tenant_id: int, key: str) -> Any:
    """Convenience: the effective value of one flag (catalog default if unset)."""
    if key not in FLAG_CATALOG:
        raise KeyError(key)
    effective = await resolve_effective(db, tenant_id)
    return effective[key]["value"]


async def set_override(db, tenant_id: int, key: str, value: Any, *, actor: str) -> Dict[str, Any]:
    """Validate + write one override into the namespace (merge, never clobber the
    column); audits via security_events. Returns the new effective entry."""
    ok, err = validate_value(key, value)
    if not ok:
        raise ValueError(err)
    plan = (await db.execute(
        text("SELECT plan FROM tenants WHERE id = CAST(:t AS integer)"),
        {"t": tenant_id},
    )).scalar()
    if not plan_allows(key, plan):
        need = FLAG_CATALOG[key].get("plan_min")
        raise ValueError(
            f"{key} requires plan '{need}' or higher; tenant {tenant_id} is on "
            f"'{plan or 'free'}' — the plan is the floor, overrides never bypass it"
        )
    # MERGE into the 'customizations' namespace only — never assign the whole
    # settings column (that would clobber every other namespace). Binds are CAST
    # explicitly: untyped binds take neighbouring literal types (known bug class).
    await db.execute(
        text("""
            UPDATE tenants
               SET settings = jsonb_set(
                       COALESCE(settings, '{}'::jsonb),
                       '{customizations}',
                       COALESCE(settings->'customizations', '{}'::jsonb)
                           || jsonb_build_object(CAST(:key AS text), CAST(:val AS jsonb)),
                       true),
                   updated_at = now()
             WHERE id = CAST(:t AS integer)
        """),
        {"key": key, "val": json.dumps(value), "t": tenant_id},
    )
    from app.services.security_events import record_event
    await record_event("customization_changed", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_email=actor,
                       detail=f"{key} -> {value!r}")
    # Having just passed validate_value + plan_allows, the layering rule makes the
    # new effective entry exactly this — no re-read needed. Caller commits.
    return {"value": value, "source": "override"}


async def clear_override(db, tenant_id: int, key: str, *, actor: str) -> None:
    """Remove one override (revert to plan/default); audits via security_events."""
    if key not in FLAG_CATALOG:
        raise ValueError(f"Unknown customization key {key!r}")
    # `-` on the namespace object only; COALESCE guards a null/missing namespace
    # so jsonb_set never nulls out the whole settings column.
    await db.execute(
        text("""
            UPDATE tenants
               SET settings = jsonb_set(
                       COALESCE(settings, '{}'::jsonb),
                       '{customizations}',
                       COALESCE(settings->'customizations', '{}'::jsonb) - CAST(:key AS text),
                       true),
                   updated_at = now()
             WHERE id = CAST(:t AS integer)
        """),
        {"key": key, "t": tenant_id},
    )
    from app.services.security_events import record_event
    await record_event("customization_cleared", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_email=actor,
                       detail=f"{key} override cleared (reverts to plan/default)")
