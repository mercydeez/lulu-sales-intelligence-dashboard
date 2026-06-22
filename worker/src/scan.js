// One diagnostics pass: run every rule for every tenant, upsert the findings, and
// dispatch notifications for any NEWLY-created high/critical findings.
import { listTenantIds } from "./db.js";
import { runRulesForTenant } from "./rules.js";
import { writeFindings } from "./findings.js";
import { dispatch } from "./notify.js";

export async function runScan() {
  const started = Date.now();
  const tenants = await listTenantIds();
  let total = 0;
  let notified = 0;
  for (const tenantId of tenants) {
    const findings = await runRulesForTenant(tenantId);
    const inserted = await writeFindings(tenantId, findings);
    total += inserted.length;
    for (const f of inserted) {
      if (await dispatch(tenantId, f)) notified += 1;
    }
  }
  const ms = Date.now() - started;
  console.log(
    `[scan] ${total} new finding(s) across ${tenants.length} tenant(s), ${notified} notified, in ${ms}ms`
  );
  return { tenants: tenants.length, findings: total, notified, ms };
}
