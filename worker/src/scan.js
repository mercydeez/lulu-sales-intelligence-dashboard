// One diagnostics pass: run every rule for every tenant and upsert the findings.
import { listTenantIds } from "./db.js";
import { runRulesForTenant } from "./rules.js";
import { writeFindings } from "./findings.js";

export async function runScan() {
  const started = Date.now();
  const tenants = await listTenantIds();
  let total = 0;
  for (const tenantId of tenants) {
    const findings = await runRulesForTenant(tenantId);
    total += await writeFindings(tenantId, findings);
  }
  const ms = Date.now() - started;
  console.log(`[scan] ${total} finding(s) across ${tenants.length} tenant(s) in ${ms}ms`);
  return { tenants: tenants.length, findings: total, ms };
}
