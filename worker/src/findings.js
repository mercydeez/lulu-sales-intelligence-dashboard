// Upsert findings by (tenant_id, dedupe_key). Re-running a scan in the same window
// refreshes the evidence/severity/detail rather than duplicating; a resolved finding
// is left resolved (operators' decisions stick) unless its window rolls over.
import { query } from "./db.js";

// Returns true if this finding row was newly INSERTED (vs an update of an existing
// one) — `xmax = 0` is Postgres's tell for an insert in an upsert RETURNING. Also
// sets `f.id` from the row so callers (notifications) can deep-link the finding.
//
// metric_before is SNAPSHOT at first insert (= metric_value then) and deliberately
// LEFT UNTOUCHED on every subsequent same-window scan, so the outcome loop's
// "before" baseline is frozen at detection rather than drifting to the latest scan.
export async function upsertFinding(tenantId, f) {
  const rows = await query(
    `INSERT INTO findings
       (tenant_id, rule, category, severity, title, detail, evidence,
        entity_type, entity_id, entity_name, metric_value, metric_before, dedupe_key,
        recommended_action, action_type, status, updated_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$11,$12,$13,$14,'open', now())
     ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET
       severity           = EXCLUDED.severity,
       title              = EXCLUDED.title,
       detail             = EXCLUDED.detail,
       evidence           = EXCLUDED.evidence,
       metric_value       = EXCLUDED.metric_value,
       recommended_action = EXCLUDED.recommended_action,
       action_type        = EXCLUDED.action_type,
       -- If the rule fires again after the MEASURE loop auto-resolved it, the
       -- problem recurred — reopen it so it resurfaces and gets re-measured.
       -- Scope strictly to system auto-resolves (resolved_by='system:measure'):
       -- a human's resolve/dismiss shares status='resolved' and MUST stick.
       status         = CASE WHEN findings.status = 'resolved' AND findings.resolved_by = 'system:measure'
                             THEN 'open' ELSE findings.status END,
       resolved_at    = CASE WHEN findings.status = 'resolved' AND findings.resolved_by = 'system:measure'
                             THEN NULL  ELSE findings.resolved_at END,
       resolved_by    = CASE WHEN findings.status = 'resolved' AND findings.resolved_by = 'system:measure'
                             THEN NULL  ELSE findings.resolved_by END,
       outcome_status = CASE WHEN findings.status = 'resolved' AND findings.resolved_by = 'system:measure'
                             THEN NULL  ELSE findings.outcome_status END,
       updated_at         = now()
     RETURNING id, (xmax = 0) AS inserted`,
    [
      tenantId, f.rule, f.category, f.severity, f.title, f.detail,
      JSON.stringify(f.evidence ?? {}), f.entity_type ?? null, f.entity_id ?? null,
      f.entity_name ?? null, f.metric_value ?? null, f.dedupe_key,
      f.recommended_action ?? null, f.action_type ?? "investigate",
    ]
  );
  if (rows[0]?.id !== undefined) f.id = rows[0].id;
  return rows[0]?.inserted === true;
}

export async function writeFindings(tenantId, findings) {
  const inserted = [];
  for (const f of findings) {
    if (await upsertFinding(tenantId, f)) inserted.push(f);
  }
  return inserted; // newly-created findings (for notifications)
}
