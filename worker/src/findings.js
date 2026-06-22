// Upsert findings by (tenant_id, dedupe_key). Re-running a scan in the same window
// refreshes the evidence/severity/detail rather than duplicating; a resolved finding
// is left resolved (operators' decisions stick) unless its window rolls over.
import { query } from "./db.js";

export async function upsertFinding(tenantId, f) {
  await query(
    `INSERT INTO findings
       (tenant_id, rule, category, severity, title, detail, evidence,
        entity_type, entity_id, entity_name, metric_value, dedupe_key, status, updated_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'open', now())
     ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET
       severity     = EXCLUDED.severity,
       title        = EXCLUDED.title,
       detail       = EXCLUDED.detail,
       evidence     = EXCLUDED.evidence,
       metric_value = EXCLUDED.metric_value,
       updated_at   = now()`,
    [
      tenantId, f.rule, f.category, f.severity, f.title, f.detail,
      JSON.stringify(f.evidence ?? {}), f.entity_type ?? null, f.entity_id ?? null,
      f.entity_name ?? null, f.metric_value ?? null, f.dedupe_key,
    ]
  );
}

export async function writeFindings(tenantId, findings) {
  for (const f of findings) await upsertFinding(tenantId, f);
  return findings.length;
}
