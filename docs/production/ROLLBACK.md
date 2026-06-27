# Rollback

How to undo a bad release. Prefer the cheapest reversible lever first.

## Decision order

1. **Feature flag** — if the regression is behind a flag, flip it (no redeploy).
2. **Image rollback** — redeploy the previous known-good image/tag.
3. **Migration reversal** — only if a migration is the cause (rare).
4. **Restore from backup** — last resort; loses data written since the backup.

## 1. Feature-flag rollback

Many risky behaviors are flagged (see [`ENVIRONMENT.md`](ENVIRONMENT.md)). Examples:
- Disable the synthetic generator: `DEMO_MODE=false` / `LIVE_GENERATOR_ENABLED=false` (then restart the generator process / API).
- Disable external AI: `ENABLE_EXTERNAL_AI=false`.
- Disable connector testing: `ENABLE_DATA_SOURCE_CONNECTORS=false`.
- Disable signup: `ENABLE_SIGNUP=false`.
Flag changes are config-only and reversible in seconds.

## 2. Image rollback

```bash
# compose: pin to the previous tag and redeploy backend/frontend/worker
docker compose -f docker-compose.production.yml --env-file .env.production up -d \
  --no-deps backend frontend worker
```
Because the API no longer runs migrations, rolling the image back does **not** roll
back the schema. A forward-only additive migration (the norm here) is compatible
with the previous image, so image rollback is usually safe on its own.

## 3. Migration reversal

Migrations are forward-only (see [`MIGRATIONS.md`](MIGRATIONS.md)). To reverse:
- **Preferred:** write a new compensating forward migration (`0NN_revert_x.sql`)
  and run the `migrate` job. Additive changes (new nullable columns/tables) usually
  need no reversal.
- **If a migration corrupted data:** restore from the pre-release backup (step 4).

See [`../runbooks/FAILED_MIGRATION.md`](../runbooks/FAILED_MIGRATION.md).

## 4. Restore from backup

Destructive and lossy. Follow
[`../runbooks/RESTORE_FROM_BACKUP.md`](../runbooks/RESTORE_FROM_BACKUP.md). Always
take a fresh backup of the current (broken) state first for forensics.

## Always
- Take a backup **before** every release/migration so steps 3–4 are possible.
- After any rollback, verify `/health/ready` and `/health/deep`, then record the
  incident.
