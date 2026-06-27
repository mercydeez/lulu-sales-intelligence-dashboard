# Demo Script — Retail IQ

A guided **~8-minute** walkthrough for a portfolio reviewer or interviewer. It is ordered to build a narrative: *live data → analytics → security → honest engineering*. Timings are approximate.

> **Before you start**
> ```bash
> docker compose up -d            # wait ~20s for the backend lifespan to finish
> curl -s localhost:8000/health   # expect {"status":"healthy",...}
> ```
> Open http://localhost:3000. Password for every demo login is **`Demo@2026!`**.

---

## 0 · One-line framing (15s)

> "This is a real-time retail sales-intelligence dashboard. The data is synthetic — a generator writes a sale every few seconds — but the pipeline, the security, and the analytics are real. I built it to show I can ship a coherent full-stack system and be honest about its limits."

---

## 1 · The live pipeline (90s) — *the hook*

1. Log in as **`atharva@retaildemo.app`** (Super Admin).
2. Land on the **home / Live Operations** screen. Point out:
   - The **KPI tickers** count up; the live streaming count flashes green on increase (and respects `prefers-reduced-motion`).
   - The **live sales table** appends new rows on its own — no refresh, no polling.
3. Explain the path in one breath: *generator → PostgreSQL + Redis pub/sub → SSE → the browser's `EventSource`.*
4. (Optional, for the technical reviewer) show it on the wire:
   ```bash
   TOKEN=$(curl -s -XPOST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"atharva@retaildemo.app","password":"Demo@2026!"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
   TICKET=$(curl -s -XPOST localhost:8000/api/auth/stream-ticket -H "Authorization: Bearer $TOKEN" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["ticket"])')
   curl -sN --max-time 4 "localhost:8000/stream/sales?ticket=$TICKET"
   # → "event: connected" then live "event: sales" frames
   ```
   Mention the **stream ticket**: `EventSource` can't send an auth header, so streams use a short-lived ticket instead.

---

## 2 · Analytics & forecasting (90s) — *the substance*

1. Go to **Analytics**.
2. **Overview tab:** revenue KPIs, the sales-trend chart, category mix, store distribution, top items, store-performance table.
3. **Forecast tab:** pick a store/item and a holdout window. Highlight the **MAPE** number and that it is measured **against a seasonal-naive baseline** — i.e. the model is evaluated honestly, not just plotted.
4. Drop the honesty line: *"Analytics shows AED because this is the one place units are priced — `units × unit_price_aed`."*

---

## 3 · RBAC, live (75s) — *the security story*

1. Log out, log in as **`krishna@retaildemo.app`** (Regional Manager, Dubai).
2. Revisit home/Analytics — **same screens, less data**: only Dubai stores. The store-comparison panel narrows.
3. Log in as **`yash@retaildemo.app`** (Store Manager, Al Barsha) — now scoped to a single store.
4. The point: *scoping is enforced **server-side** from the JWT's region→store expansion, not hidden in the UI.*

---

## 4 · Operational depth (90s) — *breadth without fluff*

Back as Super Admin, click through quickly:

- **Alerts → Tasks:** acknowledge an alert, resolve one with a note, open "My Tasks". This is a real persisted workflow, not mock toasts.
- **Inventory:** stock derived from sales velocity; note the **SSE-degraded banner** appears if the stream drops.
- **Employees:** open a bio card and the performance radar — real seeded performance data (30 employees, 180 records).
- **Admin:** call out that it's a **read-only** console *on purpose* — the admin backend is GET-only, so I didn't fake write buttons that do nothing.
- **Reports:** point out figures are labelled **units** (not AED) and the PDF footer says why. *This is the deliberate counterpoint to the Analytics screen.*

---

## 5 · The "I read my own code" moment (60s) — *seniority signal*

Pick one or two:

- **Data honesty:** the same `sales` number is units on Reports and priced revenue on Analytics — because only the analytics endpoints join `unit_price_aed`. I made that distinction explicit instead of papering over it.
- **A real bug I fixed:** fresh-boot employee seeding crashed because two columns were declared `String` while the DB made them PG enums; I bound them with SQLAlchemy `Enum(create_type=False, values_callable=…)`. Verified a clean re-seed.
- **Production hardening (Phase 4):** enumerated CORS (wildcards are invalid once credentials are allowed), request-id threaded through every log line, a covering index that turned the hot aggregation into an index-only scan, and savepoints so one failing alert sub-query can't poison the shared transaction.

---

## 6 · Internationalization & a11y (30s)

Use the **globe toggle** (top bar) to switch to **Arabic** — the shell mirrors to **RTL**. Mention WCAG-AA contrast was measured (not eyeballed) and motion respects `prefers-reduced-motion`.

---

## 7 · Close (20s)

> "What's shipped and what's next is laid out in `implementation.md` as a single forward roadmap, the design rationale is in `docs/architecture/ADR.md`, and the README's *Data & Honesty Notes* call out exactly what's synthetic. I'd rather under-claim and be trusted than demo smoke."

---

## Quick reference

| Screen | Route | One-liner |
|--------|-------|-----------|
| Live Ops (home) | `/` | real-time KPIs + live feed |
| Analytics | `/analytics` | trends, breakdowns, MAPE forecast (AED) |
| Inventory | `/inventory` | velocity-derived stock + alerts |
| Alerts | `/alerts` | acknowledge / resolve / my-tasks |
| Promotions | `/promotions` | campaigns + category performance |
| Employees | `/employees` | bios + performance analytics |
| Admin | `/admin` | read-only console (super-admin) |
| Reports | `/reports` | unit-labelled report + PDF |
| Monitoring | `/monitoring` | health / stats / metrics |

**If something looks empty:** historical data ends in 2017 and is date-shifted on a *fresh* volume — "today/this week" reflects generator output, so give it a minute to accumulate, or `docker compose down -v && docker compose up -d` to reload history.

