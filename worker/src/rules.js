// Deterministic, explainable diagnostic rules (A3). Each rule compares a recent
// 7-day window to the prior 7 days and emits findings with the evidence numbers
// and a human sentence. No ML, no hidden heuristics — everything is derivable.
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
async function revenueDropByStore(tenantId) {
  const rows = await query(
    `WITH w AS (
       SELECT s.store_id, st.name AS store_name,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '14 days'
                     AND s.date < CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
       FROM sales_fact_view s
       JOIN items i  ON i.id = s.item_id  AND i.tenant_id  = s.tenant_id
       JOIN stores st ON st.id = s.store_id AND st.tenant_id = s.tenant_id
       WHERE s.tenant_id = $1
       GROUP BY s.store_id, st.name
     )
     SELECT *, (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS change
     FROM w WHERE rev_prior > 0 AND (rev_recent - rev_prior) / rev_prior <= -0.15`,
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
    };
  });
}

// --- Rule: per-category revenue slump --------------------------------------
async function categorySlump(tenantId) {
  const rows = await query(
    `WITH w AS (
       SELECT i.category,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '14 days'
                     AND s.date < CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
       FROM sales_fact_view s
       JOIN items i ON i.id = s.item_id AND i.tenant_id = s.tenant_id
       WHERE s.tenant_id = $1
       GROUP BY i.category
     )
     SELECT *, (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS change
     FROM w WHERE rev_prior > 0 AND (rev_recent - rev_prior) / rev_prior <= -0.2`,
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
    };
  });
}

// --- Rule: returns spike (tenant-wide) -------------------------------------
async function returnSpike(tenantId) {
  const rows = await query(
    `SELECT
       COALESCE(SUM(ABS(s.sales)) FILTER (
         WHERE s.sales < 0 AND s.date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS ret_recent,
       COALESCE(SUM(ABS(s.sales)) FILTER (
         WHERE s.sales < 0 AND s.date >= CURRENT_DATE - INTERVAL '14 days'
               AND s.date < CURRENT_DATE - INTERVAL '7 days'), 0) AS ret_prior
     FROM sales_fact_view s
     WHERE s.tenant_id = $1`,
    [tenantId]
  );
  const r = rows[0];
  const recent = Number(r.ret_recent);
  const prior = Number(r.ret_prior);
  if (prior <= 0 || recent < 50) return []; // floor: ignore noise on tiny volumes
  const change = (recent - prior) / prior;
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
    },
  ];
}

// --- Rule: laggard store (growing materially slower than the chain) --------
// Relative underperformance — fires even when every store is up, surfacing the
// store that's leaving money on the table vs its peers.
async function laggardStore(tenantId) {
  const rows = await query(
    `WITH w AS (
       SELECT st.id AS store_id, st.name AS store_name,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
         COALESCE(SUM(s.sales * i.unit_price_aed)
           FILTER (WHERE s.date >= CURRENT_DATE - INTERVAL '14 days'
                     AND s.date < CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
       FROM sales_fact_view s
       JOIN items i  ON i.id = s.item_id  AND i.tenant_id  = s.tenant_id
       JOIN stores st ON st.id = s.store_id AND st.tenant_id = s.tenant_id
       WHERE s.tenant_id = $1
       GROUP BY st.id, st.name
     ), g AS (
       SELECT store_id, store_name, (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS growth
       FROM w WHERE rev_prior > 0
     ), avg AS (SELECT AVG(growth) AS chain_growth FROM g)
     SELECT g.store_id, g.store_name, g.growth, avg.chain_growth
     FROM g, avg
     WHERE g.growth < avg.chain_growth - 0.05   -- >=5pp below the chain
     ORDER BY g.growth ASC LIMIT 3`,
    [tenantId]
  );
  return rows.map((r) => {
    const gap = Number(r.chain_growth) - Number(r.growth);
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
    };
  });
}

// --- Rule: high return rate by category ------------------------------------
// Returns as a share of gross units, flagged when well above the tenant average.
async function highReturnRateCategory(tenantId) {
  const rows = await query(
    `WITH c AS (
       SELECT i.category,
         SUM(CASE WHEN s.sales > 0 THEN s.sales ELSE 0 END) AS gross_units,
         SUM(CASE WHEN s.sales < 0 THEN -s.sales ELSE 0 END) AS return_units
       FROM sales_fact_view s
       JOIN items i ON i.id = s.item_id AND i.tenant_id = s.tenant_id
       WHERE s.tenant_id = $1 AND s.date >= CURRENT_DATE - INTERVAL '30 days'
       GROUP BY i.category
     ), r AS (
       SELECT category, gross_units, return_units,
         return_units::numeric / NULLIF(gross_units, 0) AS rate
       FROM c WHERE gross_units > 0
     ), avg AS (SELECT AVG(rate) AS mean_rate FROM r)
     SELECT r.category, r.rate, r.return_units, r.gross_units, avg.mean_rate
     FROM r, avg
     WHERE r.rate > GREATEST(avg.mean_rate * 1.5, 0.05)
     ORDER BY r.rate DESC LIMIT 3`,
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
