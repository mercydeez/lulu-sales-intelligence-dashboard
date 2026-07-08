"""
Unit tests for the Role Experience Engine (blueprint Wave 1).

Pure — guards the config contract: wave-1 roles resolve to distinct experiences,
unknown roles degrade to the default (current behavior), KPI descriptors only
reference real sources/formats, nav entries only reference existing routes, the
persona fragment never claims authority over grounding, and the decision-scope
filter actually restricts what region/store roles see.
"""
from app.services.role_experience import (
    resolve_config, decision_scope_for, persona_prompt_fragment, known_roles,
    VALID_KPI_SOURCES, VALID_KPI_FORMATS, VALID_SCOPES,
    VALID_ASSISTANT_MODES, VALID_HOMEPAGE_LAYOUTS,
)
from app.services.decision_center import scope_decisions, triage_decisions, build_decision, build_reorder_decision
from app.services.ai_assistant import get_system_prompt

# Every href a nav manifest may reference must be a real frontend route.
EXISTING_ROUTES = {
    "/", "/today", "/briefing", "/decisions", "/insights", "/inventory",
    "/procurement", "/approvals", "/alerts", "/reports", "/value", "/analytics",
    "/uae-insights", "/action-drafts", "/imports", "/employees", "/promotions",
    "/forecast-lab", "/settings", "/copilot",
}


def test_wave1_roles_resolve_to_distinct_configs():
    store = resolve_config("store_manager")
    regional = resolve_config("regional_manager")
    assert store["key"] == "store_manager" and regional["key"] == "regional_manager"
    assert store["persona"]["title"] == "Store Coach"
    assert regional["persona"]["title"] == "Regional Coach"
    assert store["nav"] != regional["nav"]
    assert store["kpis"] != regional["kpis"]
    assert store["decision_scope"] == "store"
    assert regional["decision_scope"] == "region"


def test_procurement_buying_desk_config():
    proc = resolve_config("procurement_manager")
    assert proc["key"] == "procurement_manager"
    assert proc["persona"]["title"] == "Supply Chain Expert"
    assert proc["decision_scope"] == "chain"           # buys for the whole chain
    assert "SUPPLY CHAIN EXPERT" in persona_prompt_fragment("procurement_manager")
    # distinct from the other wave-1 roles
    assert proc["nav"] != resolve_config("store_manager")["nav"]
    assert proc["kpis"] != resolve_config("regional_manager")["kpis"]
    assert any(z["type"] == "approvals" for z in proc["zones"])   # the PO queue


def test_unknown_role_gets_default_and_current_behavior():
    # A role with no config (e.g. a future HR role) degrades to the default:
    # legacy dashboard home + full built-in sidebar + panel assistant.
    cfg = resolve_config("hr_manager")
    assert cfg["key"] == "_default"
    assert cfg["home"] == "/"          # existing dashboard stays home
    assert cfg["nav"] is None          # full built-in sidebar (unchanged)
    assert cfg["decision_scope"] == "chain"
    assert cfg["assistant_mode"] == "panel"   # legacy floating-panel Sage
    assert resolve_config(None)["key"] == "_default"


def test_super_admin_gets_executive_experience():
    """Wave 2: super_admin now resolves to the executive "Chief of Staff" copilot
    (config-only; no new RBAC role). Everything else stays reachable by URL/⌘K."""
    cfg = resolve_config("super_admin")
    assert cfg["key"] == "executive"
    assert cfg["home"] == "/today"
    assert cfg["assistant_mode"] == "copilot"
    assert cfg["decision_scope"] == "chain"           # sees the whole business
    assert cfg["persona"]["title"] == "Chief of Staff"
    # The curated six-item executive nav (labels driven by tKey on the client).
    hrefs = [n["href"] for n in cfg["nav"]]
    assert hrefs == ["/today", "/briefing", "/value", "/decisions", "/analytics", "/copilot"]
    assert cfg["capabilities"] == {"ai_chat": True, "voice": True}
    assert cfg["quick_actions"] and all(a["href"] in EXISTING_ROUTES for a in cfg["quick_actions"])
    # Phase 2b: the exec homepage names the Copilot feed widgets (which read one
    # shared fetch of /api/ai/copilot/feed on the client).
    zone_types = [z["type"] for z in cfg["zones"]]
    for feed_zone in ("business_health", "risks", "opportunities", "recommendations"):
        assert feed_zone in zone_types, feed_zone


def test_configs_are_copies_not_registry_references():
    a = resolve_config("store_manager")
    a["kpis"].append({"key": "hacked"})
    b = resolve_config("store_manager")
    assert all(k.get("key") != "hacked" for k in b["kpis"])


def test_kpi_descriptors_reference_valid_sources_and_formats():
    for role in known_roles() + [None, "super_admin"]:
        cfg = resolve_config(role if role else None)
        for kpi in cfg["kpis"]:
            assert kpi["source"] in VALID_KPI_SOURCES, kpi
            assert kpi["format"] in VALID_KPI_FORMATS, kpi
            assert kpi.get("label") and kpi.get("field") and kpi.get("key")


def test_nav_manifests_reference_existing_routes_only():
    for role in known_roles():
        nav = resolve_config(role)["nav"]
        if nav is None:
            continue
        for item in nav:
            assert item["href"] in EXISTING_ROUTES, item
            assert item.get("tKey") and item.get("icon") and item.get("label")


def test_decision_scopes_are_valid():
    for role in known_roles() + ["anything_else"]:
        assert decision_scope_for(role) in VALID_SCOPES


def test_persona_fragment_nonempty_for_configured_roles_default_empty():
    assert "STORE COACH" in persona_prompt_fragment("store_manager")
    assert "REGIONAL COACH" in persona_prompt_fragment("regional_manager")
    assert "CHIEF OF STAFF" in persona_prompt_fragment("super_admin")  # executive persona
    # A role with no config (→ _default) still has no persona fragment.
    assert persona_prompt_fragment("hr_manager") == ""


# --- Experience API v2 payload contract -------------------------------------

def test_v2_payload_shape_present_and_valid():
    for role in known_roles() + [None, "hr_manager"]:
        cfg = resolve_config(role)
        assert cfg["version"] == 2
        assert cfg["assistant_mode"] in VALID_ASSISTANT_MODES
        assert cfg["homepage"]["layout"] in VALID_HOMEPAGE_LAYOUTS
        # homepage envelope mirrors the (v1) top-level zone list.
        assert cfg["homepage"]["zones"] == cfg["zones"]
        assert set(cfg["capabilities"]) == {"ai_chat", "voice"}
        assert isinstance(cfg["quick_actions"], list)
        assert set(cfg["ai_context"]) >= {"focus", "scope"}
        # quick actions (when present) only point at real routes.
        for a in cfg["quick_actions"]:
            assert a["href"] in EXISTING_ROUTES, a
            assert a.get("key") and a.get("label")


# --- Phase 3: operational role configs carry the copilot contract -----------

def test_operational_roles_have_quick_actions_and_ai_context():
    """Phase 3 (SAGE_COPILOT_ARCHITECTURE §7): store/regional/procurement carry
    populated, role-distinct quick_actions and ai_context. ai_context is
    display/routing metadata only (never prompt text — that stays server-side);
    its first frontend consumer is the Phase 4 copilot surface header."""
    configs = {r: resolve_config(r)
               for r in ("store_manager", "regional_manager", "procurement_manager")}
    for role, cfg in configs.items():
        assert cfg["quick_actions"], role
        assert cfg["ai_context"]["focus"] and cfg["ai_context"]["scope"], role
    # Distinct per role — a store manager's one-taps are not a buyer's.
    keys = [tuple(a["key"] for a in c["quick_actions"]) for c in configs.values()]
    assert len(set(keys)) == 3
    scopes = [c["ai_context"]["scope"] for c in configs.values()]
    assert len(set(scopes)) == 3


def test_operational_roles_name_feed_zones_but_keep_panel_mode():
    """Feed zones arrive for operational roles (server-scoped feed), while the
    copilot shell stays executive-only: assistant_mode remains `panel`."""
    for role, feed_zone in (("store_manager", "recommendations"),
                            ("regional_manager", "risks"),
                            ("procurement_manager", "recommendations")):
        cfg = resolve_config(role)
        zone_types = [z["type"] for z in cfg["zones"]]
        assert feed_zone in zone_types, role
        assert "quick_actions" in zone_types, role
        assert cfg["assistant_mode"] == "panel", role


def test_prompt_fragment_never_in_delivered_config():
    """Security regression guard: the persona system-prompt fragment must never
    reach the client, even though it still exists server-side for the prompt."""
    for role in known_roles() + [None, "hr_manager"]:
        cfg = resolve_config(role)
        assert "prompt_fragment" not in cfg["persona"]
    # …but the server-side accessor still returns it (used by get_system_prompt).
    assert "CHIEF OF STAFF" in persona_prompt_fragment("super_admin")


def test_system_prompt_carries_persona_but_grounding_wins():
    p = get_system_prompt("store_manager")
    assert "PERSONA — STORE COACH" in p
    assert "GROUNDING & HONESTY" in p
    # explicit precedence statement, and grounding appears before the persona
    assert "take precedence" in p
    assert p.index("GROUNDING & HONESTY") < p.index("PERSONA — STORE COACH")
    # default prompt unchanged (no persona block)
    assert "PERSONA —" not in get_system_prompt(None)


# --- scope filtering (the decision permissions part of the config) ----------

def _store_decision(store_id, fid=1):
    return build_decision({
        "id": fid, "rule": "revenue_drop", "category": "sales", "severity": "high",
        "title": f"Revenue down at store {store_id}", "detail": "d", "entity_type": "store",
        "entity_id": str(store_id), "entity_name": f"Store {store_id}", "metric_value": -0.3,
        "evidence": {"rev_recent": 700.0, "rev_prior": 1000.0, "change": -0.3},
        "recommended_action": "Check store", "action_type": "promote",
        "action_accepted_at": None, "detected_at": "2026-07-05",
    })


def _category_decision(fid=9):
    return build_decision({
        "id": fid, "rule": "category_slump", "category": "sales", "severity": "critical",
        "title": "Seafood down", "detail": "d", "entity_type": "category",
        "entity_id": "Seafood", "entity_name": "Seafood", "metric_value": -0.5,
        "evidence": {"rev_recent": 5000.0, "rev_prior": 10000.0, "change": -0.5},
        "recommended_action": "Review pricing", "action_type": "review_pricing",
        "action_accepted_at": None, "detected_at": "2026-07-05",
    })


def _reorder(store_id):
    return build_reorder_decision({
        "item_name": "Dates", "store_name": f"Store {store_id}", "store_id": store_id,
        "days_of_cover": 2.0, "recommended_order_qty": 300, "urgency": "critical",
        "on_hand": 10, "forecast_daily_demand": 8.0, "forecast_demand_lead_time": 90,
        "lead_time_days": 7,
    })


def test_scope_chain_sees_everything():
    deck = [_store_decision(1), _store_decision(7), _category_decision(), _reorder(1)]
    assert len(scope_decisions(deck, "chain", [1])) == 4


def test_scope_store_sees_only_own_store_and_no_chainwide():
    deck = [_store_decision(1, 1), _store_decision(7, 2), _category_decision(), _reorder(1), _reorder(7)]
    mine = scope_decisions(deck, "store", [1])
    assert len(mine) == 2
    assert all(str(d.get("entity_id")) == "1" for d in mine)
    assert all(d.get("entity_type") == "store" for d in mine)


def test_scope_region_sees_all_region_stores():
    deck = [_store_decision(1, 1), _store_decision(2, 2), _store_decision(7, 3), _category_decision()]
    region = scope_decisions(deck, "region", [1, 2, 3])
    assert {d["id"] for d in region} == {1, 2}


def test_store_scope_triage_has_no_regional_lane():
    # 5 store decisions for store 1: top 3 go exec, the rest must land in the
    # STORE lane (a store manager has no regional lane below them).
    deck = [_store_decision(1, i) for i in range(1, 6)]
    t = triage_decisions(deck, {}, scope="store")
    lanes = {ln["key"] for ln in t["lanes"]}
    assert "regional" not in lanes
    assert "store" in lanes
