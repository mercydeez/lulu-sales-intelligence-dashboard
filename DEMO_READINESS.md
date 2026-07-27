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

### 1. Sage answers from rules, not an LLM — **BLOCKED ON YOUR API KEY**
No LLM provider is configured, so Sage falls back to deterministic rules. It will
misroute questions: "how much stock is expiring and from which store" fell through
to a **greeting template**.

- **To fix:** paste the key into `.env` → `OPENAI_API_KEY=`, keep
  `ENABLE_EXTERNAL_AI=true` (already set), then `docker compose up -d backend`.
- **If not fixed — demo workaround:** do not ask Sage open-ended analytical
  questions. Use it only to show the *interface* and the reasoning trace, or skip
  the Sage step. Do **not** promise natural-language querying live.
- **If it breaks live:** Sage returns a canned greeting with quick stats. Move on
  to `/insights`, which delivers the same analytical value from real data and is
  the strongest page in the app.

### 2. Sage's SQL guardrail has never executed
`nl2sql/guard.py` is strict on paper — single statement, SELECT/WITH only,
relation allow-list of curated `sage_*` views, hard row cap, least-privilege
`sage_ro` role. But **no SQL has ever reached it**, because no LLM has ever
generated any. **Do not claim "the SQL is verified read-only" on stage** — it is
designed to be, but untested. If asked, say the guardrail is allow-list based and
you can walk them through the code.

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
