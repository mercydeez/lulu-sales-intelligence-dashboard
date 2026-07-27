# Runbook: Import Failures

> **Note:** self-serve CSV/Excel import is **deferred** (see
> [../production/KNOWN_LIMITATIONS.md](../production/KNOWN_LIMITATIONS.md)). Until it
> ships, pilot data is loaded by an operator. This runbook covers operator-assisted
> loads now, and the import pipeline once it ships.

**Symptom:** `import_failures` metric rising; a tenant reports their data didn't load.

## Operator-assisted load (current)
- Verify rows were loaded into the **tenant-scoped** tables with the correct
  `tenant_id` (a mis-scoped load is a data-isolation incident →
  [SUSPECTED_DATA_LEAK](SUSPECTED_DATA_LEAK.md)).
- Confirm units vs AED: quantities are **units**; AED is derived from a price table.
  Do not load AED as units (see [../product/DEMO_VS_REAL_DATA.md](../product/DEMO_VS_REAL_DATA.md)).
- Re-run inside a transaction; verify counts and `/health/deep` freshness.

## Import pipeline (when shipped)
- Check the import job's state/errors report; fix the source rows; re-run.
- Commits are idempotent + tenant-scoped — a retry must not duplicate rows.

## After
Confirm the dashboard reflects the load for that tenant only; never present loaded
data as more than it is.
