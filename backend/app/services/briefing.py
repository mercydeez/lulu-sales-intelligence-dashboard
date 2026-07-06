"""
Daily Executive Briefing (blueprint E3-1) — the retention hook.

The one screen an executive opens each morning. It answers the product's four
questions from data the platform already computes — no new ML, no fabrication:

  What is happening?          → headline: revenue/volume, this week vs prior week
  Why is it happening?        → changes: the top open findings (the diagnostics loop)
  What should we do?          → decisions: highest-impact findings + reorder risks
  What will happen if we don't? → leak: dead-stock + projected stockout loss (AED)
  What's coming?              → watch: the UAE retail calendar + the forward forecast
  What went right?            → win: a finding the measure loop confirmed recovered

`build_briefing(raw)` is pure (assembles + writes the analyst-style narrative) so it
unit-tests without a DB, mirroring services/roi.py. `generate_briefing(...)` does the
I/O and is tenant + accessible-store scoped. `build_briefing_html(...)` renders a
self-contained, printable/emailable one-pager (browser → PDF), like the ROI report.
Sacred rule: VOLUME in units, VALUE in AED, never mixed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.roi import roi_summary
from app.services.forecast_service import revenue_projection, reorder_suggestions
from app.services.uae_intelligence import upcoming_events

MAX_CHANGES = 3
MAX_DECISIONS = 3
_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _money(v) -> float:
    return round(float(v or 0), 2)


def _aed(v) -> str:
    return "—" if v is None else f"AED {float(v):,.0f}"


def _pct_change(cur: float, prev: float) -> Optional[float]:
    """Percent change cur vs prev; None when there's no prior baseline."""
    if prev and prev > 0:
        return round((cur - prev) / prev * 100.0, 1)
    return None


def _trend(pct: Optional[float]) -> str:
    if pct is None:
        return "flat"
    if pct > 2:
        return "up"
    if pct < -2:
        return "down"
    return "flat"


def _greeting(now: datetime) -> str:
    h = now.hour
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    return "Good evening"


def build_briefing(raw: Dict) -> Dict:
    """Assemble the briefing + its narrative from raw aggregates. Pure — no I/O.

    raw keys: tenant_name, now (datetime), wow {rev_wk,rev_prev,units_wk,units_prev},
    findings [..], reorder [..], roi {dead_stock_aed,stockout_aed,headline_aed,total_skus},
    season {name,days_until,note,active}|None, forecast {status,horizon_days,
    projected_revenue,avg_daily_revenue}, improved_win {title,metric_before,metric_after}|None.
    """
    now: datetime = raw.get("now") or datetime.now(timezone.utc)
    wow = raw.get("wow") or {}
    rev_wk, rev_prev = _money(wow.get("rev_wk")), _money(wow.get("rev_prev"))
    units_wk = int(wow.get("units_wk") or 0)
    units_prev = int(wow.get("units_prev") or 0)
    rev_pct = _pct_change(rev_wk, rev_prev)
    units_pct = _pct_change(units_wk, units_prev)
    trend = _trend(rev_pct)

    def _dir(pct: Optional[float]) -> str:
        if pct is None:
            return "flat vs the prior week"
        word = "up" if pct > 0 else "down" if pct < 0 else "flat"
        return f"{word} {abs(pct)}% vs the prior week"

    headline = {
        "revenue_aed": rev_wk,
        "revenue_change_pct": rev_pct,
        "units": units_wk,
        "units_change_pct": units_pct,
        "trend": trend,
        "period_label": "Last 7 days vs the prior 7",
        "summary": (
            f"Revenue is {_aed(rev_wk)} over the last 7 days, {_dir(rev_pct)}; "
            f"volume {_dir(units_pct)} at {units_wk:,} units."
        ),
    }

    # ── Why: top open findings (the diagnostics loop) ──
    findings = sorted(
        raw.get("findings") or [],
        key=lambda f: (_SEV_RANK.get((f.get("severity") or "low"), 1),
                       f.get("detected_at") or ""),
        reverse=True,
    )
    changes = [{
        "title": f.get("title"),
        "detail": f.get("detail"),
        "severity": f.get("severity") or "low",
        "entity": f.get("entity_name"),
        "category": f.get("category"),
        "href": "/insights",
    } for f in findings[:MAX_CHANGES]]

    # ── What to decide: findings that carry a recommended action + reorder risks ──
    decisions: List[Dict] = []
    for f in findings:
        if f.get("recommended_action"):
            decisions.append({
                "title": f.get("title"),
                "why": f.get("detail") or f"{f.get('severity','')} finding on {f.get('entity_name','operations')}.",
                "action": f.get("recommended_action"),
                "urgency": f.get("severity") or "medium",
                "href": "/insights",
                "kind": "finding",
            })
    for s in (raw.get("reorder") or []):
        decisions.append({
            "title": f"Reorder {s.get('item_name')} at {s.get('store_name')}",
            "why": f"{s.get('days_of_cover')} days of cover left at the current forecast demand.",
            "action": f"Raise a PO for ~{s.get('recommended_order_qty')} units",
            "urgency": "critical" if s.get("urgency") == "critical" else "high",
            "href": "/procurement",
            "kind": "reorder",
        })
    decisions.sort(key=lambda d: _SEV_RANK.get(d["urgency"], 2), reverse=True)
    decisions = decisions[:MAX_DECISIONS]

    # ── The leak: cost of leaving today's findings unactioned (AED) ──
    roi = raw.get("roi") or {}
    dead = _money(roi.get("dead_stock_aed"))
    stockout = _money(roi.get("stockout_aed"))
    leak_total = round(dead + stockout, 2)
    leak = {
        "dead_stock_aed": dead,
        "stockout_loss_aed": stockout,
        "total_aed": leak_total,
        "note": (
            f"{_aed(dead)} is tied up in dead stock and about {_aed(stockout)} in projected "
            "stockout losses — the cash at stake if today's decisions wait."
        ) if leak_total > 0 else "No material dead-stock or stockout exposure detected.",
    }

    # ── What's coming: UAE calendar + forward forecast ──
    season = raw.get("season")
    fc = raw.get("forecast") or {}
    forecast_block = None
    if fc.get("status") == "ready":
        forecast_block = {
            "horizon_days": fc.get("horizon_days"),
            "projected_revenue_aed": _money(fc.get("projected_revenue")),
            "avg_daily_revenue_aed": _money(fc.get("avg_daily_revenue")),
        }
    watch = {
        "season": (
            {
                "name": season.get("name"),
                "active": bool(season.get("active")),
                "days_until": season.get("days_until"),
                "note": season.get("note"),
                "approx": bool(season.get("approx")),
            } if season else None
        ),
        "forecast": forecast_block,
        "summary": _watch_summary(season, forecast_block),
    }

    # ── The win (honest): a measure-loop recovery, else a positive revenue week ──
    win = None
    iw = raw.get("improved_win")
    if iw:
        win = {
            "title": iw.get("title"),
            "detail": "The metric recovered after your team acted — the platform re-measured and auto-resolved it.",
            "kind": "recovered",
        }
    elif rev_pct is not None and rev_pct > 2:
        win = {
            "title": f"Revenue up {rev_pct}% week-over-week",
            "detail": f"You booked {_aed(rev_wk)} in the last 7 days, ahead of the prior week.",
            "kind": "growth",
        }

    # ── TLDR: one line that captures the morning ──
    parts = [f"revenue {_dir(rev_pct)}"]
    if changes:
        parts.append(f"{len(findings)} open finding{'s' if len(findings) != 1 else ''} to review")
    if leak_total > 0:
        parts.append(f"{_aed(leak_total)} at stake")
    tldr = "Today: " + "; ".join(parts) + "."

    return {
        "date": (now.date().isoformat() if isinstance(now, datetime) else str(now)),
        "generated_at": now.astimezone(timezone.utc).isoformat() if isinstance(now, datetime) else None,
        "tenant_name": raw.get("tenant_name") or "Your company",
        "greeting": _greeting(now),
        "currency": "AED",
        "tldr": tldr,
        "headline": headline,
        "changes": changes,
        "decisions": decisions,
        "win": win,
        "watch": watch,
        "leak": leak,
        "counts": {
            "open_findings": len(findings),
            "decisions": len(decisions),
            "reorder_risks": len(raw.get("reorder") or []),
        },
        "empty": (raw.get("roi") or {}).get("total_skus", 0) == 0 and not findings and rev_wk == 0,
    }


def _watch_summary(season: Optional[Dict], forecast: Optional[Dict]) -> str:
    bits = []
    if season:
        if season.get("active"):
            bits.append(f"{season.get('name')} is live now")
        else:
            bits.append(f"{season.get('name')} starts in {season.get('days_until')} days")
    if forecast:
        bits.append(f"forecast ~{_aed(forecast['projected_revenue_aed'])} over the next {forecast['horizon_days']} days")
    return "; ".join(bits) if bits else "No major seasonal events on the near horizon."


# --- shareable / emailable printable artifact ------------------------------

def _sev_color(sev: str) -> str:
    return {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706", "low": "#0f766e"}.get(sev, "#0f766e")


def build_briefing_html(b: Dict, generated_at: str) -> str:
    """Self-contained, printable HTML one-pager (browser → print → PDF). Pure."""
    h = b["headline"]
    changes = "".join(
        f"<li><span class='dot' style='background:{_sev_color(c['severity'])}'></span>"
        f"<strong>{c['title']}</strong>{(' — ' + c['detail']) if c.get('detail') else ''}</li>"
        for c in b["changes"]
    ) or "<li class='muted'>No open findings — nothing needs attention.</li>"
    decisions = "".join(
        f"<li><strong>{d['title']}</strong><br><span class='muted'>{d['why']}</span>"
        f"<br>→ {d['action']}</li>"
        for d in b["decisions"]
    ) or "<li class='muted'>No decisions queued.</li>"
    win = (f"<div class='win'>🏆 <strong>{b['win']['title']}</strong> — {b['win']['detail']}</div>"
           if b.get("win") else "")
    leak = b["leak"]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Daily briefing — {b['tenant_name']} — {b['date']}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;max-width:760px;margin:32px auto;padding:0 20px}}
 h1{{font-size:20px;margin:0 0 2px}} .sub{{color:#666;font-size:13px;margin:0 0 20px}}
 .headline{{background:#e6f4f0;border-radius:12px;padding:18px 20px;margin-bottom:20px}}
 .headline .n{{font-size:26px;font-weight:700;color:#0f766e}} .headline p{{margin:6px 0 0;font-size:13px;color:#334}}
 h2{{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#666;margin:22px 0 8px}}
 ul{{margin:0;padding:0;list-style:none}} li{{padding:8px 0;border-bottom:1px solid #eee;font-size:14px}}
 .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;vertical-align:middle}}
 .muted{{color:#777}} .win{{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;padding:12px;border-radius:10px;font-size:14px;margin:14px 0}}
 .leak{{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;padding:12px;border-radius:10px;font-size:14px;margin-top:8px}}
 .grid{{display:flex;gap:16px;flex-wrap:wrap;margin-top:6px}} .grid div{{flex:1;min-width:150px}}
 .foot{{margin-top:26px;font-size:11px;color:#999;border-top:1px solid #eee;padding-top:12px}}
</style></head><body>
<h1>{b['greeting']} — daily briefing</h1>
<p class="sub">{b['tenant_name']} · {b['date']} · all values in AED</p>
<div class="headline"><div class="n">{_aed(h['revenue_aed'])}</div>
<p>{h['summary']}</p></div>
{win}
<h2>Why — what changed</h2><ul>{changes}</ul>
<h2>What to decide today</h2><ul>{decisions}</ul>
<h2>On the horizon</h2><p style="font-size:14px">{b['watch']['summary']}.</p>
<div class="leak">💸 Cost of inaction: {leak['note']}</div>
<p class="foot">Generated {generated_at} from your live inventory, sales, diagnostics and forecast.
Figures are operational estimates for discussion, not audited statements. VOLUME in units, VALUE in AED.</p>
</body></html>"""


async def _tenant_name(db: AsyncSession, tenant_id: int) -> str:
    row = (await db.execute(text("""
        SELECT COALESCE(
            (SELECT legal_name FROM tenant_billing_profile WHERE tenant_id = :t),
            (SELECT name FROM tenants WHERE id = :t)) AS name
    """), {"t": tenant_id})).fetchone()
    return (row.name if row and row.name else "Your company")


async def generate_briefing(
    db: AsyncSession,
    tenant_id: int,
    allowed: Optional[Sequence[int]] = None,
) -> Dict:
    """Compose the daily briefing for a tenant/scope from real data. Does I/O; the
    assembly + narrative live in the pure build_briefing()."""
    now = datetime.now(timezone.utc)

    # Week-over-week headline (units + AED), tenant + accessible-store scoped.
    where = ["s.tenant_id = :tid"]
    params: Dict = {"tid": tenant_id}
    if allowed:
        where.append("s.store_id = ANY(:allowed)")
        params["allowed"] = list(allowed)
    wow_row = (await db.execute(text(f"""
        SELECT
          COALESCE(SUM(s.sales) FILTER (WHERE s.date >= CURRENT_DATE - 7 AND s.date < CURRENT_DATE), 0)::bigint  AS units_wk,
          COALESCE(SUM(s.sales) FILTER (WHERE s.date >= CURRENT_DATE - 14 AND s.date < CURRENT_DATE - 7), 0)::bigint AS units_prev,
          COALESCE(SUM(s.sales * it.unit_price_aed) FILTER (WHERE s.date >= CURRENT_DATE - 7 AND s.date < CURRENT_DATE), 0)::numeric  AS rev_wk,
          COALESCE(SUM(s.sales * it.unit_price_aed) FILTER (WHERE s.date >= CURRENT_DATE - 14 AND s.date < CURRENT_DATE - 7), 0)::numeric AS rev_prev
        FROM sales_fact_view s JOIN items it ON it.id = s.item_id
        WHERE {' AND '.join(where)}
    """), params)).mappings().fetchone()

    # Open findings (tenant-scoped) — highest severity first.
    findings = (await db.execute(text("""
        SELECT rule, category, severity, title, detail, entity_name,
               recommended_action, action_type, detected_at
        FROM findings
        WHERE tenant_id = :tid AND status IN ('open', 'acknowledged')
        ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3
                               WHEN 'medium' THEN 2 ELSE 1 END DESC, detected_at DESC
        LIMIT 12
    """), {"tid": tenant_id})).mappings().all()

    # A recent measure-loop win (a finding that recovered), if any.
    improved = (await db.execute(text("""
        SELECT title, metric_before, metric_after FROM findings
        WHERE tenant_id = :tid AND outcome_status = 'improved'
        ORDER BY measured_at DESC NULLS LAST LIMIT 1
    """), {"tid": tenant_id})).mappings().fetchone()

    # Reuse the existing services (each tenant/scope-aware + cached). ROI is
    # store-scoped so a store/regional manager's "at stake" is THEIR number.
    roi = await roi_summary(db, tenant_id, allowed)
    try:
        fc = await revenue_projection(db, tenant_id, allowed, horizon=14)
    except Exception:
        fc = {"status": "insufficient_history"}
    try:
        reorder = (await reorder_suggestions(db, tenant_id, allowed, limit=3)).get("suggestions", [])
    except Exception:
        reorder = []

    events = upcoming_events(now.date(), horizon_days=45)
    season = events[0] if events else None

    raw = {
        "tenant_name": await _tenant_name(db, tenant_id),
        "now": now,
        "wow": dict(wow_row or {}),
        "findings": [dict(f) for f in findings],
        "reorder": reorder,
        "roi": {
            "dead_stock_aed": roi["metrics"]["dead_stock"]["aed"],
            "stockout_aed": roi["metrics"]["stockout_loss_estimate"]["aed"],
            "headline_aed": roi["headline"]["aed"],
            "total_skus": roi["context"]["total_skus"],
        },
        "season": season,
        "forecast": {
            "status": fc.get("status"),
            "horizon_days": fc.get("horizon_days"),
            "projected_revenue": fc.get("projected_revenue"),
            "avg_daily_revenue": fc.get("avg_daily_revenue"),
        },
        "improved_win": (dict(improved) if improved else None),
    }
    return build_briefing(raw)
