"""
ROI / cash-savings calculator (the CFO-ready AED number that closes a pilot).

Computes ONLY honest, derivable numbers from real data (inventory + items +
sales_fact_view). Anything that needs data the tenant hasn't imported (e.g. unit
cost for GMROI) is returned as null with an explicit `needs` flag — NEVER fabricated.
Sacred rule: VOLUME in units, VALUE in AED, never mixed.

The pure `build_summary` assembles the response + flags from raw SQL aggregates, so
the assembly logic (projections, "needs cost" gating) unit-tests without a DB.
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEAD_STOCK_DAYS = 60          # no sale in this many days (or zero velocity) = dead
STOCKOUT_PROJECTION_DAYS = 30  # window for the stockout opportunity-loss estimate

# The single `needs` string for every cost-dependent metric. Since E2-3 a tenant
# can supply cost either as an effective-dated item cost (preferred) or the legacy
# per-store inventory cost column.
_NEEDS_COST = "unit cost — import item costs, or an inventory file with a cost column"


def _money(v) -> float:
    return round(float(v or 0), 2)


def build_summary(raw: Dict, projection_days: int = STOCKOUT_PROJECTION_DAYS) -> Dict:
    """Assemble the ROI response from raw aggregates. Pure — no I/O.

    raw keys: inventory_retail_value, inventory_cost_value, has_cost,
    dead_stock_value, dead_stock_cost_value, dead_stock_count, stockout_daily_loss_aed,
    below_reorder_count, avg_days_of_supply, total_skus, total_stock_units,
    revenue_90d, cogs_90d, costed_revenue_90d.
    """
    has_cost = bool(raw.get("has_cost"))
    revenue_90d = _money(raw.get("revenue_90d"))
    stockout_daily = _money(raw.get("stockout_daily_loss_aed"))

    # GMROI = gross margin / inventory at cost. Only honest with cost data.
    #
    # Margin is computed over COSTED revenue — the sales we could actually price a
    # cost against — not total revenue. Subtracting a partial COGS from a full
    # revenue would inflate margin by exactly the uncosted sales, which is the kind
    # of quiet lie this codebase refuses to tell.
    gmroi: Optional[float] = None
    gross_margin_90d: Optional[float] = None
    gross_margin_pct: Optional[float] = None
    inv_cost = _money(raw.get("inventory_cost_value"))
    costed_revenue = _money(raw.get("costed_revenue_90d"))
    if has_cost and inv_cost > 0 and costed_revenue > 0:
        gross_margin_90d = _money(costed_revenue - _money(raw.get("cogs_90d")))
        gmroi = round(gross_margin_90d / inv_cost, 2)
        gross_margin_pct = round(100.0 * gross_margin_90d / costed_revenue, 1)

    return {
        "currency": "AED",
        "metrics": {
            "inventory_value_retail": {
                "aed": _money(raw.get("inventory_retail_value")),
                "label": "Inventory value at retail",
            },
            "cash_tied_at_cost": {
                "aed": inv_cost if has_cost else None,
                "label": "Cash tied in inventory (at cost)",
                "needs": None if has_cost else _NEEDS_COST,
            },
            "dead_stock": {
                "aed": _money(raw.get("dead_stock_value")),
                "count": int(raw.get("dead_stock_count") or 0),
                "label": f"Dead stock (no sale in {DEAD_STOCK_DAYS}d)",
                # What the dead stock actually COST you — the cash sunk, as opposed
                # to the retail value you hoped to realise (E2-3).
                "cost_aed": _money(raw.get("dead_stock_cost_value")) if has_cost else None,
                "needs": None if has_cost else _NEEDS_COST,
            },
            "stockout_loss_estimate": {
                "aed": _money(stockout_daily * projection_days),
                "per_day_aed": stockout_daily,
                "projection_days": projection_days,
                "label": "Estimated stockout opportunity loss",
                "is_estimate": True,
            },
            "gmroi": {
                "value": gmroi,
                "gross_margin_90d_aed": gross_margin_90d,
                "gross_margin_pct": gross_margin_pct,
                # The revenue the margin is actually computed over. If this is below
                # revenue_90d, some sales had no cost period — say so, don't hide it.
                "costed_revenue_90d_aed": costed_revenue if has_cost else None,
                "label": "GMROI (gross margin return on inventory)",
                "needs": None if gmroi is not None else _NEEDS_COST,
            },
            "days_of_supply_avg": {
                "value": round(float(raw.get("avg_days_of_supply") or 0), 1),
                "label": "Average days of supply",
            },
        },
        "context": {
            "revenue_90d_aed": revenue_90d,
            "below_reorder_count": int(raw.get("below_reorder_count") or 0),
            "total_skus": int(raw.get("total_skus") or 0),
            "total_stock_units": int(raw.get("total_stock_units") or 0),
            "has_cost_data": has_cost,
            # What fraction of revenue we could actually cost. < 100% means some
            # sales fell outside every cost period — margin covers only the rest.
            "cost_coverage_pct": (
                round(100.0 * costed_revenue / revenue_90d, 1)
                if has_cost and revenue_90d > 0 else None
            ),
        },
        "headline": {
            "label": "Cash you could release + recover",
            "aed": _money(raw.get("dead_stock_value")) + _money(stockout_daily * projection_days),
        },
    }


# --- shareable CFO artifact (printable HTML + CSV) -------------------------
# Pure builders so the report can be unit-tested without a DB. Every metric carries
# a one-line derivation (methodology) — a CFO trusts numbers they can reconstruct.

_METHOD = {
    "inventory_value_retail": "Σ on-hand units × retail price (AED)",
    "cash_tied_at_cost": "Σ on-hand units × unit cost, effective-dated (AED)",
    "dead_stock": "stock with no sale in 60 days, valued at retail (and at cost)",
    "stockout_loss_estimate": "out-of-stock items × avg daily units × price, projected over the window",
    "gmroi": "gross margin (90d, cost as of each sale's date) ÷ inventory at cost",
    "days_of_supply_avg": "avg(on-hand ÷ avg daily units sold)",
}


def _fmt_aed(v) -> str:
    return "needs cost data" if v is None else f"AED {float(v):,.0f}"


def _report_rows(summary: Dict) -> list:
    """Flatten the summary into (label, value, methodology) rows. Pure."""
    m = summary["metrics"]
    rows = [
        (m["inventory_value_retail"]["label"], _fmt_aed(m["inventory_value_retail"]["aed"]), _METHOD["inventory_value_retail"]),
        (m["cash_tied_at_cost"]["label"], _fmt_aed(m["cash_tied_at_cost"]["aed"]), _METHOD["cash_tied_at_cost"]),
        (m["dead_stock"]["label"], f'{_fmt_aed(m["dead_stock"]["aed"])} ({m["dead_stock"]["count"]} SKUs)', _METHOD["dead_stock"]),
        (m["stockout_loss_estimate"]["label"] + f' ({m["stockout_loss_estimate"]["projection_days"]}-day estimate)',
         _fmt_aed(m["stockout_loss_estimate"]["aed"]), _METHOD["stockout_loss_estimate"]),
        (m["gmroi"]["label"], ("needs cost data" if m["gmroi"]["value"] is None else f'{m["gmroi"]["value"]}×'), _METHOD["gmroi"]),
        (m["days_of_supply_avg"]["label"], f'{m["days_of_supply_avg"]["value"]} days', _METHOD["days_of_supply_avg"]),
    ]
    return rows


def build_report_csv(summary: Dict) -> str:
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["Metric", "Value", "How it is derived"])
    w.writerow(["Cash to release + recover (headline)", _fmt_aed(summary["headline"]["aed"]),
                "dead-stock value + projected stockout loss"])
    for label, value, method in _report_rows(summary):
        w.writerow([label, value, method])
    ctx = summary["context"]
    w.writerow([])
    w.writerow(["Revenue (90d)", _fmt_aed(ctx["revenue_90d_aed"]), ""])
    w.writerow(["SKUs below reorder", ctx["below_reorder_count"], ""])
    w.writerow(["Total SKUs", ctx["total_skus"], ""])
    return buf.getvalue()


def build_report_html(summary: Dict, company_name: str, generated_at: str) -> str:
    """Self-contained, printable HTML one-pager (browser → print → PDF). Pure."""
    rows_html = "".join(
        f"<tr><td>{label}</td><td class='v'>{value}</td><td class='m'>{method}</td></tr>"
        for label, value, method in _report_rows(summary)
    )
    headline = _fmt_aed(summary["headline"]["aed"])
    ctx = summary["context"]
    cost_note = ("" if ctx["has_cost_data"] else
                 "<p class='warn'>Cash-at-cost and GMROI need a unit-cost column on imported "
                 "inventory. We never estimate cost.</p>")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Inventory value summary — {company_name}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1a1a1a;max-width:760px;margin:32px auto;padding:0 20px}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#666;font-size:13px;margin:0 0 24px}}
 .headline{{background:#e6f4f0;border-radius:12px;padding:20px;text-align:center;margin-bottom:24px}}
 .headline .n{{font-size:30px;font-weight:700;color:#0f766e;margin:4px 0}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 th,td{{text-align:left;padding:9px 8px;border-bottom:1px solid #eee}}
 th{{color:#666;font-weight:600;font-size:12px;text-transform:uppercase}}
 td.v{{font-weight:600;white-space:nowrap}} td.m{{color:#777;font-size:12px}}
 .ctx{{margin-top:20px;font-size:13px;color:#444}}
 .warn{{background:#fef3c7;border:1px solid #fde68a;color:#92400e;padding:10px;border-radius:8px;font-size:12px;margin-top:16px}}
 .foot{{margin-top:28px;font-size:11px;color:#999;border-top:1px solid #eee;padding-top:12px}}
</style></head><body>
<h1>Inventory value summary</h1>
<p class="sub">{company_name} · generated {generated_at} · all values in AED</p>
<div class="headline"><div>Cash you could release + recover</div><div class="n">{headline}</div>
<div style="font-size:12px;color:#555">dead-stock value + projected stockout opportunity loss</div></div>
<table><thead><tr><th>Metric</th><th>Value</th><th>How it is derived</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<p class="ctx"><strong>Context:</strong> revenue (90d) {_fmt_aed(ctx['revenue_90d_aed'])} ·
{ctx['below_reorder_count']} SKUs below reorder · {ctx['total_skus']} SKUs ·
{ctx['total_stock_units']:,} units on hand.</p>
{cost_note}
<p class="foot">Computed from imported inventory + sales. Draft — figures are operational
estimates for discussion; not audited financial statements. Tax/legal treatment requires
review by a qualified UAE professional.</p>
</body></html>"""


async def roi_summary(db: AsyncSession, tenant_id: int, allowed=None) -> Dict:
    """Compute the ROI summary for a tenant from real data. When `allowed` (a list
    of store ids) is given, scope every figure to those stores — so a store or
    regional manager sees THEIR at-stake number, not the whole chain's."""
    inv_scope = ""
    sale_scope = ""
    params = {"tid": tenant_id}
    if allowed:
        inv_scope = "AND i.store_id = ANY(:allowed)"
        sale_scope = "AND s.store_id = ANY(:allowed)"
        params["allowed"] = list(allowed)

    # E2-3 cost basis: the effective-dated `items.unit_cost_aed` (current period,
    # maintained from item_costs) is authoritative; we fall back to the legacy
    # per-store `inventory.unit_cost` only where no cost period exists. GMROI's
    # numerator (COGS, point-in-time) and denominator (inventory at cost) MUST
    # share this basis or the ratio is meaningless.
    inv = (await db.execute(text(f"""
        SELECT
          COALESCE(SUM(i.current_stock * it.unit_price_aed), 0)            AS inventory_retail_value,
          COALESCE(SUM(i.current_stock * COALESCE(it.unit_cost_aed, NULLIF(i.unit_cost, 0))), 0)
                                                                          AS inventory_cost_value,
          BOOL_OR(COALESCE(it.unit_cost_aed, NULLIF(i.unit_cost, 0)) > 0) AS has_cost,
          COALESCE(SUM(CASE WHEN i.current_stock > 0
                  AND (i.average_daily_sales = 0
                       OR i.last_sale_date < (CURRENT_DATE - {DEAD_STOCK_DAYS}))
                  THEN i.current_stock * it.unit_price_aed ELSE 0 END), 0) AS dead_stock_value,
          -- Dead stock at COST is the cash actually sunk (retail value is what you
          -- hoped to get). NULL-safe: contributes 0 only where a cost exists.
          COALESCE(SUM(CASE WHEN i.current_stock > 0
                  AND (i.average_daily_sales = 0
                       OR i.last_sale_date < (CURRENT_DATE - {DEAD_STOCK_DAYS}))
                  THEN i.current_stock * COALESCE(it.unit_cost_aed, NULLIF(i.unit_cost, 0))
                  ELSE 0 END), 0)                                          AS dead_stock_cost_value,
          COALESCE(SUM(CASE WHEN i.current_stock > 0
                  AND (i.average_daily_sales = 0
                       OR i.last_sale_date < (CURRENT_DATE - {DEAD_STOCK_DAYS}))
                  THEN 1 ELSE 0 END), 0)                                   AS dead_stock_count,
          COALESCE(SUM(CASE WHEN i.current_stock = 0 AND i.average_daily_sales > 0
                  THEN i.average_daily_sales * it.unit_price_aed ELSE 0 END), 0)
                                                                          AS stockout_daily_loss_aed,
          COALESCE(SUM(CASE WHEN i.current_stock <= i.reorder_point THEN 1 ELSE 0 END), 0)
                                                                          AS below_reorder_count,
          COALESCE(AVG(CASE WHEN i.average_daily_sales > 0
                  THEN i.current_stock / i.average_daily_sales END), 0)    AS avg_days_of_supply,
          COUNT(DISTINCT i.item_id)                                       AS total_skus,
          COALESCE(SUM(i.current_stock), 0)                              AS total_stock_units
        FROM inventory i
        JOIN items it ON it.id = i.item_id
        WHERE it.tenant_id = :tid {inv_scope}
    """), params)).mappings().fetchone()

    rev = (await db.execute(text(f"""
        SELECT COALESCE(SUM(s.sales * it.unit_price_aed), 0) AS revenue_90d
        FROM sales_fact_view s JOIN items it ON it.id = s.item_id
        WHERE s.tenant_id = :tid AND s.date >= (CURRENT_DATE - 90) {sale_scope}
    """), params)).mappings().fetchone()

    raw = dict(inv or {})
    raw["revenue_90d"] = (rev or {}).get("revenue_90d", 0)
    raw["cogs_90d"] = 0
    if raw.get("has_cost"):
        # E2-3: point-in-time COGS. metric_margin_fact joins each sale to the cost
        # that was in effect ON ITS OWN DATE, so a mid-period supplier price change
        # no longer rewrites history. Previously this averaged every store's current
        # unit_cost and applied that one number to 90 days of past sales.
        # cogs_aed is NULL where no cost period covers the sale — those rows are
        # excluded from BOTH sums so the margin we report is over the sales we can
        # actually cost, never diluted by a silent zero.
        cogs = (await db.execute(text(f"""
            SELECT COALESCE(SUM(m.cogs_aed), 0)    AS cogs_90d,
                   COALESCE(SUM(m.revenue_aed), 0) AS costed_revenue_90d
            FROM metric_margin_fact m
            WHERE m.tenant_id = :tid
              AND m.date >= (CURRENT_DATE - 90)
              AND m.cogs_aed IS NOT NULL
              {sale_scope.replace('s.store_id', 'm.store_id')}
        """), params)).mappings().fetchone()
        raw["cogs_90d"] = (cogs or {}).get("cogs_90d", 0)
        raw["costed_revenue_90d"] = (cogs or {}).get("costed_revenue_90d", 0)

    return build_summary(raw)
