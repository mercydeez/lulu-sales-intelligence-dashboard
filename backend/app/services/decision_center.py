"""
AI Decision Center (blueprint E3-2) — the decisions inbox.

Composes the diagnostics loop's findings (+ forecast reorder risks) into DECISION
objects an executive can act on. Every decision carries: the problem, business
impact (AED), evidence, confidence, the recommended action, and the expected
outcome. All of it is DERIVED from the finding's own evidence numbers — impact
and confidence are never fabricated; where a value isn't derivable (returns carry
no sale price; the laggard rule stores only growth rates) the field is null and
`basis` says why. Sacred rule: VOLUME in units, VALUE in AED, never mixed.

Pure builders (unit-tested without a DB) + an async composer, mirroring
services/briefing.py and roi.py. Approve/dismiss REUSE the existing findings
endpoints (accept-action / resolve), so the measure loop keeps proving outcomes —
the "Decided" view shows whether each approved decision actually worked.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# The worker's own alert thresholds (worker/src/rules.js) — used to express how
# far past the threshold a finding is (a confidence factor, not a new metric).
RULE_THRESHOLDS = {
    "revenue_drop": 0.15,
    "category_slump": 0.20,
    "return_spike": 0.40,
    "laggard_store": 0.05,   # gap in percentage points vs the chain
    # high_return_rate's threshold is dynamic: max(1.5 × chain mean, 0.05)
}

# Floors below which a comparison is likely noise (confidence factor).
REVENUE_SCALE_FLOOR_AED = 1_000
RETURNS_SCALE_FLOOR_UNITS = 200


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _evidence_dict(finding: Dict) -> Dict:
    ev = finding.get("evidence")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (ValueError, TypeError):
            ev = {}
    return ev if isinstance(ev, dict) else {}


# ---------------------------------------------------------------------------
# Business impact — derived strictly from the finding's evidence. Pure.
# ---------------------------------------------------------------------------
def estimate_impact(finding: Dict) -> Dict:
    """Return {'aed', 'units', 'per', 'basis'}; aed/units are None when not
    honestly derivable from the evidence, and `basis` always says how/why."""
    rule = finding.get("rule")
    ev = _evidence_dict(finding)

    if rule in ("revenue_drop", "category_slump"):
        gap = max(0.0, _f(ev.get("rev_prior")) - _f(ev.get("rev_recent")))
        return {
            "aed": round(gap, 2) if gap > 0 else None,
            "units": None,
            "per": "week",
            "basis": "prior-week revenue minus this week — the weekly AED gap to recover",
        }
    if rule == "return_spike":
        delta = max(0.0, _f(ev.get("returns_recent_units")) - _f(ev.get("returns_prior_units")))
        return {
            "aed": None,
            "units": int(round(delta)) if delta > 0 else None,
            "per": "week",
            "basis": "extra returned units vs the prior week; returns carry no sale price in this data, so impact is in units",
        }
    if rule == "high_return_rate":
        excess = (_f(ev.get("return_rate")) - _f(ev.get("mean_rate"))) * _f(ev.get("gross_units"))
        return {
            "aed": None,
            "units": int(round(excess)) if excess > 0 else None,
            "per": "30d",
            "basis": "returned units above the chain-average rate over 30 days; no sale price on returns, so impact is in units",
        }
    if rule == "laggard_store":
        return {
            "aed": None,
            "units": None,
            "per": None,
            "basis": "growth-rate gap vs peers; the store's AED base isn't in this finding's evidence, so no AED figure is claimed",
        }
    return {"aed": None, "units": None, "per": None,
            "basis": "no derivable impact for this rule"}


# ---------------------------------------------------------------------------
# Confidence — deterministic, explainable factors. Pure. No ML, no vibes.
# ---------------------------------------------------------------------------
def confidence(finding: Dict) -> Dict:
    """Return {'score': 0..1, 'level': high|medium|low, 'factors': [str]}.
    Factors are the reasons a human can check; the score is just their sum."""
    rule = finding.get("rule")
    ev = _evidence_dict(finding)
    score = 0.5
    factors: List[str] = []

    # 1. Both comparison windows have real data (all rules require prior > 0).
    window_pairs = [("rev_recent", "rev_prior"), ("returns_recent_units", "returns_prior_units"),
                    ("return_units", "gross_units"), ("store_growth", "chain_growth")]
    if any(k1 in ev and k2 in ev for k1, k2 in window_pairs):
        score += 0.15
        factors.append("Full comparison windows on both sides")

    # 2. How far past the worker's own alert threshold the deviation is.
    threshold = RULE_THRESHOLDS.get(rule)
    magnitude = None
    if rule == "laggard_store":
        magnitude = abs(_f(ev.get("gap_pp")))
    elif rule == "high_return_rate":
        threshold = max(1.5 * _f(ev.get("mean_rate")), 0.05)
        magnitude = abs(_f(ev.get("return_rate")))
    else:
        magnitude = abs(_f(finding.get("metric_value")))
    if threshold and magnitude:
        ratio = magnitude / threshold
        if ratio >= 2:
            score += 0.2
            factors.append(f"Deviation is {ratio:.1f}× the alert threshold")
        elif ratio >= 1.5:
            score += 0.1
            factors.append(f"Deviation is {ratio:.1f}× the alert threshold")

    # 3. Scale floor — the numbers are big enough not to be noise.
    if _f(ev.get("rev_prior")) >= REVENUE_SCALE_FLOOR_AED:
        score += 0.1
        factors.append("Meaningful revenue base (not small-number noise)")
    elif (_f(ev.get("returns_prior_units")) >= RETURNS_SCALE_FLOOR_UNITS
          or _f(ev.get("gross_units")) >= RETURNS_SCALE_FLOOR_UNITS):
        score += 0.1
        factors.append("Meaningful unit volume (not small-number noise)")

    score = max(0.35, min(0.95, score))
    level = "high" if score >= 0.75 else "medium" if score >= 0.55 else "low"
    if not factors:
        factors.append("Rule fired with limited supporting evidence")
    return {"score": round(score, 2), "level": level, "factors": factors}


# ---------------------------------------------------------------------------
# Expected outcome — what happens if the action works. Pure, derived text.
# ---------------------------------------------------------------------------
def expected_outcome(finding: Dict, impact: Dict) -> str:
    rule = finding.get("rule")
    entity = finding.get("entity_name") or "the affected area"
    ev = _evidence_dict(finding)
    if rule in ("revenue_drop", "category_slump") and impact.get("aed"):
        return (f"Recovering {entity} to last week's level returns ~AED {impact['aed']:,.0f}/week. "
                "Sage re-measures after you act and reports whether it worked.")
    if rule == "return_spike" and impact.get("units"):
        return (f"Returning to last week's level avoids ~{impact['units']:,} returned units/week. "
                "Sage re-measures the return rate after you act.")
    if rule == "high_return_rate" and impact.get("units"):
        return (f"Bringing {entity} down to the chain-average rate avoids ~{impact['units']:,} "
                "returned units per 30 days.")
    if rule == "laggard_store":
        gap_pp = _f(ev.get("gap_pp"))
        return (f"Closing the {gap_pp * 100:.1f}pp growth gap brings {entity} back in line with its peers. "
                "Sage re-measures the gap after you act.")
    return "Sage re-measures the metric after you act and reports whether it recovered."


# ---------------------------------------------------------------------------
# Evidence — humanized facts a reader can verify. Pure.
# ---------------------------------------------------------------------------
def evidence_facts(finding: Dict) -> List[Dict]:
    ev = _evidence_dict(finding)
    aed = lambda v: f"AED {_f(v):,.0f}"                      # noqa: E731
    pct = lambda v: f"{_f(v) * 100:+.1f}%"                   # noqa: E731
    units = lambda v: f"{int(round(_f(v))):,} units"         # noqa: E731
    LABELS = [
        ("rev_recent", "This week", aed),
        ("rev_prior", "Prior week", aed),
        ("returns_recent_units", "Returns this week", units),
        ("returns_prior_units", "Returns prior week", units),
        ("return_units", "Returned (30d)", units),
        ("gross_units", "Gross sold (30d)", units),
        ("return_rate", "Return rate", lambda v: f"{_f(v) * 100:.1f}%"),
        ("mean_rate", "Chain average", lambda v: f"{_f(v) * 100:.1f}%"),
        ("store_growth", "Store growth", pct),
        ("chain_growth", "Chain growth", pct),
        ("gap_pp", "Gap vs chain", lambda v: f"{_f(v) * 100:.1f}pp"),
        ("change", "Change", pct),
    ]
    facts = [{"label": label, "value": fmt(ev[key])} for key, label, fmt in LABELS if key in ev]
    return facts


def enrich_finding(finding: Dict) -> Dict:
    """Attach the Decision Center's derived intelligence (impact, confidence,
    expected outcome, humanized evidence) to a raw finding dict, in place-ish
    (returns the same dict). Used by the findings API so Insights and the
    Decision Center speak from ONE derivation and can never disagree. Pure."""
    impact = estimate_impact(finding)
    finding["impact"] = impact
    finding["confidence"] = confidence(finding)
    finding["expected_outcome"] = expected_outcome(finding, impact)
    finding["evidence_facts"] = evidence_facts(finding)
    return finding


# ---------------------------------------------------------------------------
# Decision assembly. Pure.
# ---------------------------------------------------------------------------
def build_decision(finding: Dict) -> Dict:
    impact = estimate_impact(finding)
    conf = confidence(finding)
    decided = finding.get("action_accepted_at") is not None
    d = {
        "id": finding.get("id"),
        "kind": "finding",
        "rule": finding.get("rule"),
        "severity": finding.get("severity") or "medium",
        "state": "decided" if decided else "pending",
        "problem": finding.get("title"),
        "detail": finding.get("detail"),
        "entity_name": finding.get("entity_name"),
        "entity_type": finding.get("entity_type"),
        "entity_id": finding.get("entity_id"),
        "category": finding.get("category"),
        "impact": impact,
        "confidence": conf,
        "evidence": evidence_facts(finding),
        "recommended_action": finding.get("recommended_action"),
        "action_type": finding.get("action_type"),
        "expected_outcome": expected_outcome(finding, impact),
        "detected_at": finding.get("detected_at"),
        "href": "/insights",
    }
    if decided:
        d["decision"] = {
            "accepted_by": finding.get("action_accepted_by"),
            "accepted_at": finding.get("action_accepted_at"),
            "outcome_status": finding.get("outcome_status") or "pending",
            "metric_before": finding.get("metric_before"),
            "metric_after": finding.get("metric_after"),
            "measured_at": finding.get("measured_at"),
        }
    return d


def build_reorder_decision(s: Dict) -> Dict:
    """A forecast-driven stockout risk as a decision. No AED claimed (the
    suggestion carries no price) — impact in units, honestly labeled. Acting on
    it happens in Procurement, where the PO/approval system already lives."""
    qty = int(s.get("recommended_order_qty") or 0)
    demand = _f(s.get("forecast_demand_lead_time"))
    cover = _f(s.get("days_of_cover"))
    sev = "critical" if s.get("urgency") == "critical" else "high"
    return {
        "id": None,
        "kind": "reorder",
        "rule": "stockout_risk",
        "reorder_qty": qty,
        "severity": sev,
        "state": "pending",
        "problem": f"{s.get('item_name')} will run out at {s.get('store_name')}",
        "detail": (f"{cover:.1f} days of cover left at the forecast demand rate "
                   f"({_f(s.get('forecast_daily_demand')):.1f} units/day; lead time "
                   f"{int(s.get('lead_time_days') or 0)}d)."),
        "entity_name": s.get("store_name"),
        "entity_type": "store",
        "entity_id": str(s.get("store_id")) if s.get("store_id") is not None else None,
        "category": "inventory",
        "impact": {
            "aed": None,
            "units": int(round(demand)) if demand > 0 else None,
            "per": "lead time",
            "basis": "forecast demand over the supplier lead time; the suggestion carries no price, so impact is in units",
        },
        "confidence": {
            "score": 0.6, "level": "medium",
            "factors": ["Forecast-driven days-of-cover math", "Deterministic reorder quantity"],
        },
        "evidence": [
            {"label": "On hand", "value": f"{int(s.get('on_hand') or 0):,} units"},
            {"label": "Days of cover", "value": f"{cover:.1f} days"},
            {"label": "Forecast demand/day", "value": f"{_f(s.get('forecast_daily_demand')):.1f} units"},
        ],
        "recommended_action": f"Raise a PO for ~{qty:,} units of {s.get('item_name')} at {s.get('store_name')}.",
        "action_type": "reorder",
        "expected_outcome": (f"Ordering ~{qty:,} units protects ~{int(round(demand)):,} units of forecast "
                             f"demand and avoids a stockout in ~{cover:.0f} days."),
        "detected_at": None,
        "href": "/procurement",
    }


def scope_decisions(decisions: List[Dict], scope: str,
                    allowed: Optional[Sequence[int]]) -> List[Dict]:
    """Role-scope filter (blueprint decision ladder). `chain` sees everything.
    `region`/`store` see only decisions about THEIR stores — chain-wide
    category/global findings are executive concerns and are excluded. Pure."""
    if scope == "chain":
        return decisions
    allowed_ids = {str(a) for a in (allowed or [])}
    return [
        d for d in decisions
        if d.get("entity_type") == "store" and str(d.get("entity_id")) in allowed_ids
    ]


def sort_decisions(decisions: List[Dict]) -> List[Dict]:
    """Money first (AED impact desc, None last), then severity, then units."""
    def key(d):
        aed = d["impact"].get("aed")
        units = d["impact"].get("units")
        return (
            0 if aed is not None else 1,
            -(aed or 0),
            -_SEV_RANK.get(d.get("severity"), 1),
            -(units or 0),
        )
    return sorted(decisions, key=key)


def summarize(pending: List[Dict]) -> Dict:
    at_stake = round(sum(d["impact"]["aed"] or 0 for d in pending), 2)
    return {
        "pending": len(pending),
        "at_stake_aed_per_week": at_stake,
        "note": "AED at stake sums only decisions with a derivable weekly AED gap.",
    }


# ---------------------------------------------------------------------------
# Composer (I/O)
# ---------------------------------------------------------------------------
_FINDING_COLS = (
    "id, rule, category, severity, title, detail, evidence, entity_type, entity_id, "
    "entity_name, metric_value, status, recommended_action, action_type, "
    "action_accepted_at, action_accepted_by, outcome_status, metric_before, "
    "metric_after, measured_at, detected_at"
)


async def gather_scoped_pending(
    db: AsyncSession, tenant_id: int,
    allowed: Optional[Sequence[int]], scope: str,
) -> List[Dict]:
    """The scoped, pending decision pool (open findings + forecast reorder
    risks), money-ranked. Shared by `list_decisions`, `triage_view`, and the
    Sage Copilot feed so all three surfaces read from ONE composed list — never
    three independent derivations of "what's pending"."""
    return scope_decisions(await _gather_pending(db, tenant_id, allowed), scope, allowed)


async def list_decisions(
    db: AsyncSession,
    tenant_id: int,
    allowed: Optional[Sequence[int]] = None,
    state: str = "pending",
    scope: str = "chain",
) -> Dict:
    """The decision inbox. pending = open findings not yet decided (+ forecast
    reorder risks); decided = accepted decisions with their measured outcomes.
    `scope` (from the caller's role config) filters to the user's own stores."""
    if state == "decided":
        rows = (await db.execute(text(
            f"SELECT {_FINDING_COLS} FROM findings "
            "WHERE tenant_id = :tid AND action_accepted_at IS NOT NULL "
            "ORDER BY action_accepted_at DESC LIMIT 50"
        ), {"tid": tenant_id})).mappings().all()
        decisions = scope_decisions([build_decision(dict(r)) for r in rows], scope, allowed)
        return {"state": "decided", "decisions": decisions, "count": len(decisions)}

    decisions = await gather_scoped_pending(db, tenant_id, allowed, scope)
    return {
        "state": "pending",
        "decisions": decisions,
        "count": len(decisions),
        "summary": summarize(decisions),
    }


async def _gather_pending(db: AsyncSession, tenant_id: int,
                          allowed: Optional[Sequence[int]]) -> List[Dict]:
    """Open findings (+ forecast reorder risks) as money-ranked decisions."""
    rows = (await db.execute(text(
        f"SELECT {_FINDING_COLS} FROM findings "
        "WHERE tenant_id = :tid AND status IN ('open', 'acknowledged') "
        "AND action_accepted_at IS NULL "
        "ORDER BY detected_at DESC LIMIT 200"
    ), {"tid": tenant_id})).mappings().all()
    decisions = [build_decision(dict(r)) for r in rows]
    # Forecast-driven stockout risks (best-effort — must not 500 on a cold forecaster).
    # Each is linked to the exact draft PO that already carries the item, so acting
    # on "X will run out" lands on X's order — the item is never lost in the handoff.
    try:
        from app.services.forecast_service import reorder_suggestions
        reorder = (await reorder_suggestions(db, tenant_id, allowed, limit=10)).get("suggestions", [])
        po_for_item = await _open_po_for_items(db, tenant_id, [s.get("item_id") for s in reorder])
        for s in reorder:
            d = build_reorder_decision(s)
            po = po_for_item.get(s.get("item_id"))
            if po:
                item_q = quote(s.get("item_name") or "")
                d["po_id"] = po["po_id"]
                d["po_number"] = po["po_number"]
                d["href"] = f"/procurement/po/{po['po_id']}?item={item_q}"
            decisions.append(d)
    except Exception:
        pass
    return sort_decisions(decisions)


async def _open_po_for_items(db: AsyncSession, tenant_id: int, item_ids) -> Dict:
    """Map each item id → the most recent OPEN purchase order that already carries
    it {item_id: {po_id, po_number}}. Lets a reorder decision deep-link to the
    order for that exact item instead of a generic supplier list."""
    ids = [i for i in (item_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (l.item_id) l.item_id, l.po_id, po.po_number
        FROM purchase_order_lines l JOIN purchase_orders po ON po.id = l.po_id
        WHERE po.tenant_id = :t AND l.item_id = ANY(:items)
          AND po.status IN ('draft','pending_approval','approved','sent','partially_received')
        ORDER BY l.item_id, po.id DESC
    """), {"t": tenant_id, "items": ids})).mappings().all()
    return {r["item_id"]: {"po_id": r["po_id"], "po_number": r["po_number"]} for r in rows}


# ===========================================================================
# Triage & delegation (COO view) — reduce 55 decisions to the 3 that need you,
# and route the rest to the right owner. Deterministic + explainable. Pure.
# ===========================================================================
EXEC_SLOTS = 3
# Scope multiplier: a chain-wide problem outweighs one store of equal AED because
# only an executive can set chain policy. Used ONLY to rank for executive slots —
# never to change a displayed money figure.
SCOPE_WEIGHT = {"global": 1.5, "category": 1.4, "store": 1.0}
AUTO_PO_MAX_UNITS = 200   # reorders at/under this are auto-PO candidates for Sage

LANE_META = {
    "regional": {
        "label": "Regional managers",
        "reason": "Single-store performance — the regional owner investigates staffing, stock and local competition, and acts on the ground.",
    },
    "store": {
        "label": "Store managers",
        "reason": "Local replenishment a store manager should place and confirm at the shelf.",
    },
    "automate": {
        "label": "Sage can automate",
        "reason": "Repeatable, low-risk actions — small POs under your approval threshold and recurring supplier audits — Sage can handle end-to-end once you switch automation on.",
    },
}


def _base_impact(d: Dict) -> float:
    """A single comparable magnitude for ranking. AED where we have it; a units
    proxy otherwise; severity as a last resort. NOT shown as money anywhere."""
    imp = d.get("impact") or {}
    if imp.get("aed") is not None:
        return float(imp["aed"])
    if imp.get("units") is not None:
        return float(imp["units"]) * 5.0
    return _SEV_RANK.get(d.get("severity"), 1) * 1500.0


def strategic_score(d: Dict) -> float:
    if d.get("kind") == "reorder":
        weight = 0.6
    else:
        weight = SCOPE_WEIGHT.get(d.get("entity_type"), 0.8)
    return _base_impact(d) * weight


def route_owner(d: Dict) -> str:
    """Where a non-executive decision belongs: regional | store | automate | strategic."""
    if d.get("kind") == "reorder":
        return "automate" if int(d.get("reorder_qty") or 0) <= AUTO_PO_MAX_UNITS else "store"
    if d.get("rule") == "high_return_rate":
        return "automate"
    if d.get("entity_type") == "store":
        return "regional"
    return "strategic"   # chain-wide (category/global) that isn't a top-3 exec call


def _routing_reason(d: Dict, owner: str, region: Optional[str]) -> str:
    ent = d.get("entity_name") or "this area"
    if owner == "regional":
        return f"{region or 'Regional'} manager — single-store issue at {ent}."
    if owner == "store":
        return f"Store manager at {ent} — replenishment above the auto-approve size."
    if owner == "automate":
        if d.get("kind") == "reorder":
            return "Small PO under your approval threshold — a safe auto-place candidate."
        return "Recurring supplier-audit task Sage can open and track on its own."
    return "Chain-wide — a strategic call to review when you can."


def _sum_aed(decisions: List[Dict]) -> float:
    return round(sum((d["impact"].get("aed") or 0) for d in decisions), 2)


def triage_decisions(decisions: List[Dict], region_map: Optional[Dict] = None,
                     scope: str = "chain") -> Dict:
    """Split decisions into: the 3 for you, extra chain-wide to review, and the
    delegation lanes (regional / store / automate). Pure — region_map is optional
    context {store_id(str): region_name}. For a store-scoped user there is no
    regional lane below them — those decisions are theirs (store lane)."""
    region_map = region_map or {}
    ranked = sorted(decisions, key=strategic_score, reverse=True)
    exec_picks = ranked[:EXEC_SLOTS]
    exec_identity = {id(d) for d in exec_picks}

    buckets: Dict[str, List[Dict]] = {"regional": [], "store": [], "automate": [], "strategic": []}
    for d in decisions:
        if id(d) in exec_identity:
            continue
        owner = route_owner(d)
        if scope == "store" and owner == "regional":
            owner = "store"   # a store manager IS the on-the-ground owner
        region = region_map.get(str(d.get("entity_id"))) if owner == "regional" else None
        if region:
            d["region"] = region
        d["routing_reason"] = _routing_reason(d, owner, region)
        buckets[owner].append(d)

    # Regional decisions grouped by region (each region ≈ one manager).
    groups: Dict[str, Dict] = {}
    for d in buckets["regional"]:
        name = d.get("region") or "Unassigned"
        g = groups.setdefault(name, {"name": name, "count": 0, "aed": 0.0, "decisions": []})
        g["count"] += 1
        g["aed"] = round(g["aed"] + (d["impact"].get("aed") or 0), 2)
        g["decisions"].append(d)
    region_groups = sorted(groups.values(), key=lambda x: x["aed"], reverse=True)

    def lane(key: str) -> Dict:
        items = buckets[key]
        out = {
            "key": key,
            "label": LANE_META[key]["label"],
            "reason": LANE_META[key]["reason"],
            "count": len(items),
            "aed": _sum_aed(items),
            "decisions": items,
            "automate": key == "automate",
        }
        if key == "regional":
            out["groups"] = region_groups
        return out

    lanes = [lane("regional"), lane("store"), lane("automate")]

    return {
        "state": "pending",
        "total": len(decisions),
        "at_stake_aed_per_week": _sum_aed(decisions),
        "routed_count": len(decisions) - len(exec_picks),
        "executive": {
            "reason": "Chain-wide, high-impact calls only an executive can make. Ranked by AED weighted for scope.",
            "decisions": exec_picks,
            "more": {
                "count": len(buckets["strategic"]),
                "aed": _sum_aed(buckets["strategic"]),
                "decisions": buckets["strategic"],
            },
        },
        "lanes": [ln for ln in lanes if ln["count"] > 0],
    }


async def _region_map(db: AsyncSession, tenant_id: int) -> Dict[str, str]:
    rows = (await db.execute(text(
        "SELECT st.id AS id, COALESCE(r.name, 'Unassigned') AS region "
        "FROM stores st LEFT JOIN regions r ON r.id = st.region_id "
        "WHERE st.tenant_id = :t"
    ), {"t": tenant_id})).mappings().all()
    return {str(row["id"]): row["region"] for row in rows}


async def triage_view(db: AsyncSession, tenant_id: int,
                      allowed: Optional[Sequence[int]] = None,
                      scope: str = "chain") -> Dict:
    """The triage view: 3 decisions for you, the rest routed to owners —
    filtered to the caller's role scope (chain / region / store)."""
    decisions = await gather_scoped_pending(db, tenant_id, allowed, scope)
    region_map = await _region_map(db, tenant_id)
    return triage_decisions(decisions, region_map, scope=scope)
