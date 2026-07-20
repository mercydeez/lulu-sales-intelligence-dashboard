"""
Role Experience Engine (ROLE_EXPERIENCE_BLUEPRINT.md, Wave 1).

One engine, many experiences: each role gets a CONFIG — persona pack, homepage
zone list, KPI descriptors, navigation manifest, decision scope, notification
defaults — and generic surfaces render from it. Adding a role = adding a config
here, not building screens.

Wave 1 covers the operational roles that exist in RBAC today (`store_manager`,
`regional_manager`); Wave 2 (Sage Copilot) adds the executive experience mapped
to `super_admin` (the "Chief of Staff" copilot). A `_default` preserves current
behavior for every other role. Roles that need data we don't have (HR attendance,
Loss Prevention POS grain) are intentionally absent.

The delivered payload is Experience API v2 — see `resolve_config` for the shape
(version, assistant_mode, homepage envelope, quick_actions, ai_context,
capabilities) and the security note on why persona prompt fragments never ship.

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

# ── Experience API v2 (Sage Copilot) ────────────────────────────────────────
# The config now fully describes the frontend experience: which assistant shell
# to render, the role's one-tap actions, the homepage layout, and lightweight AI
# display context. These are DATA (config-as-data), never code paths.
#   assistant_mode : which Sage shell the frontend renders
#   capabilities   : rendering hints only — the server still authorizes every AI
#                    call (routes/ai.py require_ai_chat); a client can never widen
#                    its own access by asserting a capability here.
#   ai_context     : DISPLAY/routing metadata (focus areas, scope label) — never
#                    prompt text. Prompt fragments stay server-side (see below).
VALID_ASSISTANT_MODES = {"panel", "copilot", "hidden"}
VALID_HOMEPAGE_LAYOUTS = {"focus", "grid"}

# Any v2 field a role record omits falls back here at resolve time, so older or
# partial configs stay valid and the payload shape is always complete.
_V2_DEFAULTS: Dict = {
    "assistant_mode": "panel",                     # panel | copilot | hidden
    "quick_actions": [],                           # [{key,label,href,icon}]
    "ai_context": {"focus": [], "scope": ""},      # display/routing metadata only
    "capabilities": {"ai_chat": True, "voice": True},  # hints; server authorizes
    "layout": "focus",                             # homepage layout (→ homepage.layout)
}

_CONFIGS: Dict[Optional[str], Dict] = {
    # ── Executive (super_admin) — "Chief of Staff" (AI-first copilot) ────────
    # Wave 2: the CEO / executive experience is pure configuration over engines
    # that already exist (briefing, decisions/triage, ROI/value, analytics). It
    # is mapped to `super_admin` so NO new RBAC role is required; a dedicated
    # `ceo` role can adopt this same record later (interface request to Krishna).
    # The six-item nav is the executive's *curated* surface — every other page
    # stays reachable by URL and the ⌘K command palette; nothing is deleted.
    "super_admin": {
        "key": "executive",
        "home": "/today",
        "decision_scope": "chain",
        "assistant_mode": "copilot",
        "capabilities": {"ai_chat": True, "voice": True},
        "ai_context": {"focus": ["revenue", "profit", "risks", "growth"], "scope": "All stores"},
        "persona": {
            "name": None,  # filled with settings.chatbot_name at resolve time
            "title": "Chief of Staff",
            "tagline": "The whole business, one screen",
            "greeting": "Here's where the business stands — and the calls that need you.",
            "voice": ["strategic", "money-first", "concise", "decisive"],
            "prompt_fragment": (
                "PERSONA — CHIEF OF STAFF: You are briefing a CEO / senior executive who owns "
                "the whole chain. Be their chief of staff: strategic, concise, money-first. Lead "
                "with the single number that matters and the one decision that moves it, then stop "
                "— delegate the detail. Prefer AED for value and units for volume, never mixed. "
                "Surface risks and growth openings before they ask. Respect their time."
            ),
        },
        # Five-Questions homepage: verdict (what matters) · business health ·
        # KPIs · decisions (what to do first) · risks · growth openings ·
        # recommendations · quick actions (what Sage can do). The feed widgets
        # (business_health/risks/opportunities/recommendations) read ONE shared
        # fetch of /api/ai/copilot/feed; older frontends without those widgets
        # degrade gracefully (unknown zone types are skipped).
        "zones": [
            {"type": "verdict"},
            {"type": "business_health", "props": {"title": "Business health"}},
            {"type": "kpis"},
            {"type": "decisions", "props": {"limit": 3, "title": "Decisions that need you"}},
            {"type": "risks", "props": {"title": "Risks Sage is watching"}},
            {"type": "opportunities", "props": {"title": "Growth openings"}},
            {"type": "recommendations", "props": {"title": "Sage recommends"}},
            {"type": "quick_actions", "props": {"title": "What Sage can do for you"}},
        ],
        "kpis": [
            {"key": "week_revenue", "label": "Revenue (7d)", "source": "kpis",
             "field": "total_revenue_week", "format": "aed"},
            {"key": "revenue_trend", "label": "Trend", "source": "kpis",
             "field": "revenue_trend", "format": "trend"},
            {"key": "week_units", "label": "Volume (7d)", "source": "kpis",
             "field": "total_sales_week", "format": "units"},
            {"key": "decisions_pending", "label": "Decisions waiting", "source": "decisions",
             "field": "pending", "format": "int"},
            {"key": "at_stake", "label": "At stake /wk", "source": "decisions",
             "field": "at_stake_aed_per_week", "format": "aed"},
        ],
        "nav": [
            {"key": "overview", "tKey": "nav.overview", "label": "Overview", "href": "/today", "icon": "LayoutDashboard"},
            {"key": "briefing", "tKey": "nav.execBriefing", "label": "Executive Briefing", "href": "/briefing", "icon": "Sunrise"},
            {"key": "role_workbench", "tKey": "nav.roleWorkbench", "label": "Role Workbench", "href": "/role-workbench", "icon": "ClipboardCheck"},
            {"key": "health", "tKey": "nav.businessHealth", "label": "Business Health", "href": "/value", "icon": "TrendingUp"},
            {"key": "decisions", "tKey": "nav.decisions", "label": "Decisions", "href": "/decisions", "icon": "Scale"},
            {"key": "growth", "tKey": "nav.growth", "label": "Growth", "href": "/analytics", "icon": "BarChart3"},
            {"key": "flywheel", "tKey": "nav.flywheel", "label": "Flywheel", "href": "/flywheel", "icon": "Repeat"},
            # Horizon 1: ONLY the proof surface belongs in an executive manifest.
            # Holdout, Contact Governance and Shadow Mode are operator tools —
            # they are registered in the main sidebar (config/nav.tsx) and reached
            # from there. An executive nav that lists every sub-page stops being a
            # curated view and becomes a second, worse sitemap.
            {"key": "incrementality", "tKey": "nav.incrementality", "label": "Incrementality", "href": "/flywheel/incrementality", "icon": "TrendingUp"},
            {"key": "sage", "tKey": "nav.sageCopilot", "label": "Sage Copilot", "href": "/copilot", "icon": "Lightbulb"},
        ],
        "quick_actions": [
            {"key": "ask", "label": "Ask Sage anything", "href": "/copilot", "icon": "Lightbulb"},
            {"key": "briefing", "label": "Read today's executive briefing", "href": "/briefing", "icon": "Sunrise"},
            {"key": "role_workbench", "label": "Audit role workflows", "href": "/role-workbench", "icon": "ClipboardCheck"},
            {"key": "decisions", "label": "Review the decisions that need me", "href": "/decisions", "icon": "Scale"},
            {"key": "health", "label": "Open business health", "href": "/value", "icon": "TrendingUp"},
        ],
        "notifications": {"brief_hour_gst": 7, "quiet_hours": [22, 6], "tiers": ["T1 exec brief 07:00", "T0 chain-critical only"]},
    },

    # ── Store Manager — "Store Coach" (phone-first; today only) ─────────────
    "store_manager": {
        "key": "store_manager",
        "home": "/today",
        "decision_scope": "store",
        # Display/routing metadata only — prompt text stays server-side (§3.6).
        # First rendered by the copilot surface header (Phase 4).
        "ai_context": {"focus": ["stockouts", "today_sales", "reorders"], "scope": "Your store"},
        "quick_actions": [
            {"key": "reorder", "label": "Reorder what's running low", "href": "/procurement", "icon": "Truck"},
            {"key": "alerts", "label": "Check today's alerts", "href": "/alerts", "icon": "Bell"},
            {"key": "briefing", "label": "Read today's briefing", "href": "/briefing", "icon": "Sunrise"},
            {"key": "role_workbench", "label": "Open role workbench", "href": "/role-workbench", "icon": "ClipboardCheck"},
        ],
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
            {"type": "recommendations", "props": {"title": "Do these next"}},
            {"type": "quick_actions"},
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
            {"key": "role_workbench", "tKey": "nav.roleWorkbench", "label": "Role Workbench", "href": "/role-workbench", "icon": "ClipboardCheck"},
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
        "ai_context": {"focus": ["store_comparison", "approvals", "wow_movement"], "scope": "Your region"},
        "quick_actions": [
            {"key": "approvals", "label": "Review pending approvals", "href": "/approvals", "icon": "Inbox"},
            {"key": "compare", "label": "Compare my stores", "href": "/analytics", "icon": "BarChart3"},
            {"key": "briefing", "label": "Read today's briefing", "href": "/briefing", "icon": "Sunrise"},
        ],
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
            {"type": "risks", "props": {"title": "Stores at risk"}},
            {"type": "quick_actions"},
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
        # Demo (2026-07-08): regional manager gets the FULL built-in sidebar
        # (nav=None) so they see every operational + admin tab, not just the
        # curated 5. Backend RBAC for the admin-gated pages is opened to
        # regional_manager alongside super_admin (see admin/security/data_sources
        # routes). To restore the curated "Regional Coach" nav, put the 5-item
        # manifest back here. (Role Workbench remains reachable via the full
        # sidebar, so no curated entry is needed here.)
        "nav": None,
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
        "ai_context": {"focus": ["po_queue", "stock_pressure", "overstock"], "scope": "All stores (buying desk)"},
        "quick_actions": [
            {"key": "po_queue", "label": "Open the PO queue", "href": "/approvals", "icon": "Inbox"},
            {"key": "generate_pos", "label": "Generate POs from forecast", "href": "/procurement", "icon": "Truck"},
            {"key": "stock", "label": "Check stock pressure", "href": "/inventory", "icon": "Package"},
        ],
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
            {"type": "recommendations", "props": {"title": "Buying recommendations"}},
            {"type": "quick_actions"},
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
            {"key": "role_workbench", "tKey": "nav.roleWorkbench", "label": "Role Workbench", "href": "/role-workbench", "icon": "ClipboardCheck"},
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
    """The role's experience config as delivered to the client (Experience API
    v2). A deep copy — callers may not mutate the registry. Unknown roles get the
    default, so new roles degrade gracefully.

    Guarantees on the returned payload:
    - `version == 2`, and every v2 field is present (defaults fill omissions).
    - `homepage = {layout, zones}` wraps the zone list; top-level `zones` is kept
      for backward compatibility with v1 consumers.
    - the persona `prompt_fragment` is REMOVED — it is a server-only system-prompt
      fragment (see `persona_prompt_fragment`); shipping it would disclose the
      prompt and widen the injection surface. Sage's prompt is assembled
      server-side in `ai_assistant.get_system_prompt`.
    """
    cfg = copy.deepcopy(_CONFIGS.get(role) or _CONFIGS[None])
    # Persona name follows the configured chatbot name (single source of truth).
    try:
        from app.config import get_settings
        cfg["persona"]["name"] = get_settings().chatbot_name
    except Exception:
        cfg["persona"]["name"] = cfg["persona"]["name"] or "Sage"
    # SECURITY: never send the persona's system-prompt fragment to the client.
    cfg["persona"].pop("prompt_fragment", None)
    # Fill any v2 field the record omitted, then wrap the homepage envelope.
    for key, default in _V2_DEFAULTS.items():
        cfg.setdefault(key, copy.deepcopy(default))
    layout = cfg.pop("layout", "focus")
    cfg["homepage"] = {"layout": layout, "zones": cfg["zones"]}
    cfg["version"] = 2
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
