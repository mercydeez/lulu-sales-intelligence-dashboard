# Deploying to Render (free tier)

> **Production deploy pipeline (E0-3):** for the compose-based staging/production
> pipeline (push to `main` → staging, tag `vX.Y.Z` → production, smoke-gated,
> rollback by redeploying a previous tag), see
> **[docs/runbooks/DEPLOY_PIPELINE.md](docs/runbooks/DEPLOY_PIPELINE.md)**. For
> uptime monitoring + founder-phone alerting, see
> **[docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md](docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md)**.
> Production uses schema-only `database/prod-init.sql` + the `migrate` job (no demo
> data, no `train.csv`); `scripts/validate-production-compose.sh` enforces this.

This app is a 4-service stack: **Postgres**, **Redis**, a **FastAPI backend**
(always-on — it runs the live data generator + SSE), and a **Next.js frontend**.
`render.yaml` provisions all four.

> Architecture note: the backend **cannot** be a sleep-on-idle service if you
> want the "real-time" demo to look alive. Free Render web services sleep after
> ~15 min idle, so add the keep-warm pinger (Step 5).

---

## 1. Push to GitHub
```bash
git push origin main      # (or your branch)
```

## 2. Create the Blueprint
In Render: **New + → Blueprint → select this repo → Apply.**
Render reads `render.yaml` and creates: `app-postgres`, `app-redis`,
`app-backend`, `app-frontend`. It auto-wires `DATABASE_URL` and `REDIS_URL`,
and generates strong `JWT_SECRET_KEY` / `SECRET_KEY`.

The **first backend boot runs the seeder** (creates the schema and bulk-loads
913k historical rows, then migrations) — allow **~1–2 minutes** before it goes
healthy. This is normal and only happens once.

## 3. The URL handshake (two values render.yaml can't know up front)
After the services exist, grab their URLs (e.g. `https://app-backend.onrender.com`,
`https://app-frontend.onrender.com`) and set:

| Service | Env var | Value |
|---|---|---|
| **app-frontend** | `NEXT_PUBLIC_API_URL` | the **backend** URL (e.g. `https://app-backend.onrender.com`) |
| **app-backend** | `CORS_ORIGINS` | the **frontend** URL (e.g. `https://app-frontend.onrender.com`) |
| **app-backend** | `CSP_CONNECT_SRC` | `'self' https://app-backend.onrender.com` |

Then **redeploy both** (the frontend value is baked at build time, so it needs
a rebuild). After this, the frontend talks to the backend and CORS/CSP allow it.

## 4. Verify
- Open the frontend URL, log in with a demo account (below).
- Backend health: `https://app-backend.onrender.com/health` → `200`.
- The live feed / KPIs should populate (KPIs are warmed, so ~instant).

## 5. Keep-warm pinger (so the free backend doesn't sleep)
Use a free uptime monitor (UptimeRobot, cron-job.org, …):
- **GET `https://app-backend.onrender.com/health` every ~10 minutes.**
- (Optionally also ping the frontend URL.)

One always-warm backend stays within Render's free monthly instance-hours, so
this is effectively always-on for **$0**. Without it the generator/SSE pause on
idle and the dashboard looks dead until the next visit wakes it (~30–60s cold
start).

## 6. Optional: real AI answers
Set `OPENAI_API_KEY` on **app-backend** to enable LLM chat. Without it, the
assistant uses the built-in rule-based responder (still answers from live data).

---

## Backups & disaster recovery (blueprint E0-1)

Do not host a real tenant without this. Full detail:
[`docs/runbooks/BACKUP_AND_RESTORE.md`](docs/runbooks/BACKUP_AND_RESTORE.md).

- **Self-hosted (docker compose):** the production stack runs an always-on `backup` sidecar —
  daily `pg_dump` at `BACKUP_AT_UTC` (default 02:00 UTC) + an immediate backup on boot, each
  self-verified, pruned to `BACKUP_RETENTION_DAYS`. Set `BACKUP_S3_URL` (+ `AWS_*`) for an
  **offsite** copy — a backup on the DB's own host is not disaster recovery.
- **Render (managed Postgres):** enable the provider's automated daily snapshots — that is your
  offsite tier. Use `scripts/backup-postgres.sh` from any box with DB access for on-demand dumps.
- **Restore is proven, not assumed:** `scripts/drill-restore.sh` restores into a scratch DB and
  checks row counts + a checksum; CI runs it on every push (`backup-restore-drill`). Rehearse
  against the real pilot DB quarterly and log it in the runbook.
- **Real recovery** (overwrites the DB): follow
  [`docs/runbooks/RESTORE_FROM_BACKUP.md`](docs/runbooks/RESTORE_FROM_BACKUP.md).

## Demo logins (password `Demo@2026!`)
| Email | Role | Scope |
|---|---|---|
| `atharva@retaildemo.app` | super_admin | all 10 stores |
| `krishna@retaildemo.app` | regional_manager | Dubai (3 stores) |
| `yash@retaildemo.app` | store_manager | Al Barsha (1 store) |

## Gotchas
- **Free Postgres expires ~90 days** after creation — take a dump
  (`scripts/backup-postgres.sh`) and recreate before then; see Backups & DR above.
- **First deploy is slow** (~1–2 min) while the seeder loads the CSV; subsequent boots skip it.
- Local dev is unchanged: `docker compose up -d` still works (the backend seeds
  the local DB the same way; no Postgres entrypoint needed).
