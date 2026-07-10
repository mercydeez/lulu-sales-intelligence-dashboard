// Unit tests for the outcome-classification logic — pure, no DB. Run with:
//   npm test   (node --test, built in, zero deps)
import { test } from "node:test";
import assert from "node:assert/strict";

import { classifyOutcome, entityKey } from "./outcome.js";

test("rule no longer fires (after = null) → improved (auto-resolve)", () => {
  assert.equal(classifyOutcome("revenue_drop", -0.3, null), "improved");
  assert.equal(classifyOutcome("return_spike", 0.8, null), "improved");
  assert.equal(classifyOutcome("laggard_store", -0.1, undefined), "improved");
});

test("lower-is-worse rules: metric fell further → worsened", () => {
  // revenue_drop / category_slump / laggard_store: more negative = worse
  assert.equal(classifyOutcome("revenue_drop", -0.2, -0.35), "worsened");
  assert.equal(classifyOutcome("category_slump", -0.25, -0.4), "worsened");
  assert.equal(classifyOutcome("laggard_store", -0.05, -0.2), "worsened");
});

test("lower-is-worse rules: metric recovered toward healthy but still firing → unchanged", () => {
  assert.equal(classifyOutcome("revenue_drop", -0.35, -0.2), "unchanged");
  assert.equal(classifyOutcome("laggard_store", -0.2, -0.05), "unchanged");
});

test("higher-is-worse rules: return metrics rose → worsened, fell → unchanged", () => {
  assert.equal(classifyOutcome("return_spike", 0.5, 0.9), "worsened");
  assert.equal(classifyOutcome("high_return_rate", 0.08, 0.15), "worsened");
  assert.equal(classifyOutcome("return_spike", 0.9, 0.5), "unchanged");
});

test("missing before metric defaults to unchanged when still firing", () => {
  assert.equal(classifyOutcome("revenue_drop", null, -0.3), "unchanged");
});

test("entityKey ignores the ISO-week stamp and normalizes global findings", () => {
  assert.equal(entityKey("revenue_drop", "store", "5"), "revenue_drop:store:5");
  assert.equal(entityKey("return_spike", "global", null), "return_spike:global:all");
  assert.equal(entityKey("return_spike", null, null), "return_spike:global:all");
});

// --- E3-5 rules 6-12: each rule's direction is pinned ----------------------
//
// Getting a rule's side of HIGHER_IS_WORSE wrong INVERTS its outcome — a supplier
// going from 3 days late to 14 would be reported as "improved" and the finding
// auto-closed. These lock every new rule's direction.

test("E3-5 higher-is-worse rules: a rising metric means worsened", () => {
  // A faster-selling item stuck out of stock costs more each day.
  assert.equal(classifyOutcome("stockout", 5, 20), "worsened");
  // More dead SKUs than before.
  assert.equal(classifyOutcome("dead_stock_growth", 0.2, 0.6), "worsened");
  // The forecast error grew.
  assert.equal(classifyOutcome("forecast_miss", 0.31, 0.55), "worsened");
  // The supplier slipped from 3 days late to 14.
  assert.equal(classifyOutcome("supplier_late", 3, 14), "worsened");
  // More cash stranded on the shelf.
  assert.equal(classifyOutcome("zero_sales_sku", 1200, 8000), "worsened");
});

test("E3-5 higher-is-worse rules: a falling metric means recovering, not worse", () => {
  assert.equal(classifyOutcome("supplier_late", 14, 3), "unchanged");
  assert.equal(classifyOutcome("forecast_miss", 0.55, 0.31), "unchanged");
  assert.equal(classifyOutcome("stockout", 20, 5), "unchanged");
});

test("E3-5 lower-is-worse rules: margin ratio and share shift", () => {
  // Margin ratio sliding toward (and below) zero is worse.
  assert.equal(classifyOutcome("price_anomaly", 0.04, -0.02), "worsened");
  assert.equal(classifyOutcome("price_anomaly", -0.02, 0.04), "unchanged");
  // Share shift is in percentage POINTS; more negative is worse.
  assert.equal(classifyOutcome("category_share_shift", -1.6, -4.2), "worsened");
  assert.equal(classifyOutcome("category_share_shift", -4.2, -1.6), "unchanged");
});

test("E3-5 rules auto-resolve when they stop firing", () => {
  for (const rule of [
    "stockout", "dead_stock_growth", "forecast_miss",
    "price_anomaly", "supplier_late", "category_share_shift", "zero_sales_sku",
  ]) {
    assert.equal(classifyOutcome(rule, 1, null), "improved", `${rule} should auto-resolve`);
  }
});

test("E3-5 entity keys are stable across weeks (the measure loop matches on them)", () => {
  assert.equal(entityKey("supplier_late", "supplier", "3"), "supplier_late:supplier:3");
  assert.equal(entityKey("dead_stock_growth", "global", null), "dead_stock_growth:global:all");
  assert.equal(entityKey("category_share_shift", "category", "Dairy"), "category_share_shift:category:Dairy");
});
