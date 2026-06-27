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
