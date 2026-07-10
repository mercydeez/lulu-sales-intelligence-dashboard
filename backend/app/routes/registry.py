"""Central router registry — the single, append-only place that lists every API
router with its mount prefix and OpenAPI tag.

WHY THIS FILE EXISTS (parallel-development / merge-conflict reduction):
Previously `app/main.py` had to be edited TWICE for every new endpoint — once to
import the route module and once to `include_router(...)`. With three developers
adding routes in parallel that made `main.py` the #1 merge-conflict hub. Now
`main.py` just iterates `ROUTERS`; adding an endpoint is a ONE-LINE append here.

HOW TO ADD A ROUTE:
  1. Import your route module below (in YOUR owner block).
  2. Append one `(module.router, "/api/<path>", ["Tag"])` tuple to `ROUTERS`
     (again, in YOUR owner block — never reorder another owner's lines).

OWNERSHIP: see TEAM_OWNERSHIP.md. Blocks are grouped by primary owner so two
people adding routes touch different regions of the list.
"""
from __future__ import annotations

from typing import List, Tuple

from fastapi import APIRouter

# --- Route module imports (grouped by owner) --------------------------------
# Krishna — Platform / Data / Services / Auth / Security / Integrations
from app.routes import sales, history, kpis, stream, analytics, auth
from app.routes import inventory, promotions, alerts, admin, reports, monitoring, employees
from app.routes import data_sources
from app.routes import tenants
from app.routes import billing as billing_routes
from app.routes import notifications as notifications_routes
from app.routes import imports as imports_routes
from app.routes import outcome_pricing as outcome_pricing_routes
from app.routes import team as team_routes
from app.routes import uae_intelligence as uae_intelligence_routes
from app.routes import public_api, api_keys, webhooks, procurement
from app.routes import security as security_routes
from app.routes import data_rights as data_rights_routes
from app.routes import provisioning as provisioning_routes
from app.routes import payments as payments_routes
from app.routes import pos as pos_routes
from app.routes import atelier_ai as atelier_routes
from app.routes import customizations as customizations_routes
from app.routes import platform_ops as platform_ops_routes
from app.routes import bespoke as bespoke_routes
from app.routes import sso as sso_routes
from app.routes import scim as scim_routes

# Yash — Frontend-platform support surfaces (CX loops)
from app.routes import feedback as feedback_routes
from app.routes import bulk_import as bulk_import_routes

# Atharva — AI / Sage / Decisions / Briefing / Role Experience / Diagnostics
from app.routes import ai as ai_routes
from app.routes import action_drafts as action_drafts_routes
from app.routes import roi as roi_routes
from app.routes import briefing as briefing_routes
from app.routes import decisions as decisions_routes
from app.routes import experience as experience_routes
from app.routes import findings as findings_routes
from app.routes import search as search_routes
from app.routes import copilot as copilot_routes


# A router, its mount prefix, and its OpenAPI tags.
RouterSpec = Tuple[APIRouter, str, List[str]]

# The order here is the order routers are mounted (and the order they appear in
# Swagger). Keep new entries inside your owner block.
ROUTERS: List[RouterSpec] = [
    # === Krishna — Platform / Data / Services / Auth / Security =============
    (sales.router, "/api/sales", ["Sales"]),
    (history.router, "/api/history", ["History"]),
    (kpis.router, "/api/kpis", ["KPIs"]),
    (stream.router, "/stream", ["Stream"]),
    (analytics.router, "/api/analytics", ["Analytics"]),
    (auth.router, "/api/auth", ["Authentication"]),
    (inventory.router, "/api/inventory", ["Inventory Management"]),
    (promotions.router, "/api/promotions", ["Promotions & Pricing"]),
    (alerts.router, "/api/alerts", ["Alerts & Notifications"]),
    (admin.router, "/api/admin", ["Admin"]),
    (reports.router, "/api/reports", ["Reports"]),
    (monitoring.router, "/api/monitoring", ["Monitoring"]),
    (employees.router, "/api/employees", ["Employees"]),
    (data_sources.router, "/api/data-sources", ["Data Sources"]),
    (tenants.router, "/api/tenants", ["Tenants"]),
    (billing_routes.router, "/api/billing", ["Billing"]),
    (notifications_routes.router, "/api/notifications", ["Notifications"]),
    (imports_routes.router, "/api/imports", ["Imports"]),
    (outcome_pricing_routes.router, "/api/outcome-pricing", ["Outcome Pricing"]),
    (team_routes.router, "/api/team", ["Team"]),
    (uae_intelligence_routes.router, "/api/uae-intelligence", ["UAE Intelligence"]),
    (api_keys.router, "/api/api-keys", ["API Keys"]),
    (webhooks.router, "/api/webhooks", ["Webhooks"]),
    (procurement.router, "/api/procurement", ["Procurement"]),
    (security_routes.router, "/api/security", ["Security"]),
    (public_api.router, "/api/public", ["Public API"]),
    (data_rights_routes.router, "/api/data-rights", ["Data Rights"]),
    (provisioning_routes.router, "/api/admin", ["Provisioning"]),
    (payments_routes.router, "/api/payments", ["Payments"]),
    (pos_routes.router, "/api/pos", ["POS Connectors"]),
    (atelier_routes.router, "/api/ai/atelier", ["Atelier"]),
    (customizations_routes.router, "/api/admin", ["Customizations"]),
    (platform_ops_routes.router, "/api/admin", ["Platform Ops"]),
    (bespoke_routes.router, "/api/admin", ["Bespoke"]),
    (sso_routes.router, "/api/sso", ["SSO"]),
    (scim_routes.router, "/api/scim", ["SCIM"]),

    # === Yash — Frontend-platform support surfaces (CX loops) ==============
    (feedback_routes.router, "/api/feedback", ["Feedback"]),
    # Bulk external-data ingestion (SCALE-2): /api/imports/bulk — shares the
    # /api/imports domain with the interactive importer, no path overlap.
    (bulk_import_routes.router, "/api/imports", ["Bulk Import"]),

    # === Atharva — AI / Sage / Decisions / Briefing / Experience ===========
    (ai_routes.router, "/api/ai", ["AI Assistant"]),
    (action_drafts_routes.router, "/api/action-drafts", ["Action Drafts"]),
    (roi_routes.router, "/api/roi", ["ROI"]),
    (briefing_routes.router, "/api/briefing", ["Briefing"]),
    (decisions_routes.router, "/api/decisions", ["Decisions"]),
    (experience_routes.router, "/api/experience", ["Experience"]),
    (findings_routes.router, "/api/findings", ["Diagnostics"]),
    (search_routes.router, "/api/search", ["Search"]),
    (copilot_routes.router, "/api/ai/copilot", ["Sage Copilot"]),
]
