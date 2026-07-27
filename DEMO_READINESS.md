# DEMO READINESS — Al Safeer Group

Branch `demo-hardening`. Last verified 2026-07-27, `python scripts/demo_smoke.py`
→ **DEMO READY — 0 failures, 0 warnings.**

---

## 🎯 Pre-demo checklist (do this ~30 min before)

```bash
docker compose up -d
python scripts/demo_smoke.py
```

The smoke test is the gate. **If it does not print `DEMO READY`, do not start.**
It checks services, seed volume, history freshness, all 190 GET endpoints for
5xx, and that the per-day KPI averages reconcile against month/30.

Then, in the browser:

1. Open http://localhost:3000 in a **fresh incognito window** (avoids a stale
   cached profile from an earlier role).
2. Log in as `atharva@retaildemo.app` / `Demo@2026!` (super_admin — widest scope,
   all 12 stores).
3. Confirm the overview hero renders a revenue sentence, not a spinner.

**Cold start takes ~20s.** Backend healthy in 18s from `docker compose up -d`.

⚠️ **Do not run `docker compose down -v` tonight or tomorrow.** It wipes the
volume and re-seeds ~915k rows. The fresh-database seeding path was verified by
code inspection only, not executed.

---

## ✅ Green list — verified working, in demo order

| # | Step | Route | Evidence |
|---|---|---|---|
| 1 | Landing / overview | `/` | KPI cards show real AED. Hero and cards now agree exactly (AED 3,050,411 / 155,461 units). |
| 2 | Revenue / sales trend | `/analytics` | Renders, 1529ms, no console errors. |
| 3 | Insights / findings | `/insights` | Richest page (64.5k chars of real findings, named stores and SKUs). |
| 4 | Inventory health | `/inventory` | Renders, real stock positions. |
| 5 | Forecast lab | `/forecast-lab` | Renders. |
| 6 | Today | `/today` | Renders. |
| 7 | Alerts | `/alerts` | Renders, 455 alerts seeded. |
| 8 | Reports | `/reports` | Renders. |

**Whole-app numbers:** all **65 routes** load; **0** blank/crashed; **0** uncaught
exceptions; **0** `NaN`/`undefined` reaching the screen; **0** routes over 3s
(median 987ms, max 1574ms); **0** 5xx across 190 endpoints.

---

## ⚠️ Known issues and workarounds

### 1. Sage — ✅ WORKING (key installed)
Provider chain is `['OpenAIProvider']`. Verified end to end.

**Ask it questions with a clear window and subject.** These are verified:
- *"What were the total units sold yesterday across all stores?"* → **26,420**,
  which matches the database exactly.
- *"What were the total units sold by each store in the last 30 days?"* → correct
  per-store breakdown, `grounded=True`, `confidence 1.00`.

**Behaviour to expect:** vague questions trigger a clarifying question rather than
a guess — that is by design and demos well ("it asks rather than hallucinates").
Your original *"how much stock is getting expired in total and from which store?"*
still asks "which store?" first. Either answer it, or phrase it as *"expiring
stock by store"*.

⚠️ **On phrasing "last 30 days":** Sage's window can differ from the dashboard's
by a day or two, so a Sage figure may not tie exactly to a KPI card. Prefer
"yesterday" or an explicit date range when you want the two to match on screen.

### 2. Sage read-only safety — what you can and cannot claim
**You CAN say:** queries run as a least-privilege `sage_ro` Postgres role that is
verified to have no INSERT/UPDATE/DELETE/DROP/CREATE grant and no read access to
base tables like `users`; generated SQL is additionally allow-listed to a fixed
set of read-only `sage_*` views with a hard row cap. This is enforced by the
database, not by string matching. Injection attempts were tested and refused.

**Lead with the database role, not the regex** — that is the layer that holds even
if everything above it is bypassed. If pressed for detail, `AUDIT.md` has the
four-layer table with the evidence for each.

### 3. Restarting the backend alone can wedge it
Fixed and verified (7s restart under load), but if you ever see
`Application startup failed`:

```bash
docker compose stop worker singletons && docker compose restart backend && docker compose up -d worker singletons
```

### 4. Rebuilding one service is not enough
`backend`, `singletons` and `worker` share a codebase. The `singletons` cache
warmer will overwrite KPIs with stale values if it runs old code. Always:

```bash
docker compose up -d --no-deps --build backend singletons worker
```

### 5. Cosmetic / talking points
- **"Business Health 25/100 — Critical"** is prominent on the landing page. This
  is *intentional* (it drives "Decisions that need you"), but frame it before they
  ask: it is the system surfacing real risk, not the product failing.
- **Empty sections:** Flywheel campaigns, approvals, holdout, trade, coalition;
  webhooks; SSO providers; POS connections. These fill when a user creates
  something. Pages render proper empty states. Avoid clicking into
  `/flywheel/campaigns/<id>` or `/flywheel/decisions/<id>` — no record exists, so
  they 404 in the console.
- **Product name mismatch:** `.env` says "Retail IQ", the UI ships "Retail
  Intelligence". Sage may name the product differently than the screen.
- **Demo retailer is "Meridian Hypermarket"** throughout the seed data. If you
  want it reading "Al Safeer", that is a data change — ask before the demo, not
  during.
- **Week/month windows are 8 and 31 days** (`>= today - 7`). Left as-is
  deliberately; only the *headline* week totals were re-scoped to 7 completed days
  to match the hero.

---

## 🔥 If it breaks live

| Symptom | Do this |
|---|---|
| Page stuck spinning | Hard-refresh (Ctrl+Shift+R). The auth gate holds a loader until the route settles. |
| A number looks wrong | `python scripts/demo_smoke.py` in a side terminal — it reconciles KPIs against SQL. |
| Backend unreachable | `docker compose restart backend`; if startup fails, use the stop-worker sequence above. |
| KPIs look stale | Cache is Redis-backed with a TTL. `docker exec sales_redis redis-cli -a sales_redis_dev_pass --scan --pattern "cache:*" \| xargs -n50 docker exec sales_redis redis-cli -a sales_redis_dev_pass DEL` |
| Sage says something odd | Expected without an LLM key. Pivot to `/insights`. |

**Safest recovery, always:** `docker compose restart backend` then wait 20s. Data
lives in a volume and is not touched by a restart.
