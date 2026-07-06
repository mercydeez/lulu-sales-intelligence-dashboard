"""
Role Experience Engine (ROLE_EXPERIENCE_BLUEPRINT.md, Wave 1).

One engine, many experiences: each role gets a CONFIG — persona pack, homepage
zone list, KPI descriptors, navigation manifest, decision scope, notification
defaults — and generic surfaces render from it. Adding a role = adding a config
here, not building screens.

Wave 1 covers the roles that exist in RBAC today (`store_manager`,
`regional_manager`) plus a `_default` that preserves current behavior for every
other role (super_admin, admin, ...). Roles that need data we don't have
(HR attendance, Loss Prevention POS grain) are intentionally absent.

Design rules:
- Configs are DATA. No role-specific code paths anywhere else.
- KPI descriptors point at fields of EXISTING endpoints (kpis / decisions
  summary / inventory summary) — the engine never invents a number.
- `nav` entries reference EXISTING routes only; `_default: None` means "use the
  full built-in sidebar" (unchanged behavior).
- Persona prompt fragments are appended to Sage's system prompt; they tune voice
  and focus but can never override the grounding/honesty rules (which are
  declared to take precedence over everything, including this fragment).
- `decision_scope` drives real filtering in the Decision Center:
  chain = everything · region/store = only decisions about your stores.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

# KPI descriptor sources → existing endpoints (frontend fetches these):
#   kpis      -> GET /api/kpis
#   decisions -> GET /api/decisions/summary
#   inventory -> GET /api/inventory/summary
VALID_KPI_SOURCES = {"kpis", "decisions", "inventory"}
VALID_KPI_FORMATS = {"aed", "units", "int", "trend"}
VALID_SCOPES = {"chain", "region", "store"}

_CONFIGS: Dict[Optional[str], Dict] = {
    # ── Store Manager — "Store Coach" (phone-first; today only) ─────────────
    "store_manager": {
        "key": "store_manager",
        "home": "/today",
        "decision_scope": "store",
        "persona": {
            "name": None,  # filled with settings.chatbot_name at resolve time
            "title": "Store Coach",
            "tagline": "Your store, today",
            "greeting": "Here's your store today — three things before anything else.",
            "voice": ["concrete", "shelf-level", "today-focused", "brief"],
            "prompt_fragment": (
                "PERSONA — STORE COACH: You are speaking to the STORE MANAGER of a single "
                "store. Be their store coach: concrete, brief, shelf-level, focused on TODAY "
                "— deliveries, stockouts, tasks, today's number vs the week. Lead with the one "
                "thing to do next. Prefer units for volume and AED only for value. Avoid chain "
                "strategy and long-range analysis unless they explicitly ask."
            ),
        },
        "zones": [
            {"type": "verdict"},
            {"type": "kpis"},
            {"type": "decisions", "props": {"limit": 3, "title": "Decide now"}},
            {"type": "stock"},
        ],
        # KPIs are today-focused (a store manager's frame) + counts. The 7-day
        # revenue lives in the hero verdict alone, so it never appears twice with
        # two different figures.
        "kpis": [
            {"key": "today_units", "label": "Sold today", "source": "kpis",
             "field": "total_sales_today", "format": "units"},
            {"key": "today_revenue", "label": "Revenue today", "source": "kpis",
             "field": "total_revenue_today", "format": "aed"},
            {"key": "stockouts_now", "label": "Out of stock", "source": "inventory",
             "field": "out_of_stock_count", "format": "int"},
            {"key": "low_stock", "label": "Running low", "source": "inventory",
             "field": "low_stock_count", "format": "int"},
            {"key": "decisions_pending", "label": "To review", "source": "decisions",
             "field": "pending", "format": "int"},
        ],
        "nav": [
            {"key": "today", "tKey": "nav.today", "label": "Today", "href": "/today", "icon": "Sunrise"},
            {"key": "my_work", "tKey": "nav.myWork", "label": "My Work", "href": "/decisions", "icon": "Scale"},
            {"key": "my_store", "tKey": "nav.myStore", "label": "My Store", "href": "/inventory", "icon": "Store"},
            {"key": "alerts", "tKey": "nav.alerts", "label": "Alerts", "href": "/alerts", "icon": "Bell"},
        ],
        "notifications": {"brief_hour_gst": 7, "quiet_hours": [22, 7], "tiers": ["T1 open brief", "T0 store criticals only"]},
    },

    # ── Regional Manager — "Regional Coach" (league table; approvals) ───────
    "regional_manager": {
        "key": "regional_manager",
        "home": "/today",
        "decision_scope": "region",
        "persona": {
            "name": None,
            "title": "Regional Coach",
            "tagline": "Your stores, compared",
            "greeting": "Here's how your region looks this morning.",
            "voice": ["comparative", "store-by-store", "action-first"],
            "prompt_fragment": (
                "PERSONA — REGIONAL COACH: You are speaking to a REGIONAL MANAGER responsible "
                "for several stores. Be their regional coach: comparative, league-table "
                "thinking across THEIR stores. Name stores explicitly, lead with the store "
                "that most needs attention and why, and connect answers to pending approvals "
                "or transfers when relevant. Week-over-week movement matters more than "
                "long-range trends."
            ),
        },
        "zones": [
            {"type": "verdict"},
            {"type": "kpis"},
            {"type": "decisions", "props": {"limit": 3, "title": "Decide now"}},
            {"type": "approvals"},
        ],
        # The 7-day region revenue is stated once, in the hero verdict; KPIs add
        # movement + workload rather than repeating it with a second figure.
        "kpis": [
            {"key": "week_units", "label": "Volume (7d)", "source": "kpis",
             "field": "total_sales_week", "format": "units"},
            {"key": "revenue_trend", "label": "Trend", "source": "kpis",
             "field": "revenue_trend", "format": "trend"},
            {"key": "stockouts_now", "label": "Out of stock", "source": "inventory",
             "field": "out_of_stock_count", "format": "int"},
            {"key": "decisions_pending", "label": "Decisions waiting", "source": "decisions",
             "field": "pending", "format": "int"},
            {"key": "at_stake", "label": "At stake /wk", "source": "decisions",
             "field": "at_stake_aed_per_week", "format": "aed"},
        ],
        "nav": [
            {"key": "today", "tKey": "nav.today", "label": "Today", "href": "/today", "icon": "Sunrise"},
            {"key": "my_work", "tKey": "nav.myWork", "label": "My Work", "href": "/decisions", "icon": "Scale"},
            {"key": "approvals", "tKey": "nav.approvals", "label": "Approvals", "href": "/approvals", "icon": "Inbox"},
            {"key": "my_stores", "tKey": "nav.myStores", "label": "My Stores", "href": "/analytics", "icon": "BarChart3"},
            {"key": "alerts", "tKey": "nav.alerts", "label": "Alerts", "href": "/alerts", "icon": "Bell"},
        ],
        "notifications": {"brief_hour_gst": 7, "quiet_hours": [22, 6], "tiers": ["T1 region brief", "T0 store critical / stuck transfer"]},
    },

    # ── Procurement Manager — "Supply Chain Expert" (the Buying Desk) ───────
    # Chain-wide operator: sees replenishment across every store. Ready for a
    # `procurement_manager` RBAC role; until one is provisioned, no user resolves
    # to it (the engine simply never selects it). Built only on data we have —
    # PO queue (procurement approvals), replenishment decisions, stock pressure.
    "procurement_manager": {
        "key": "procurement_manager",
        "home": "/today",
        "decision_scope": "chain",
        "persona": {
            "name": None,
            "title": "Supply Chain Expert",
            "tagline": "Right stock, right terms",
            "greeting": "Here's your buying desk — the orders and suppliers that need you today.",
            "voice": ["terms-savvy", "supplier-memory", "lead-time-aware"],
            "prompt_fragment": (
                "PERSONA — SUPPLY CHAIN EXPERT: You are speaking to a PROCUREMENT MANAGER who "
                "buys for the whole chain. Think in POs, suppliers, lead times, terms and "
                "renewals. Lead with which orders are urgent and which suppliers need attention. "
                "Use units for order quantities and AED for spend/value; call out over-ordering "
                "(overstock) as clearly as shortfalls. Keep it to what the data shows — never "
                "invent a supplier, price, or lead time that isn't in the context."
            ),
        },
        "zones": [
            {"type": "verdict"},
            {"type": "kpis"},
            {"type": "approvals"},
            {"type": "decisions", "props": {"limit": 3, "title": "Buys that need you"}},
        ],
        "kpis": [
            {"key": "stockouts_now", "label": "Out of stock", "source": "inventory",
             "field": "out_of_stock_count", "format": "int"},
            {"key": "low_stock", "label": "Running low", "source": "inventory",
             "field": "low_stock_count", "format": "int"},
            {"key": "overstock", "label": "Overstocked", "source": "inventory",
             "field": "overstocked_count", "format": "int"},
            {"key": "decisions_pending", "label": "Buys waiting", "source": "decisions",
             "field": "pending", "format": "int"},
            {"key": "at_stake", "label": "At stake /wk", "source": "decisions",
             "field": "at_stake_aed_per_week", "format": "aed"},
        ],
        "nav": [
            {"key": "today", "tKey": "nav.today", "label": "Today", "href": "/today", "icon": "Sunrise"},
            {"key": "po_queue", "tKey": "nav.poQueue", "label": "PO Queue", "href": "/approvals", "icon": "Inbox"},
            {"key": "buying", "tKey": "nav.buying", "label": "Buying", "href": "/procurement", "icon": "Truck"},
            {"key": "my_work", "tKey": "nav.myWork", "label": "My Work", "href": "/decisions", "icon": "Scale"},
            {"key": "stock", "tKey": "nav.stock", "label": "Stock", "href": "/inventory", "icon": "Package"},
        ],
        "notifications": {"brief_hour_gst": 8, "quiet_hours": [22, 6], "tiers": ["T1 buying brief 08:30", "T0 supplier failure blocking top sellers"]},
    },

    # ── Default — preserves today's behavior for every other role ───────────
    None: {
        "key": "_default",
        "home": "/",             # keep the existing dashboard as home
        "decision_scope": "chain",
        "persona": {
            "name": None,
            "title": "Retail Analyst",
            "tagline": "Chain-wide, grounded answers",
            "greeting": "I'm watching the whole business — ask me anything about your data.",
            "voice": ["precise", "chain-wide", "evidence-first"],
            # No fragment: the base system prompt already is the chain-wide analyst.
            "prompt_fragment": "",
        },
        "zones": [
            {"type": "verdict"},
            {"type": "kpis"},
            {"type": "decisions", "props": {"limit": 3, "title": "Decide now"}},
        ],
        "kpis": [
            {"key": "week_revenue", "label": "Revenue (7d)", "source": "kpis",
             "field": "total_revenue_week", "format": "aed"},
            {"key": "week_units", "label": "Volume (7d)", "source": "kpis",
             "field": "total_sales_week", "format": "units"},
            {"key": "decisions_pending", "label": "Decisions waiting", "source": "decisions",
             "field": "pending", "format": "int"},
            {"key": "at_stake", "label": "At stake /wk", "source": "decisions",
             "field": "at_stake_aed_per_week", "format": "aed"},
        ],
        "nav": None,             # None = use the full built-in sidebar (unchanged)
        "notifications": {"brief_hour_gst": 7, "quiet_hours": [22, 6], "tiers": ["T1 daily brief"]},
    },
}


def resolve_config(role: Optional[str]) -> Dict:
    """The role's experience config (deep copy — callers may not mutate the
    registry). Unknown roles get the default, so new roles degrade gracefully."""
    cfg = copy.deepcopy(_CONFIGS.get(role) or _CONFIGS[None])
    # Persona name follows the configured chatbot name (single source of truth).
    try:
        from app.config import get_settings
        cfg["persona"]["name"] = get_settings().chatbot_name
    except Exception:
        cfg["persona"]["name"] = cfg["persona"]["name"] or "Sage"
    cfg["role"] = role or "_unknown"
    return cfg


def decision_scope_for(role: Optional[str]) -> str:
    """chain | region | store — drives Decision Center filtering."""
    return (_CONFIGS.get(role) or _CONFIGS[None])["decision_scope"]


def persona_prompt_fragment(role: Optional[str]) -> str:
    """The persona voice fragment appended to Sage's system prompt. Empty string
    when the role has none (default chain-wide analyst)."""
    return ((_CONFIGS.get(role) or _CONFIGS[None])["persona"].get("prompt_fragment") or "").strip()


def known_roles() -> List[str]:
    return [k for k in _CONFIGS if k is not None]
