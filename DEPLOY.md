# Deploying to Render (free tier)

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
Render reads `render.yaml` and creates: `lulu-postgres`, `lulu-redis`,
`lulu-backend`, `lulu-frontend`. It auto-wires `DATABASE_URL` and `REDIS_URL`,
and generates strong `JWT_SECRET_KEY` / `SECRET_KEY`.

The **first backend boot runs the seeder** (creates the schema and bulk-loads
913k historical rows, then migrations) — allow **~1–2 minutes** before it goes
healthy. This is normal and only happens once.

## 3. The URL handshake (two values render.yaml can't know up front)
After the services exist, grab their URLs (e.g. `https://lulu-backend.onrender.com`,
`https://lulu-frontend.onrender.com`) and set:

| Service | Env var | Value |
|---|---|---|
| **lulu-frontend** | `NEXT_PUBLIC_API_URL` | the **backend** URL (e.g. `https://lulu-backend.onrender.com`) |
| **lulu-backend** | `CORS_ORIGINS` | the **frontend** URL (e.g. `https://lulu-frontend.onrender.com`) |
| **lulu-backend** | `CSP_CONNECT_SRC` | `'self' https://lulu-backend.onrender.com` |

Then **redeploy both** (the frontend value is baked at build time, so it needs
a rebuild). After this, the frontend talks to the backend and CORS/CSP allow it.

## 4. Verify
- Open the frontend URL, log in with a demo account (below).
- Backend health: `https://lulu-backend.onrender.com/health` → `200`.
- The live feed / KPIs should populate (KPIs are warmed, so ~instant).

## 5. Keep-warm pinger (so the free backend doesn't sleep)
Use a free uptime monitor (UptimeRobot, cron-job.org, …):
- **GET `https://lulu-backend.onrender.com/health` every ~10 minutes.**
- (Optionally also ping the frontend URL.)

One always-warm backend stays within Render's free monthly instance-hours, so
this is effectively always-on for **$0**. Without it the generator/SSE pause on
idle and the dashboard looks dead until the next visit wakes it (~30–60s cold
start).

## 6. Optional: real AI answers
Set `OPENAI_API_KEY` on **lulu-backend** to enable LLM chat. Without it, the
assistant uses the built-in rule-based responder (still answers from live data).

---

## Demo logins (password `Lulu@2026!`)
| Email | Role | Scope |
|---|---|---|
| `atharva@lulu.ae` | super_admin | all 10 stores |
| `krishna@lulu.ae` | regional_manager | Dubai (3 stores) |
| `yash@lulu.ae` | store_manager | Al Barsha (1 store) |

## Gotchas
- **Free Postgres expires ~90 days** after creation — back up / recreate before then.
- **First deploy is slow** (~1–2 min) while the seeder loads the CSV; subsequent boots skip it.
- Local dev is unchanged: `docker compose up -d` still works (the backend seeds
  the local DB the same way; no Postgres entrypoint needed).
