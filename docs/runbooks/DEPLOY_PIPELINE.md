# Runbook — Deploy Pipeline (E0-3)

Automated deploys via `.github/workflows/deploy.yml`, gated by smoke tests.
Provider-neutral: deploy over a **webhook** or over **SSH + docker compose**.

## 1. What the workflow does

| Trigger | Job | Result |
|---|---|---|
| Push to `main` | `deploy-staging` | Deploy staging, then smoke-test |
| Push tag `vX.Y.Z` | `deploy-production` | Deploy the exact tag to production, then smoke-test |
| `workflow_dispatch` (staging) | `deploy-staging` | Manual staging deploy of a chosen ref |
| `workflow_dispatch` (production) | `deploy-production` | Manual production deploy of a chosen tag/ref (rollback path) |

Every run first executes `validate-deploy-config` (no secrets): shell-syntax checks,
`scripts/validate-production-compose.sh`, a deploy-script dry-run, and workflow-YAML
parsing. Deploy jobs `need` it, so a bad compose/script blocks all deploys.

**Smoke gates the deploy:** after deploying, `scripts/smoke-deploy.sh` hits
`/health/live`, `/health/ready`, `/health/deep` and fails the job on any non-2xx,
a missing subsystem check, a missing worker heartbeat, or a leaked secret.

## 2. Required GitHub environments
Create two environments (Settings → Environments): **`staging`** and **`production`**.
Add reviewers/approval rules to `production` for a manual gate before prod deploys.

## 3. Required secrets (per environment)
Pick **one** mode per environment — webhook OR SSH.

**Webhook mode**
- Staging: `STAGING_DEPLOY_WEBHOOK_URL`, `STAGING_BASE_URL`
- Production: `PRODUCTION_DEPLOY_WEBHOOK_URL`, `PRODUCTION_BASE_URL`

**SSH mode**
- Staging: `STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_SSH_KEY`, `STAGING_APP_DIR`, `STAGING_BASE_URL`
- Production: `PRODUCTION_SSH_HOST`, `PRODUCTION_SSH_USER`, `PRODUCTION_SSH_KEY`, `PRODUCTION_APP_DIR`, `PRODUCTION_BASE_URL`

`*_BASE_URL` is always required (the smoke target). If a deploy job runs without a
configured mode or `BASE_URL`, it **fails clearly** rather than silently no-op.

## 4. Fresh host prerequisites (SSH mode)
- Docker Engine + Docker Compose plugin
- Git, with the repo checked out at `DEPLOY_APP_DIR`
- `.env.production` present (from `.env.production.example`, real secrets filled)
- DNS / TLS / nginx configured (see `DEPLOY.md`, `docs/production/DEPLOYMENT.md`)
- First run creates the DB from `database/prod-init.sql` (schema only) → `migrate`
  applies `database/migrations/*` → backend + worker start. **No demo data.**
- Provision the first admin user out-of-band (no demo users are seeded in production).

## 5. Staging deploy
Merge/push to `main` → `deploy-staging` runs automatically → smoke-test on
`STAGING_BASE_URL`. Or run the workflow manually with environment `staging`.

## 6. Production deploy
Tag a release and push it:
```bash
git tag v1.2.3 && git push origin v1.2.3
```
`deploy-production` deploys the exact tag, then smoke-tests `PRODUCTION_BASE_URL`.
(With an approval rule on the `production` environment, it waits for sign-off first.)

## 7. Rollback
Rollback = **redeploy a previous known-good tag** (no special tooling):
1. Run the **Deploy** workflow via *Run workflow* → environment `production`,
   `ref = v1.2.2` (the last good tag). SSH mode checks out that tag and
   `docker compose up -d --build`; webhook mode posts that ref.
2. Alternatively push the old tag through the pipeline again.
3. Verify: `curl -fsS https://api.<domain>/health/ready` returns 200 and
   `scripts/smoke-deploy.sh` passes.

## 8. Smoke test behavior
`BASE_URL=<url> scripts/smoke-deploy.sh`:
- Fails on non-2xx from `/health/live` or `/health/ready`.
- Parses `/health/deep` (python, no jq): asserts `database`, `redis`, `migrations`,
  `worker_heartbeat` checks exist; worker heartbeat is **not** `missing`; and no
  secret-looking strings (`ALERT_WEBHOOK_URL`, `postgres://`, `redis://`,
  `JWT_SECRET`, `SECRET_KEY`, `password`) appear in the response.

## 9. Production compose cleanup (E0-4)
- **No `train.csv`** mounted (removed — demo-only).
- **No demo seed** mounts (`init.sql` demo seeding replaced by schema-only
  `database/prod-init.sql`).
- **Schema source = the `migrate` job** (`database/migrations/*`), applied on the
  prod-init base. Synthetic generator stays `--profile demo` gated;
  `RUN_SEED_ON_STARTUP=false`, `LIVE_GENERATOR_ENABLED=false` for the backend.
- `scripts/validate-production-compose.sh` enforces all of the above in CI.

## 10. Acceptance checklist
- [ ] Staging deploy log (green `deploy-staging`).
- [ ] Production tag deploy log (green `deploy-production` on a `vX.Y.Z` tag).
- [ ] Smoke test pass (both environments).
- [ ] Rollback proof (redeploy of a previous tag → `/health/ready` 200).
- [ ] Fresh-VM compose validation (`validate-production-compose.sh` green; stack boots).
- [ ] External monitor proof (see `docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md` §9).
