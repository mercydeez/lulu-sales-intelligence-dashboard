// Measure / outcome pass — closes the loop (detect → … → accept → MEASURE).
//
// For every finding an operator ACCEPTED (action_accepted_at set) that isn't yet
// resolved, we re-run the SAME deterministic rules over the CURRENT window and ask:
// does this rule still fire for this entity?
//   - no longer fires  → the problem cleared → outcome `improved` → AUTO-RESOLVE.
//   - still fires       → compare the current metric to the at-detection metric:
//                          moved the wrong way → `worsened`, else `unchanged`.
// This reuses the rule outputs as the source of truth — no new metric math, so the
// "after" number is always the rule's own metric, on the same footing as detection.
import { listTenantIds, query } from "./db.js";
import { runRulesForTenantTracked } from "./rules.js";
import { measureDecision, entityKey } from "./outcome.js";

// Accepted findings still awaiting (or due for re-)measurement for one tenant.
async function acceptedOpen(tenantId) {
  return query(
    `SELECT id, rule, entity_type, entity_id, metric_value, metric_before
       FROM findings
      WHERE tenant_id = $1
        AND action_accepted_at IS NOT NULL
        AND status <> 'resolved'`,
    [tenantId]
  );
}

async function recordOutcome(tenantId, id, outcome, before, after) {
  const resolve = outcome === "improved";
  await query(
    `UPDATE findings SET
       outcome_status = $3,
       metric_before  = COALESCE(metric_before, $4),   -- capture the detection metric once
       metric_after   = $5,
       measured_at    = now(),
       status         = CASE WHEN $6 THEN 'resolved'        ELSE status      END,
       resolved_at    = CASE WHEN $6 THEN now()             ELSE resolved_at END,
       resolved_by    = CASE WHEN $6 THEN 'system:measure'  ELSE resolved_by END,
       updated_at     = now()
     WHERE id = $1 AND tenant_id = $2`,
    [id, tenantId, outcome, before, after, resolve]
  );
}

export async function runMeasure() {
  const started = Date.now();
  const tenants = await listTenantIds();
  let measured = 0;
  let resolved = 0;
  for (const tenantId of tenants) {
    const pending = await acceptedOpen(tenantId);
    if (pending.length === 0) continue;
    // Re-evaluate the rules once for the tenant; the current findings are the "after".
    // allClean=false means a rule threw — we must not read a missing entity as a
    // recovery (that would falsely auto-resolve a still-active problem).
    const { findings: current, allClean } = await runRulesForTenantTracked(tenantId);
    const firing = new Map();
    for (const f of current) firing.set(entityKey(f.rule, f.entity_type, f.entity_id), f);

    for (const f of pending) {
      const before =
        f.metric_before !== null && f.metric_before !== undefined
          ? Number(f.metric_before)
          : f.metric_value !== null && f.metric_value !== undefined
          ? Number(f.metric_value)
          : null;
      const now = firing.get(entityKey(f.rule, f.entity_type, f.entity_id));
      const after = now && now.metric_value != null ? Number(now.metric_value) : null;
      const outcome = measureDecision(f.rule, before, after, allClean);
      if (outcome === "defer") continue;  // re-measure next (clean) cycle
      await recordOutcome(tenantId, f.id, outcome, before, after);
      measured += 1;
      if (outcome === "improved") resolved += 1;
    }
  }
  const ms = Date.now() - started;
  console.log(
    `[measure] ${measured} accepted finding(s) measured, ${resolved} auto-resolved, ` +
      `across ${tenants.length} tenant(s), in ${ms}ms`
  );
  return { tenants: tenants.length, measured, resolved, ms };
}
