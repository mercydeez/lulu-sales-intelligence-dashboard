# Runbook — UAE data residency & region hosting (E5-3)

**Owner:** Krishna (Platform, Data & Services)
**Status:** buildable slice shipped (config guardrail + posture API + this runbook);
cloud region provisioning is an operator action performed at deploy time.

Retail IQ can be deployed so that **all tenant data stays inside the UAE**. This is a
hard requirement for B2G (government) tenants and a selling point for enterprise tenants
under the UAE Personal Data Protection Law (PDPL, Federal Decree-Law No. 45 of 2021).
This runbook is the single source of truth for how residency is configured, enforced,
verified, and evidenced.

---

## 1. What "data residency" means here

Every place tenant data can physically come to rest or be processed:

| Component | Where it lives | Controlled by |
|---|---|---|
| Primary database (Postgres) | The cloud region you deploy into | `DATABASE_URL` host + region choice |
| Cache / streams / blacklist (Redis) | Same region as the app | `REDIS_URL` host |
| Object-storage backups | `BACKUP_REGION` (default = `AWS_DEFAULT_REGION`) | `docker-compose.production.yml` backup service |
| Application & audit logs | The host running the containers | `LOG_RETENTION_DAYS` (retention policy) |
| External AI (optional) | A third-party LLM, possibly out-of-region | `ENABLE_EXTERNAL_AI` (**off** for strict residency) |

The declared region is a single value, `DATA_REGION`, plus `BACKUP_REGION` for the
offsite copy. The app does **not** geolocate hosts for you — it enforces that the
region you *declare* is an approved UAE region and reports that posture honestly.

## 2. Approved regions

Deploy the primary DB, Redis, app, and backups into one of:

- **AWS `me-central-1`** (UAE, Middle East — recommended), or
- **Azure `uae-north`** (Dubai) / `uae-central` (Abu Dhabi).

`APPROVED_DATA_REGIONS` is a comma-separated allow-list of region *tokens* matched as
case-insensitive substrings, so `me-central-1` matches the token `me-central`, and
`uae-north-1` matches `uae-north`. Default:

```
APPROVED_DATA_REGIONS=me-central-1,me-central,uae-north,uae-central,uae,ae
```

## 3. Configuration (production)

Set these in `.env.production` (see `.env.production.example`):

```bash
DATA_REGION=me-central-1            # the region you actually deployed into
DATA_RESIDENCY_REQUIRED=true        # turn the boot guardrail ON
BACKUP_REGION=me-central-1          # offsite bucket region (keep in-country)
CROSS_BORDER_TRANSFER_ALLOWED=false # no egress out of region
LOG_RETENTION_DAYS=30
DATA_RESIDENCY_STATEMENT_ENABLED=true
ENABLE_EXTERNAL_AI=false            # keep third-party LLMs off under strict residency
```

Also point the backup sidecar's `AWS_DEFAULT_REGION` (and the S3 bucket) at the same
region — `BACKUP_REGION` defaults to it in `docker-compose.production.yml`.

## 4. The boot guardrail (enforcement)

When `DATA_RESIDENCY_REQUIRED=true`, `app/config.py::validate_security()` runs at
startup and, in `production`/`staging`:

- **Raises `RuntimeError` (refuses to boot)** if `DATA_REGION` is empty or not in
  `APPROVED_DATA_REGIONS`, **or** if `BACKUP_REGION` is set but outside the approved
  set. Both are hard residency violations (serving or backing up data from the wrong
  country), so the deploy fails closed instead of silently breaching residency.
- **Warns** (logs, does not block) if `CROSS_BORDER_TRANSFER_ALLOWED=true` or if
  `ENABLE_EXTERNAL_AI=true` — each is a residency risk the operator has explicitly
  opted into, surfaced in the posture rather than blocking boot.

In `development` the same conditions surface as warnings only, so local work is never
blocked.

## 5. The residency posture (verification & transparency)

Two read-only, secret-free surfaces report exactly what is configured — never an
unbacked compliance claim:

- **Public:** `GET /api/monitoring/residency` — for a `/trust`-style page. Returns
  `status`, `region`, `region_approved`, `backup_region`, `backup_in_region`,
  `cross_border_transfer_allowed`, `external_ai_may_leave_region`, `log_retention_days`,
  and a human-readable `statement`. Returns **404** when
  `DATA_RESIDENCY_STATEMENT_ENABLED=false`. Region ids + booleans only — no hosts,
  secrets, or connection strings.
- **Ops:** `GET /health/deep` → `checks.data_residency` — the same posture folded into
  the deep health check as **informational**. It never flips readiness (aggregate
  status only weighs database/redis/migrations/worker), so a residency warning won't
  page you as an outage but is visible to monitoring.

`status` values: `undeclared` (no region set), `in_region` (declared & approved),
`out_of_region` (declared, not approved, not required), `non_compliant` (required but
region not approved — the guardrail would have blocked boot).

### Verify after deploy

```bash
# 1. The app booted (guardrail passed).
curl -fsS https://api.yourdomain.com/health/ready

# 2. Posture is in-region.
curl -fsS https://api.yourdomain.com/api/monitoring/residency | jq '{status, region, region_approved, backup_in_region}'
# expect: {"status":"in_region","region":"me-central-1","region_approved":true,"backup_in_region":true}

# 3. Deep health shows the residency check ok.
curl -fsS https://api.yourdomain.com/health/deep | jq '.checks.data_residency'
```

## 6. Cross-border transfer policy

Under strict residency, **no tenant data leaves the UAE region**. Keep
`CROSS_BORDER_TRANSFER_ALLOWED=false`. If a specific integration genuinely requires
egress (e.g. an out-of-region analytics vendor), that is a contractual decision:
document the legal basis (PDPL Art. 22–23 cross-border conditions), set the flag true
**only** for that deployment, and note that the posture will surface the risk. External
AI is the most common leak path — leaving `ENABLE_EXTERNAL_AI=false` keeps prompts from
being sent to an out-of-region LLM.

## 7. Backups in-region

The `backup` sidecar (E0-1) writes nightly dumps. For residency:

- Set the offsite bucket (`BACKUP_S3_URL`) to a bucket **in the UAE region** and
  `BACKUP_REGION` / `AWS_DEFAULT_REGION` to that region.
- The restore drill (`docs/runbooks/BACKUP_AND_RESTORE.md`) must restore **into the
  same region** — never pull a UAE tenant's dump into an out-of-region host, even
  temporarily.

## 8. Log retention

`LOG_RETENTION_DAYS` (default 30) documents how long application/audit logs are kept.
Logs may contain personal data; retain them in-region and purge on schedule. Wire the
value into your log platform's retention policy — the app declares the number; the
platform enforces deletion.

## 9. Data subject rights (export / delete)

PDPL grants data-subject access and erasure. Those flows are documented separately in
`docs/runbooks/DATA_EXPORT_AND_DELETE.md` (backed by `/api/data-rights` and
`services/data_rights_service.py`). Residency and data-rights together form the PDPL
operational story.

## 10. Compliance evidence checklist (B2G acceptance)

Collect and file the following as acceptance evidence:

- [ ] Cloud region confirmed = `me-central-1` / `uae-north` (console screenshot of DB,
      Redis, app, and backup bucket regions).
- [ ] `DATA_RESIDENCY_REQUIRED=true` in the deployed `.env.production` (redacted copy).
- [ ] Boot log shows no residency `CRITICAL`/`WARNING` from `validate_security`.
- [ ] `GET /api/monitoring/residency` returns `status: in_region`, `region_approved:
      true`, `backup_in_region: true` (captured output).
- [ ] `GET /health/deep` `checks.data_residency.status == "ok"`.
- [ ] `CROSS_BORDER_TRANSFER_ALLOWED=false` and `ENABLE_EXTERNAL_AI=false` (or a signed
      exception on file).
- [ ] Backup bucket region = data region; restore drill executed in-region (link to
      the last `drill-restore` CI run / runbook entry).
- [ ] Log retention policy set to `LOG_RETENTION_DAYS` in the log platform.
- [ ] Data export/delete runbook (`DATA_EXPORT_AND_DELETE.md`) rehearsed once.
- [ ] Public residency statement reviewed by legal before it is linked from `/trust`.

## 11. Rollback / relaxing the requirement

Residency is config-only — no migration, no schema change. To relax it (e.g. a non-UAE
demo tenant), set `DATA_RESIDENCY_REQUIRED=false` and redeploy; the guardrail becomes
advisory and the posture reports the declared region honestly. To fully hide the public
statement, set `DATA_RESIDENCY_STATEMENT_ENABLED=false` (the endpoint 404s). No data is
migrated or destroyed by any residency setting.

## 12. Related

- `docs/production/ENVIRONMENT.md` — the residency env-var table.
- `docs/runbooks/BACKUP_AND_RESTORE.md` — in-region backup/restore.
- `docs/runbooks/DATA_EXPORT_AND_DELETE.md` — PDPL data-subject rights.
- `app/config.py::validate_security` — the boot guardrail.
- `app/services/data_residency.py` — posture + validation helpers (pure, no secrets).
