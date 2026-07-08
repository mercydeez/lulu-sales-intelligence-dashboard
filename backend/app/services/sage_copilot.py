"""
Sage Copilot Feed — the proactive intelligence layer (Sage Copilot, Phase 2).

This is NOT a chatbot. It is a composition/orchestration layer: it aggregates
already-grounded output from the existing AI engines into one feed the frontend
renders on `/today` (and later, the dedicated copilot surface). It never
re-derives a business number and never calls an LLM — every figure here already
went through its own engine's math and its own tests:

    Sage Copilot Feed
      ├─ services/briefing.py         → the executive narrative (headline/why/decide/leak/watch/win)
      ├─ services/decision_center.py  → the scoped, ranked decision pool + triage
      ├─ services/roi.py              → honest AED (dead stock / stockout / GMROI)
      ├─ services/forecast_service.py → the revenue projection + narrative
      └─ (recommended_actions / risks / alerts are RESHAPINGS of the decision
         pool above — not a new derivation)

Design rules (mirrors briefing.py / roi.py / decision_center.py):
  - `build_feed(raw)` is PURE — it only reshapes already-computed dicts/lists
    from the engines above. It never touches the DB and unit-tests without one.
  - `generate_feed(...)` does the I/O: it calls each engine exactly once, then
    hands their outputs to `build_feed`.
  - LLM-free by construction: the proactive front door cannot hallucinate. Any
    future LLM narration is optional garnish inside chat, never on this path.
  - No hallucination policy: every list item carries `evidence` and a
    `confidence` score sourced from an existing engine (decision_center's
    deterministic scorer, or a fixed/documented confidence for forecast- or
    ROI-derived items — see `_GROUNDED_ESTIMATE_CONFIDENCE` /
    `_GROUNDED_MEASURED_CONFIDENCE` below, which mirror the exact fixed-
    confidence technique `decision_center.build_reorder_decision` already uses
    for forecast-driven items). Nothing here invents a new scoring formula for
    a finding — only reuses the one decision_center already computed.
  - Dict-shaped sections (briefing, business_health, forecast, roi) are ALWAYS
    present so the frontend has stable keys, but degrade honestly to a
    "not enough evidence" status rather than a fabricated figure. List-shaped
    sections (decisions, risks, opportunities, recommended_actions, alerts) are
    always present as a list — legitimately empty ("nothing needs attention")
    is an honest state, not a placeholder (the same convention `/today`,
    `/decisions` and `/insights` already use for their empty states).

Sacred rule inherited from every engine here: VOLUME in units, VALUE in AED,
never mixed on one axis.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.briefing import generate_briefing
from app.services.decision_center import (
    gather_scoped_pending, triage_decisions, summarize,
)
from app.services.roi import roi_summary
from app.services.forecast_service import revenue_projection, forecast_narrative
from app.services.cache import generate_cache_key, get_cached, set_cached

FEED_VERSION = 2
FEED_TTL_SECONDS = 300           # 5 minutes — compute-on-read cache freshness
_TIME_BUCKET_MINUTES = 15        # cache key changes every 15 minutes at most

MAX_RISKS = 5
MAX_OPPORTUNITIES = 3
MAX_RECOMMENDED_ACTIONS = 5
MAX_ALERTS = 5

# Deterministic, documented confidence for items that don't carry a native
# per-item score (mirrors decision_center.build_reorder_decision's own fixed
# {0.6, "medium"} pattern for forecast-driven items — NOT a new formula per
# finding, just the same "estimate vs measured" honesty already used for ROI's
# `is_estimate` flag).
_GROUNDED_MEASURED_CONFIDENCE = {"score": 0.85, "level": "high",
                                 "factors": ["Directly measured from live data — not a projection"]}
_GROUNDED_ESTIMATE_CONFIDENCE = {"score": 0.55, "level": "low",
                                 "factors": ["Projected estimate — see methodology"]}

# Severity → recommended-action priority. Deterministic mapping, not a fabricated rank.
_PRIORITY_BY_SEVERITY = {"critical": "urgent", "high": "high", "medium": "normal", "low": "low"}


# ---------------------------------------------------------------------------
# Business Health — an AGGREGATION of existing signals into one label.
# No new business calculation: every field below is copied from an upstream
# engine; `overall` is a deterministic classification of those copied numbers
# (same "factors explain the score" transparency as decision_center.confidence).
# ---------------------------------------------------------------------------
def compose_business_health(raw: Dict) -> Dict:
    """raw keys: revenue_trend, revenue_change_pct, decisions_pending,
    at_stake_aed_per_week, critical_risk_count, dead_stock_aed,
    below_reorder_count, total_skus, forecast_status. Pure."""
    trend = raw.get("revenue_trend") or "flat"
    pct = raw.get("revenue_change_pct")
    critical = int(raw.get("critical_risk_count") or 0)
    at_stake = float(raw.get("at_stake_aed_per_week") or 0)
    forecast_status = raw.get("forecast_status") or "insufficient_history"
    below_reorder = int(raw.get("below_reorder_count") or 0)
    total_skus = int(raw.get("total_skus") or 0)

    factors: List[str] = []
    score = 0.6  # neutral baseline; nudged by real, already-computed signals

    if trend == "up":
        score += 0.15
        factors.append(f"Revenue trending up{f' ({pct:+.1f}% WoW)' if pct is not None else ''}")
    elif trend == "down":
        score -= 0.2
        factors.append(f"Revenue trending down{f' ({pct:+.1f}% WoW)' if pct is not None else ''}")

    if critical:
        score -= min(0.25, 0.06 * critical)
        factors.append(f"{critical} critical/high-severity risk{'s' if critical != 1 else ''} open")
    else:
        factors.append("No critical or high-severity risks open")

    if total_skus > 0 and below_reorder / total_skus > 0.15:
        score -= 0.1
        factors.append(f"{below_reorder} of {total_skus} SKUs at or below reorder point")

    if forecast_status != "ready":
        factors.append("Forecast confidence: not enough sales history yet")
    else:
        factors.append("Forecast confidence: model has sufficient history")

    score = max(0.0, min(1.0, round(score, 2)))
    overall = ("strong" if score >= 0.75 else
               "steady" if score >= 0.55 else
               "attention" if score >= 0.35 else
               "critical")

    return {
        "overall": overall,
        "score": score,
        "factors": factors,
        "components": {
            "revenue_trend": trend,
            "revenue_change_pct": pct,
            "open_actions": int(raw.get("decisions_pending") or 0),
            "at_stake_aed_per_week": round(at_stake, 2),
            "critical_risks": critical,
            "inventory_pressure": {"below_reorder_count": below_reorder, "total_skus": total_skus},
            "forecast_status": forecast_status,
        },
    }


# ---------------------------------------------------------------------------
# Recommended actions — a RESHAPING of decision_center's own decision objects
# into {title, reason, evidence, priority, confidence, deep_link}. No new
# analysis: every field is copied from the finding/decision that decision_center
# already scored.
# ---------------------------------------------------------------------------
def _to_recommended_action(d: Dict) -> Optional[Dict]:
    action = d.get("recommended_action")
    if not action:
        return None
    severity = d.get("severity") or "medium"
    return {
        "title": action,
        "reason": d.get("problem") or "Flagged by the diagnostics engine.",
        "evidence": d.get("evidence") or [],
        "priority": _PRIORITY_BY_SEVERITY.get(severity, "normal"),
        "confidence": (d.get("confidence") or {}).get("score"),
        "deep_link": d.get("href") or "/decisions",
    }


def _dedupe_by_id(items: Sequence[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for d in items:
        key = d.get("id") if d.get("id") is not None else id(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Opportunities — ONLY grounded, positive signals already computed elsewhere:
# a measure-loop recovery or WoW growth (from briefing's own `win`), and ROI's
# own dead-stock/stockout figures. Never fabricated; each carries the honest
# measured-vs-estimated confidence distinction ROI already flags.
# ---------------------------------------------------------------------------
def _opportunities_from_win(win: Optional[Dict]) -> List[Dict]:
    if not win:
        return []
    if win.get("kind") == "recovered":
        return [{
            "title": win["title"],
            "reason": win["detail"],
            "evidence": [{"label": "Outcome", "value": "Measured recovery (measure loop)"}],
            "confidence": _GROUNDED_MEASURED_CONFIDENCE["score"],
            "deep_link": "/insights",
        }]
    if win.get("kind") == "growth":
        return [{
            "title": win["title"],
            "reason": win["detail"],
            "evidence": [{"label": "Signal", "value": "Week-over-week revenue growth"}],
            "confidence": _GROUNDED_MEASURED_CONFIDENCE["score"],
            "deep_link": "/analytics",
        }]
    return []


def _opportunities_from_roi(roi: Dict) -> List[Dict]:
    out: List[Dict] = []
    dead = (roi.get("metrics") or {}).get("dead_stock") or {}
    if (dead.get("aed") or 0) > 0:
        out.append({
            "title": f"Recover AED {dead['aed']:,.0f} tied up in dead stock",
            "reason": f"{dead.get('count', 0)} SKUs have had no sale in 60 days.",
            "evidence": [{"label": "Dead stock (AED)", "value": f"AED {dead['aed']:,.0f}"},
                         {"label": "SKUs affected", "value": str(dead.get("count", 0))}],
            "confidence": _GROUNDED_MEASURED_CONFIDENCE["score"],  # live inventory fact, not a projection
            "deep_link": "/value",
        })
    stockout = (roi.get("metrics") or {}).get("stockout_loss_estimate") or {}
    if (stockout.get("aed") or 0) > 0:
        out.append({
            "title": f"Prevent an estimated AED {stockout['aed']:,.0f} in stockout losses",
            "reason": f"Projected over {stockout.get('projection_days', 30)} days at current out-of-stock velocity.",
            "evidence": [{"label": "Projected loss (AED)", "value": f"AED {stockout['aed']:,.0f}"}],
            "confidence": _GROUNDED_ESTIMATE_CONFIDENCE["score"],  # roi.py flags this is_estimate
            "deep_link": "/value",
        })
    return out


# ---------------------------------------------------------------------------
# The pure composer
# ---------------------------------------------------------------------------
def build_feed(raw: Dict) -> Dict:
    """Assemble the copilot feed from already-computed engine outputs. Pure —
    no I/O, no LLM, and no re-derivation: `briefing` must be the dict already
    assembled by `briefing.build_briefing`/`generate_briefing` — this function
    never calls that builder itself, so the feed's briefing section is always
    IDENTICAL to what `/api/briefing` shows (one source of truth, never a
    second derivation of the same WoW math). `raw` keys:
      now (datetime), briefing (dict, from briefing.generate_briefing),
      pending_decisions (list[dict], from decision_center.gather_scoped_pending),
      region_map (dict), scope (str), roi (dict, from roi_summary),
      forecast (dict, from revenue_projection), forecast_text (str,
      from forecast_narrative).
    """
    now: datetime = raw.get("now") or datetime.now(timezone.utc)
    pending = raw.get("pending_decisions") or []
    scope = raw.get("scope") or "chain"
    briefing = raw["briefing"]

    triage = triage_decisions(pending, raw.get("region_map") or {}, scope=scope)
    top_decisions = triage["executive"]["decisions"]
    top_ids = {d.get("id") if d.get("id") is not None else id(d) for d in top_decisions}

    # Risks: finding-derived, critical/high severity, not already a top decision.
    risk_pool = [
        d for d in pending
        if d.get("kind") == "finding" and (d.get("severity") in ("critical", "high"))
        and (d.get("id") if d.get("id") is not None else id(d)) not in top_ids
    ]
    risks = risk_pool[:MAX_RISKS]

    # Operational alerts: imminent stockouts (reorder-kind, critical severity) —
    # distinct from strategic risk, these are "act today at the shelf" items.
    alerts = [d for d in pending if d.get("kind") == "reorder" and d.get("severity") == "critical"][:MAX_ALERTS]

    # Recommended actions: the executive's top decisions + top risks, deduped,
    # reshaped into the {title,reason,evidence,priority,confidence,deep_link}
    # contract. No new derivation — every field already exists on the decision.
    action_pool = _dedupe_by_id(list(top_decisions) + list(risks))
    recommended_actions = [
        a for a in (_to_recommended_action(d) for d in action_pool[:MAX_RECOMMENDED_ACTIONS]) if a
    ]

    opportunities = (_opportunities_from_win(briefing.get("win"))
                     + _opportunities_from_roi(raw.get("roi") or {}))[:MAX_OPPORTUNITIES]

    roi = raw.get("roi") or {}
    fc = raw.get("forecast") or {}
    forecast_block = {
        "status": fc.get("status", "insufficient_history"),
        "horizon_days": fc.get("horizon_days"),
        "projected_units": fc.get("projected_units"),
        "projected_revenue_aed": fc.get("projected_revenue"),
        "avg_daily_revenue_aed": fc.get("avg_daily_revenue"),
        "model_version": fc.get("model_version"),
        "narrative": raw.get("forecast_text") or "Not enough evidence to project a forecast yet.",
    }

    decisions_summary = summarize(pending)
    business_health = compose_business_health({
        "revenue_trend": briefing["headline"]["trend"],
        "revenue_change_pct": briefing["headline"]["revenue_change_pct"],
        "decisions_pending": decisions_summary["pending"],
        "at_stake_aed_per_week": decisions_summary["at_stake_aed_per_week"],
        "critical_risk_count": sum(1 for d in pending if d.get("severity") in ("critical", "high")),
        "dead_stock_aed": (roi.get("metrics") or {}).get("dead_stock", {}).get("aed"),
        "below_reorder_count": (roi.get("context") or {}).get("below_reorder_count"),
        "total_skus": (roi.get("context") or {}).get("total_skus"),
        "forecast_status": forecast_block["status"],
    })

    # metadata.confidence: the mean of the confidence scores actually PRESENT in
    # this feed (a real aggregate of real numbers — never an invented figure).
    scores = [d.get("confidence", {}).get("score") for d in (top_decisions + risks) if d.get("confidence")]
    scores += [a["confidence"] for a in recommended_actions if a.get("confidence") is not None]
    mean_confidence = round(sum(scores) / len(scores), 2) if scores else None

    generated_at = now.astimezone(timezone.utc).isoformat()
    fresh_until = (now + timedelta(seconds=FEED_TTL_SECONDS)).astimezone(timezone.utc).isoformat()

    sections_included = [k for k, v in {
        "briefing": briefing, "business_health": business_health,
        "decisions": top_decisions, "risks": risks, "opportunities": opportunities,
        "forecast": forecast_block, "roi": roi if roi else None,
        "recommended_actions": recommended_actions, "alerts": alerts,
    }.items() if v]

    return {
        "version": FEED_VERSION,
        "generated_at": generated_at,
        "fresh_until": fresh_until,
        "briefing": briefing,
        "business_health": business_health,
        "decisions": top_decisions,
        "risks": risks,
        "opportunities": opportunities,
        "forecast": forecast_block,
        "roi": roi,
        "recommended_actions": recommended_actions,
        "alerts": alerts,
        "metadata": {
            "confidence": mean_confidence,
            "sections_included": sections_included,
            "more_strategic_count": triage["executive"]["more"]["count"],
        },
    }


# ---------------------------------------------------------------------------
# Composer (I/O) — calls each engine exactly once, then hands off to build_feed.
# ---------------------------------------------------------------------------
def _cache_key(tenant_id: int, role: str, allowed: Optional[Sequence[int]], now: datetime) -> str:
    """tenant is folded in by generate_cache_key (Krishna's cache.py contract);
    role + scope (allowed stores) + a coarse time bucket complete the key so the
    feed refreshes periodically without recomputing on every request."""
    scope_sig = hashlib.md5(",".join(map(str, sorted(allowed or []))).encode()).hexdigest()[:8]
    bucket = now.replace(
        minute=(now.minute // _TIME_BUCKET_MINUTES) * _TIME_BUCKET_MINUTES, second=0, microsecond=0
    ).isoformat()
    return generate_cache_key(f"sage_copilot_feed_t{tenant_id}_r{role}_s{scope_sig}_b{bucket}")


async def generate_feed(
    db: AsyncSession,
    tenant_id: int,
    role: Optional[str],
    allowed: Optional[Sequence[int]] = None,
    scope: str = "chain",
) -> Dict:
    """Compose the Sage Copilot feed for a tenant/role/scope. Compute-on-read +
    Redis cache (fails open to live computation if Redis is unavailable —
    `get_cached`/`set_cached` already swallow Redis errors, per cache.py)."""
    now = datetime.now(timezone.utc)
    key = _cache_key(tenant_id, role or "_default", allowed, now)
    cached = await get_cached(key)
    if cached:
        return cached

    from app.services.decision_center import _region_map  # module-private, same owner (Atharva)

    # Each engine is called EXACTLY ONCE here; build_feed only reshapes the
    # results. `briefing` reuses generate_briefing() wholesale — /api/briefing
    # and the copilot feed can never disagree about "what happened this week".
    briefing = await generate_briefing(db, tenant_id, allowed)
    pending = await gather_scoped_pending(db, tenant_id, allowed, scope)
    region_map = await _region_map(db, tenant_id)
    roi = await roi_summary(db, tenant_id, allowed)
    try:
        fc = await revenue_projection(db, tenant_id, allowed, horizon=14)
    except Exception:
        fc = {"status": "insufficient_history"}
    try:
        fc_text = await forecast_narrative(db, tenant_id, allowed, horizon=14)
    except Exception:
        fc_text = "Not enough evidence to project a forecast yet."

    feed = build_feed({
        "now": now,
        "briefing": briefing,
        "pending_decisions": pending,
        "region_map": region_map,
        "scope": scope,
        "roi": roi,
        "forecast": fc,
        "forecast_text": fc_text,
    })

    await set_cached(key, feed, FEED_TTL_SECONDS)
    return feed
