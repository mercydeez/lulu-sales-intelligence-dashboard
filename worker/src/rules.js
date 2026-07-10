// Deterministic, explainable diagnostic rules (A3). Each rule compares a recent
// 7-day window to the prior 7 days and emits findings with the evidence numbers
// and a human sentence. No ML, no hidden heuristics — everything is derivable.
//
// E6-1: the metric MATH now lives in shared SQL (migration 050 `metric_*` views),
// the SAME definitions routes/kpis.py reads. Each rule here is a thin SELECT that
// thresholds and formats — it computes no revenue, change ratio, rate, or average
// in JS. That defuses the Python/JS "two-language drift" on what the numbers mean.
//
// Convention (matches the app): VALUE is AED revenue (units * unit_price_aed),
// VOLUME is units. Returns are rows with units < 0.
import { query } from "./db.js";

// ISO-week stamp so a finding is per-week: re-runs in the same week upsert; a new
// week produces a fresh finding.
function isoWeek(d = new Date()) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const week =
    1 + Math.round(((date - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return `${date.getUTCFullYear()}W${String(week).padStart(2, "0")}`;
}

const WEEK = isoWeek();
const fmtAed = (n) => `AED ${Math.round(Number(n)).toLocaleString("en-US")}`;
const pct = (n) => `${(Number(n) * 100).toFixed(1)}%`;

function severityFromDrop(changeRatio) {
  // changeRatio is negative for a drop.
  if (changeRatio <= -0.4) return "critical";
  if (changeRatio <= -0.3) return "high";
  return "medium";
}

// --- Rule: per-store revenue drop week-over-week ---------------------------
// Reads metric_store_wow; the change ratio is computed in SQL.
async function revenueDropByStore(tenantId) {
  const rows = await query(
    `SELECT store_id, store_name, rev_recent, rev_prior, change
       FROM metric_store_wow
      WHERE tenant_id = $1 AND rev_prior > 0 AND change <= -0.15`,
    [tenantId]
  );
  return rows.map((r) => {
    const change = Number(r.change);
    return {
      rule: "revenue_drop",
      category: "sales",
      severity: severityFromDrop(change),
      title: `Revenue down ${pct(Math.abs(change))} at ${r.store_name}`,
      detail:
        `${r.store_name} made ${fmtAed(r.rev_recent)} in the last 7 days vs ` +
        `${fmtAed(r.rev_prior)} the week before — a ${pct(Math.abs(change))} drop.`,
      evidence: { rev_recent: Number(r.rev_recent), rev_prior: Number(r.rev_prior), change },
      entity_type: "store",
      entity_id: String(r.store_id),
      entity_name: r.store_name,
      metric_value: change,
      dedupe_key: `revenue_drop:store:${r.store_id}:${WEEK}`,
      recommended_action:
        `Check ${r.store_name} for stockouts, staffing, or a local competitor; consider a targeted promotion.`,
      action_type: "promote",
    };
  });
}

// --- Rule: per-category revenue slump --------------------------------------
// Reads metric_category_wow; the change ratio is computed in SQL.
async function categorySlump(tenantId) {
  const rows = await query(
    `SELECT category, rev_recent, rev_prior, change
       FROM metric_category_wow
      WHERE tenant_id = $1 AND rev_prior > 0 AND change <= -0.2`,
    [tenantId]
  );
  return rows.map((r) => {
    const change = Number(r.change);
    return {
      rule: "category_slump",
      category: "sales",
      severity: severityFromDrop(change),
      title: `${r.category} revenue down ${pct(Math.abs(change))}`,
      detail:
        `The ${r.category} category fell to ${fmtAed(r.rev_recent)} this week from ` +
        `${fmtAed(r.rev_prior)} last week (${pct(Math.abs(change))} down).`,
      evidence: { rev_recent: Number(r.rev_recent), rev_prior: Number(r.rev_prior), change },
      entity_type: "category",
      entity_id: r.category,
      entity_name: r.category,
      metric_value: change,
      dedupe_key: `category_slump:category:${r.category}:${WEEK}`,
      recommended_action:
        `Review ${r.category} pricing and shelf placement; check for supply gaps across stores.`,
      action_type: "review_pricing",
    };
  });
}

// --- Rule: returns spike (tenant-wide) -------------------------------------
// Reads metric_returns_wow; the noise floor + trigger stay as thresholds here.
async function returnSpike(tenantId) {
  const rows = await query(
    `SELECT returns_recent_units, returns_prior_units, change
       FROM metric_returns_wow
      WHERE tenant_id = $1`,
    [tenantId]
  );
  const r = rows[0];
  if (!r) return [];
  const recent = Number(r.returns_recent_units);
  const prior = Number(r.returns_prior_units);
  if (prior <= 0 || recent < 50) return []; // floor: ignore noise on tiny volumes
  const change = Number(r.change);
  if (change < 0.4) return [];
  return [
    {
      rule: "return_spike",
      category: "returns",
      severity: change >= 1.0 ? "high" : "medium",
      title: `Returns up ${pct(change)} this week`,
      detail:
        `Returned units rose to ${Math.round(recent).toLocaleString()} in the last 7 days ` +
        `from ${Math.round(prior).toLocaleString()} the week before (+${pct(change)}).`,
      evidence: { returns_recent_units: recent, returns_prior_units: prior, change },
      entity_type: "global",
      entity_id: null,
      entity_name: "All stores",
      metric_value: change,
      dedupe_key: `return_spike:global:all:${WEEK}`,
      recommended_action:
        "Investigate the return spike — check for a defective batch, a mispriced item, or a delivery issue this week.",
      action_type: "investigate",
    },
  ];
}

// --- Rule: laggard store (growing materially slower than the chain) --------
// Relative underperformance — fires even when every store is up, surfacing the
// store that's leaving money on the table vs its peers. Reads metric_store_wow;
// the chain-average growth and per-store gap are computed in SQL.
async function laggardStore(tenantId) {
  const rows = await query(
    `SELECT store_id, store_name, change AS growth, chain_avg_change AS chain_growth, gap_pp
       FROM metric_store_wow
      WHERE tenant_id = $1 AND rev_prior > 0 AND change < chain_avg_change - 0.05
      ORDER BY change ASC LIMIT 3`,
    [tenantId]
  );
  return rows.map((r) => {
    const gap = Number(r.gap_pp);
    return {
      rule: "laggard_store",
      category: "sales",
      severity: gap >= 0.12 ? "high" : "medium",
      title: `${r.store_name} is lagging peers`,
      detail:
        `${r.store_name} grew ${pct(Number(r.growth))} week-over-week while the chain averaged ` +
        `${pct(Number(r.chain_growth))} — ${pct(gap)} behind its peers.`,
      evidence: { store_growth: Number(r.growth), chain_growth: Number(r.chain_growth), gap_pp: gap },
      entity_type: "store",
      entity_id: String(r.store_id),
      entity_name: r.store_name,
      metric_value: Number(r.growth),
      dedupe_key: `laggard_store:store:${r.store_id}:${WEEK}`,
      recommended_action:
        `Compare ${r.store_name}'s assortment and promotions to the top stores; close the gap with a local campaign.`,
      action_type: "promote",
    };
  });
}

// --- Rule: high return rate by category ------------------------------------
// Returns as a share of gross units, flagged when well above the tenant average.
// Reads metric_category_return_rate; rate and the tenant mean are computed in SQL.
async function highReturnRateCategory(tenantId) {
  const rows = await query(
    `SELECT category, rate, return_units, gross_units, mean_rate
       FROM metric_category_return_rate
      WHERE tenant_id = $1
        AND gross_units > 0
        AND rate > GREATEST(mean_rate * 1.5, 0.05)
      ORDER BY rate DESC LIMIT 3`,
    [tenantId]
  );
  return rows.map((r) => {
    const rate = Number(r.rate);
    return {
      rule: "high_return_rate",
      category: "returns",
      severity: rate >= 0.12 ? "high" : "medium",
      title: `High return rate in ${r.category}`,
      detail:
        `${r.category} has a ${pct(rate)} return rate over 30 days (chain average ` +
        `${pct(Number(r.mean_rate))}) — ${Math.round(Number(r.return_units)).toLocaleString()} units returned.`,
      evidence: {
        return_rate: rate,
        mean_rate: Number(r.mean_rate),
        return_units: Number(r.return_units),
        gross_units: Number(r.gross_units),
      },
      entity_type: "category",
      entity_id: r.category,
      entity_name: r.category,
      metric_value: rate,
      dedupe_key: `high_return_rate:category:${r.category}:${WEEK}`,
      recommended_action:
        `Audit ${r.category} supplier quality and product descriptions; high returns often signal a quality or expectation gap.`,
      action_type: "review_supplier",
    };
  });
}

// ===========================================================================
// Rules 6-12 (E3-5). Every number below is read from a metric_* view (migration
// 061) — these functions threshold and format, they compute nothing. Same E6-1
// discipline as rules 1-5.
// ===========================================================================

const fmtUnits = (n) => `${Math.round(Number(n)).toLocaleString("en-US")} units`;
const plural = (n, s) => `${n} ${s}${Number(n) === 1 ? "" : "s"}`;

// --- Rule 6: items out of stock right now ----------------------------------
// There is no stock-level history table, so a true "stockout days streak" is not
// derivable. We report what the data supports: currently out of stock, and how
// long since it last sold. Measuring what exists beats inventing what does not.
async function stockoutItems(tenantId) {
  const rows = await query(
    `SELECT store_id, store_name, item_id, item_name, category,
            days_since_last_sale, average_daily_sales
       FROM metric_inventory_state
      WHERE tenant_id = $1
        AND is_out_of_stock
        AND average_daily_sales > 0
      ORDER BY average_daily_sales DESC
      LIMIT 25`,
    [tenantId]
  );
  return rows.map((r) => {
    const daily = Number(r.average_daily_sales);
    const stale = r.days_since_last_sale === null ? null : Number(r.days_since_last_sale);
    return {
      rule: "stockout",
      category: "inventory",
      severity: daily >= 20 ? "critical" : daily >= 5 ? "high" : "medium",
      title: `${r.item_name} is out of stock at ${r.store_name}`,
      detail:
        `${r.item_name} has zero on-hand at ${r.store_name} and normally sells ` +
        `${fmtUnits(daily)}/day` +
        (stale !== null ? `; last sale was ${plural(stale, "day")} ago.` : "."),
      evidence: {
        average_daily_sales: daily,
        days_since_last_sale: stale,
        current_stock: 0,
      },
      entity_type: "item",
      entity_id: String(r.item_id),
      entity_name: r.item_name,
      // Higher = worse: the faster it sells, the more each empty day costs.
      metric_value: daily,
      dedupe_key: `stockout:item:${r.item_id}:${WEEK}`,
      recommended_action:
        `Raise a purchase order for ${r.item_name} at ${r.store_name}; every day out of stock ` +
        `forgoes about ${fmtUnits(daily)} of demand.`,
      action_type: "reorder",
    };
  });
}

// --- Rule 7: dead stock is GROWING -----------------------------------------
// One dead SKU is housekeeping. A rising count is a buying problem.
async function deadStockGrowth(tenantId) {
  const rows = await query(
    `SELECT dead_skus_recent, dead_skus_prior, dead_value_recent_aed, dead_value_prior_aed
       FROM metric_dead_stock_growth
      WHERE tenant_id = $1 AND dead_skus_prior > 0 AND dead_skus_recent > dead_skus_prior`,
    [tenantId]
  );
  return rows.map((r) => {
    const recent = Number(r.dead_skus_recent);
    const prior = Number(r.dead_skus_prior);
    const growth = (recent - prior) / prior;
    return {
      rule: "dead_stock_growth",
      category: "inventory",
      severity: growth >= 0.5 ? "high" : "medium",
      title: `Dead stock grew ${pct(growth)} — ${recent} SKUs unsold for 30 days`,
      detail:
        `${recent} SKUs had no sale in the last 30 days, up from ${prior} in the 30 days before ` +
        `— ${fmtAed(r.dead_value_recent_aed)} of stock at retail is not moving.`,
      evidence: {
        dead_skus_recent: recent,
        dead_skus_prior: prior,
        dead_value_recent_aed: Number(r.dead_value_recent_aed),
        dead_value_prior_aed: Number(r.dead_value_prior_aed),
        growth,
      },
      entity_type: "global",
      entity_id: null,
      entity_name: "All stores",
      metric_value: growth, // higher = worse
      dedupe_key: `dead_stock_growth:global:all:${WEEK}`,
      recommended_action:
        `Review the ${recent} non-moving SKUs for markdown or return-to-supplier, and tighten reorder ` +
        `points so the buy stops replenishing them.`,
      action_type: "markdown",
    };
  });
}

// --- Rule 8: the forecast is missing badly ---------------------------------
// Scored against the SEASONAL-NAIVE baseline the app itself publishes, so a miss
// here means exactly what a miss means in the Forecast Lab.
async function forecastMiss(tenantId) {
  const rows = await query(
    `SELECT store_id, store_name, actual_units, naive_units, abs_error_units, wape, days_compared
       FROM metric_forecast_miss
      WHERE tenant_id = $1 AND wape IS NOT NULL AND wape >= 0.30 AND days_compared >= 5`,
    [tenantId]
  );
  return rows.map((r) => {
    const wape = Number(r.wape);
    return {
      rule: "forecast_miss",
      category: "forecast",
      severity: wape >= 0.5 ? "high" : "medium",
      title: `Demand at ${r.store_name} is ${pct(wape)} off its own weekly pattern`,
      detail:
        `Over the last ${r.days_compared} days ${r.store_name} sold ${fmtUnits(r.actual_units)} against ` +
        `${fmtUnits(r.naive_units)} the same weekdays a week earlier — a ${pct(wape)} weighted error. ` +
        `Something changed that last week does not explain.`,
      evidence: {
        actual_units: Number(r.actual_units),
        naive_units: Number(r.naive_units),
        abs_error_units: Number(r.abs_error_units),
        wape,
        baseline: "seasonal_naive",
        days_compared: Number(r.days_compared),
      },
      entity_type: "store",
      entity_id: String(r.store_id),
      entity_name: r.store_name,
      metric_value: wape, // higher = worse
      dedupe_key: `forecast_miss:store:${r.store_id}:${WEEK}`,
      recommended_action:
        `Check ${r.store_name} for a promotion, stockout or local event in the window; if none, the ` +
        `demand pattern has shifted and the reorder points need re-basing.`,
      action_type: "investigate",
    };
  });
}

// --- Rule 9: price anomaly — selling at or below cost -----------------------
// Items with no cost period are ABSENT from the view (E2-3), so a missing row is
// never silently reported as a healthy margin.
async function priceAnomaly(tenantId) {
  const rows = await query(
    `SELECT item_id, item_name, category, units_30d, revenue_30d_aed, cogs_30d_aed,
            margin_30d_aed, margin_ratio, unit_price_aed, unit_cost_aed
       FROM metric_price_anomaly
      WHERE tenant_id = $1 AND margin_ratio IS NOT NULL AND margin_ratio <= 0.05`,
    [tenantId]
  );
  return rows.map((r) => {
    const ratio = Number(r.margin_ratio);
    const losing = ratio < 0;
    return {
      rule: "price_anomaly",
      category: "sales",
      severity: losing ? "critical" : "high",
      title: losing
        ? `${r.item_name} is selling BELOW cost`
        : `${r.item_name} has almost no margin (${pct(ratio)})`,
      detail:
        `${r.item_name} sold ${fmtUnits(r.units_30d)} in 30 days for ${fmtAed(r.revenue_30d_aed)} ` +
        `against ${fmtAed(r.cogs_30d_aed)} of cost — ${fmtAed(r.margin_30d_aed)} gross margin ` +
        `(${pct(ratio)}). Price ${fmtAed(r.unit_price_aed)} vs cost ${fmtAed(r.unit_cost_aed)}.`,
      evidence: {
        units_30d: Number(r.units_30d),
        revenue_30d_aed: Number(r.revenue_30d_aed),
        cogs_30d_aed: Number(r.cogs_30d_aed),
        margin_30d_aed: Number(r.margin_30d_aed),
        margin_ratio: ratio,
        unit_price_aed: Number(r.unit_price_aed),
        unit_cost_aed: Number(r.unit_cost_aed),
      },
      entity_type: "item",
      entity_id: String(r.item_id),
      entity_name: r.item_name,
      // LOWER is worse (a negative ratio is the worst case), matching the
      // revenue_drop convention — so it stays OUT of HIGHER_IS_WORSE.
      metric_value: ratio,
      dedupe_key: `price_anomaly:item:${r.item_id}:${WEEK}`,
      recommended_action: losing
        ? `Stop the bleed on ${r.item_name}: re-price above ${fmtAed(r.unit_cost_aed)} or renegotiate the cost.`
        : `Review ${r.item_name}'s price or supplier cost — it is selling at almost no margin.`,
      action_type: "reprice",
    };
  });
}

// --- Rule 10: supplier is late ---------------------------------------------
// purchase_orders has no expected_delivery_date; it is derived in SQL as
// sent_at + the supplier's own lead time.
async function supplierLate(tenantId) {
  const rows = await query(
    `SELECT supplier_id, supplier_name, overdue_pos, overdue_value_aed,
            max_days_overdue, avg_days_overdue
       FROM metric_supplier_overdue
      WHERE tenant_id = $1 AND max_days_overdue >= 3`,
    [tenantId]
  );
  return rows.map((r) => {
    const maxDays = Number(r.max_days_overdue);
    return {
      rule: "supplier_late",
      category: "inventory",
      severity: maxDays >= 14 ? "critical" : maxDays >= 7 ? "high" : "medium",
      title: `${r.supplier_name} is ${plural(maxDays, "day")} late`,
      detail:
        `${r.supplier_name} has ${plural(Number(r.overdue_pos), "purchase order")} past the agreed ` +
        `lead time (worst: ${plural(maxDays, "day")}, average ${r.avg_days_overdue}), ` +
        `covering ${fmtAed(r.overdue_value_aed)} of stock you have already committed to.`,
      evidence: {
        overdue_pos: Number(r.overdue_pos),
        overdue_value_aed: Number(r.overdue_value_aed),
        max_days_overdue: maxDays,
        avg_days_overdue: Number(r.avg_days_overdue),
      },
      entity_type: "supplier",
      entity_id: String(r.supplier_id),
      entity_name: r.supplier_name,
      metric_value: maxDays, // higher = worse
      dedupe_key: `supplier_late:supplier:${r.supplier_id}:${WEEK}`,
      recommended_action:
        `Chase ${r.supplier_name} on the overdue orders and, if this repeats, re-rate their lead time ` +
        `so reorder points stop assuming a delivery date they never hit.`,
      action_type: "review_supplier",
    };
  });
}

// --- Rule 11: a category is losing SHARE -----------------------------------
// Share, not revenue: a category can grow in AED and still be losing ground.
async function categoryShareShift(tenantId) {
  const rows = await query(
    `SELECT category, rev_recent, rev_prior, share_recent, share_prior, shift_pp
       FROM metric_category_share
      WHERE tenant_id = $1 AND shift_pp IS NOT NULL AND shift_pp <= -1.5`,
    [tenantId]
  );
  return rows.map((r) => {
    const shift = Number(r.shift_pp); // negative percentage POINTS
    const grew = Number(r.rev_recent) > Number(r.rev_prior);
    return {
      rule: "category_share_shift",
      category: "sales",
      severity: shift <= -4 ? "high" : "medium",
      title: `${r.category} lost ${Math.abs(shift).toFixed(1)}pp of chain share`,
      detail:
        `${r.category} fell from ${pct(r.share_prior)} to ${pct(r.share_recent)} of chain revenue ` +
        `week-over-week` +
        (grew
          ? ` — it grew in AED (${fmtAed(r.rev_prior)} → ${fmtAed(r.rev_recent)}) but the rest of the chain grew faster.`
          : ` (${fmtAed(r.rev_prior)} → ${fmtAed(r.rev_recent)}).`),
      evidence: {
        rev_recent: Number(r.rev_recent),
        rev_prior: Number(r.rev_prior),
        share_recent: Number(r.share_recent),
        share_prior: Number(r.share_prior),
        shift_pp: shift,
        grew_in_aed: grew,
      },
      entity_type: "category",
      entity_id: r.category,
      entity_name: r.category,
      metric_value: shift, // lower (more negative) = worse
      dedupe_key: `category_share_shift:category:${r.category}:${WEEK}`,
      recommended_action:
        `Review ${r.category}'s space, price and availability — it is losing ground to the rest of the ` +
        `chain even where its own sales hold up.`,
      action_type: "investigate",
    };
  });
}

// --- Rule 12: SKU on the shelf, zero sales in 30 days ----------------------
// Disjoint from `stockout` by construction (this one needs current_stock > 0).
async function zeroSalesSku(tenantId) {
  const rows = await query(
    `SELECT store_id, store_name, item_id, item_name, category,
            current_stock, stock_retail_aed, days_since_last_sale
       FROM metric_zero_sales_sku
      WHERE tenant_id = $1 AND stock_retail_aed > 0
      ORDER BY stock_retail_aed DESC
      LIMIT 25`,
    [tenantId]
  );
  return rows.map((r) => {
    const value = Number(r.stock_retail_aed);
    return {
      rule: "zero_sales_sku",
      category: "inventory",
      severity: value >= 5000 ? "high" : "medium",
      title: `${r.item_name} has not sold in 30 days at ${r.store_name}`,
      detail:
        `${fmtUnits(r.current_stock)} of ${r.item_name} sit at ${r.store_name} with no sale in 30 days ` +
        `— ${fmtAed(value)} of shelf space earning nothing.`,
      evidence: {
        current_stock: Number(r.current_stock),
        stock_retail_aed: value,
        days_since_last_sale:
          r.days_since_last_sale === null ? null : Number(r.days_since_last_sale),
      },
      entity_type: "item",
      entity_id: String(r.item_id),
      entity_name: r.item_name,
      metric_value: value, // higher = worse (more cash stranded)
      dedupe_key: `zero_sales_sku:item:${r.item_id}:${WEEK}`,
      recommended_action:
        `Mark down or delist ${r.item_name} at ${r.store_name}, and give the facing to a SKU that turns.`,
      action_type: "markdown",
    };
  });
}

// All rules, run in order. Add new deterministic rules here.
export const RULES = [
  revenueDropByStore,
  categorySlump,
  returnSpike,
  laggardStore,
  highReturnRateCategory,
  // E3-5 — diagnostic depth 5 -> 12
  stockoutItems,
  deadStockGrowth,
  forecastMiss,
  priceAnomaly,
  supplierLate,
  categoryShareShift,
  zeroSalesSku,
];

export async function runRulesForTenant(tenantId) {
  const findings = [];
  for (const rule of RULES) {
    try {
      findings.push(...(await rule(tenantId)));
    } catch (e) {
      console.error(`[rules] ${rule.name} failed for tenant ${tenantId}:`, e.message);
    }
  }
  return findings;
}
