# Pilot Deployment (first real tenant)

A pilot is the first deployment with a **real customer tenant**. It uses the full
production topology (no demo behavior) and the strictest config.

## Differences from the demo

| Aspect | Demo (Render) | Pilot |
|--------|---------------|-------|
| `DEMO_MODE` | true | **false** |
| Synthetic generator | running | **off** |
| Synthetic seed | on startup | **not run** |
| Migrations | on startup | dedicated `migrate` job |
| RLS | app-layer only | **`USE_RLS_ROLE=true` + `app_rw` password** |
| Demo users | seeded, login disabled | removed/rotated |
| Data shown | synthetic | the tenant's real data (or empty until loaded) |

## Data for the pilot

Self-serve CSV/Excel import and the public ingestion API are **deferred** (see
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)). Until they ship, a pilot tenant's
data is loaded by an operator (controlled SQL/COPY into the tenant-scoped tables)
or the tenant runs on an empty dataset. **Be explicit with the customer** that the
dashboard shows their real loaded data, derived AED revenue (computed from units ×
unit price — not POS-captured), and that there is no live POS integration. See
[`../product/DEMO_VS_REAL_DATA.md`](../product/DEMO_VS_REAL_DATA.md).

## Steps

1. Follow [`DEPLOYMENT.md`](DEPLOYMENT.md) with `.env.production` set for a real
   tenant: `DEMO_MODE=false`, RLS on, demo users removed, docs off.
2. Run the `migrate` job; verify `/health/ready` and `/health/deep`.
3. Provision the pilot tenant (tenant row + owner/admin user + invite — Phase 5).
4. Load the tenant's data (operator-assisted) into tenant-scoped tables.
5. Confirm isolation: a second test tenant cannot see the pilot's data
   (tenant-isolation tests — Phase 6/11).
6. Configure backups + alerts ([`BACKUP_RESTORE.md`](BACKUP_RESTORE.md),
   [`OBSERVABILITY.md`](OBSERVABILITY.md)).

## Pilot limits
Document agreed limits up front: pilot scale (rows/tenants tested), no POS
integration, manual data load, deferred self-serve import, and the support/SLA
terms ([`../support/SUPPORT_PLAYBOOK.md`](../support/SUPPORT_PLAYBOOK.md) — Phase 12).
