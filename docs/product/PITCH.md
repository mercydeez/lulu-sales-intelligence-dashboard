# Retail IQ — One-Page Pitch

**What it is:** a real-time retail sales-intelligence dashboard for a UAE supermarket chain. A background generator emits a synthetic sale every few seconds; it flows through PostgreSQL and Redis to a Next.js dashboard that updates live. Built solo as a portfolio MVP — **synthetic data, real engineering.**

**Try it in 30 seconds:** `docker compose up -d` → http://localhost:3000 → log in as `atharva@retaildemo.app` / `Demo@2026!`.

---

## The problem (framing)

Retail operators need *current* visibility — sales as they happen, scoped to the store or region a person is responsible for, with forecasting and alerting on top. Most demo dashboards fake the "real-time" part and hand-wave security and data provenance. This project takes those three things seriously.

## The solution

| Pillar | What it does | How |
|--------|--------------|-----|
| **Live pipeline** | sub-15s updates, no polling | generator → Postgres + Redis pub/sub → SSE → `EventSource` |
| **Analytics** | trends, breakdowns, demand forecast | async SQL aggregations; seasonal forecast with a **MAPE backtest vs a naive baseline** |
| **Security** | role-scoped access, hardened API | JWT + region→store RBAC enforced server-side; CSP/CORS/CSRF/rate-limit middleware |
| **Honesty** | trustworthy numbers | documents what's synthetic, units vs derived AED revenue, and what's simplified |

Nine screens (Live Ops, Analytics/Forecast, Inventory, Alerts→Tasks, Promotions, Employees, Admin, Reports, Monitoring) on a custom design system with **EN/AR + RTL** and **WCAG-AA** contrast.

---

## Key technical decisions & tradeoffs

- **SSE over WebSockets** — dashboards only need server→client push; SSE is simpler, auto-reconnects, rides plain HTTP. Streams are auth'd with short-lived **tickets** (because `EventSource` can't send headers). *Tradeoff:* no client→server channel — fine here.
- **Three-table sales model unified by a view** — history and live events stored separately, queried through one `sales_fact_view`. *Tradeoff:* the view's date expression blocks one kind of index on the live table (small, so OK).
- **Local-first AI** — Ollama by default, OpenAI optional, deterministic DB-backed fallback. *Tradeoff:* the fallback answers a fixed intent set rather than free-form — chosen so it can't hallucinate business figures, and so it needs **no paid key**.
- **Units vs derived revenue** — the source data has no prices; revenue = `units × unit_price_aed`, applied only where it's meaningful (Analytics), while Reports stays in honest units. *Tradeoff:* two screens show different scales — documented, not hidden.
- **Build only what the backend supports** — the Admin console is read-only because the admin API is GET-only; no dead buttons. *Tradeoff:* looks less "finished" than a mock-driven build; that's the point.

---

## Engineering quality signals

- **92 backend tests**; CI runs the full suite + enforced TypeScript check + Next build + Docker builds on every push.
- **Phase 4 hardening, each change measured:** enumerated CORS (wildcards are invalid with credentials), env-driven CSP, a `request_id` threaded through every log line, a covering index that turned the hot aggregation into an **index-only scan**, and **savepoints** so one failing alert sub-query can't poison a shared transaction.
- **Self-audited:** found and fixed a fresh-boot seeding crash (ORM `String` columns vs PG enum columns) and a CORS spec violation that the original config shipped with.
- **Documented end-to-end:** [`README.md`](../../README.md) (incl. Data & Honesty Notes), [`docs/architecture/ADR.md`](../architecture/ADR.md) (decisions), [`docs/product/DEMO_SCRIPT.md`](DEMO_SCRIPT.md) (walkthrough), and [`implementation.md`](../../implementation.md) (phase-by-phase log with commits).

## Stack

Next.js 14 / TypeScript / Tailwind / Recharts · FastAPI / async SQLAlchemy 2 / asyncpg · PostgreSQL 15 · Redis 7 · Docker Compose · JWT + bcrypt · Ollama/OpenAI.

## Honestly out of scope (for now)

Trained ML forecasting (currently statistical), frontend component tests, CSP nonces, down-migrations, and richer admin writes (need new endpoints). These are listed as roadmap items rather than faked.

---

**Author:** Atharva Soundankar — [github.com/mercydeez](https://github.com/mercydeez)

