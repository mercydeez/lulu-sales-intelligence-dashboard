// Pure outcome-classification logic for the measure loop — no DB, no side effects,
// so it's unit-testable in isolation (see measure.test.js). measure.js wires this to
// the rules + Postgres.

// A finding is identified for measurement by (rule, entity) — independent of the
// ISO-week stamp baked into dedupe_key, so a finding accepted last week is matched
// to this week's re-evaluation of the same store/category/global entity.
export function entityKey(rule, entityType, entityId) {
  return `${rule}:${entityType ?? "global"}:${entityId ?? "all"}`;
}

// Rules whose metric is "higher = worse" (returns / return-rate spikes, and the
// E3-5 rules whose metric_value counts damage upward). The rest — revenue drop,
// category slump, laggard growth, category share shift, price margin ratio — are
// "lower = worse". Used only to decide unchanged vs worsened while a finding is
// STILL firing.
//
// Getting a rule's side wrong INVERTS its outcome: a supplier going from 3 days
// late to 14 would be reported as "improved". Every new rule must be classified
// here deliberately, and measure.test.js pins each one.
const HIGHER_IS_WORSE = new Set([
  "return_spike",
  "high_return_rate",
  // E3-5:
  "stockout",            // faster-selling item out of stock = worse
  "dead_stock_growth",   // growth ratio climbing = worse
  "forecast_miss",       // WAPE climbing = worse
  "supplier_late",       // more days overdue = worse
  "zero_sales_sku",      // more AED stranded on the shelf = worse
  // NOT here (lower = worse): price_anomaly (margin ratio; negative is worst),
  // category_share_shift (percentage points; more negative is worst).
]);

// Given the at-detection metric (`before`) and the current metric (`after`, or null
// when the rule no longer fires), classify the outcome:
//   improved  — rule no longer fires (problem cleared) → caller auto-resolves
//   worsened  — still firing and the metric moved the wrong way
//   unchanged — still firing, flat or recovering but not yet cleared
export function classifyOutcome(rule, before, after) {
  if (after === null || after === undefined) return "improved";
  if (before === null || before === undefined) return "unchanged";
  const worse = HIGHER_IS_WORSE.has(rule) ? after > before : after < before;
  return worse ? "worsened" : "unchanged";
}
