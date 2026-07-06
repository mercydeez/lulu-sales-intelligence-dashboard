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
