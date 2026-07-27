# AUDIT — demo hardening

Branch `demo-hardening`, off `prototype-evolution-accuracy-bullmq` @ `4758749`.
Audit date 2026-07-27. Verification is automated: `python scripts/demo_smoke.py`.

---

## ROOT CAUSE SUMMARY

The reported symptom was "pages not loading properly". Measured against a real
authenticated session, **that symptom did not reproduce**: all 65 routes render,
none blank, none hit an error boundary, no uncaught exceptions, and every route
settles in under 1.6s. What the sweep did find were four systemic defects, three
of which are invisible until someone checks the numbers against source.

1. **Displayed KPIs were wrong by ~500x, not missing.** `average_daily_sales` and
   `average_daily_revenue` were `AVG()` over `metric_sales_fact`, whose grain is
   one *store-item-day* row (~516 rows/day) — so they averaged a row, not a day.
   The dashboard renders them literally as "Avg: N units/day" and "AED N/day".
   The app claimed **52 units/day** and **AED 1,022/day** against actuals of
   ~26,866 units and ~AED 447,000. This is the single most demo-damaging finding:
   a retail buyer reads those cards first.

2. **Demo data silently went stale.** The date shift anchoring history to
   "yesterday" ran only on the initial CSV load, so a database seeded N days ago
   serves history ending N days ago. Found at **36 days stale** — only 471 rows in
   the last 7 days, all from the live generator. That made `total_sales_today` and
   `total_sales_week` byte-identical and would have put a month-wide cliff in
   every trend chart.

3. **Restarting the backend reliably killed it.** `run_seed` re-executed the full
   `init.sql` on every boot; that DDL needs `AccessExclusiveLock` while the worker
   polls the same tables. Reproduced twice — and it sits on the demo path, because
   any `.env` change needs a backend restart.

4. **Two hard 500s**, including one that was also an auth hole: the legacy
   `/api/stream/sales` shim declared no ticket dependency and, had it not crashed,
   would have streamed live tenant sales unauthenticated.

A fifth, operational: **`backend`, `singletons` and `worker` share one codebase**.
Rebuilding only `backend` leaves the `singletons` cache warmer running old code,
which overwrote corrected KPIs back into Redis. The smoke test caught this.

---

## Findings

| Area | Item | Status | Root cause | Fix | Prevention | Commit |
|---|---|---|---|---|---|---|
| KPIs | `Avg N units/day` ~500x low | 🟩 | `AVG(units)` averages a store-item-day row, not a day | window total ÷ `COUNT(DISTINCT date)` over last 30 completed days | smoke test asserts avg reconciles with month/30 | `82a1543` |
| KPIs | `AED N/day` ~500x low | 🟩 | same | same | same | `82a1543` |
| Data | history 36 days stale | 🟩 | date shift ran only on initial CSV load | `_refresh_date_shift()` re-asserts every boot, no-op when fresh | smoke test fails if `data_range_end` > 2d old, or week == today | `82a1543` |
| Startup | backend restart deadlock | 🟩 | `init.sql` DDL vs worker's `AccessShareLock` | skip DDL when core tables exist; bounded `lock_timeout` + backoff for the fresh-DB path | `SEED_FORCE_SCHEMA=1` escape hatch | `d478f17` |
| API | `/api/data-rights/export` 500 | 🟩 | UUID/datetime not JSON-serializable via `JSONResponse` | route through `jsonable_encoder` | smoke test fails on any 5xx | `7cb0a2f` |
| API | `/api/stream/sales` 500 **+ unauthenticated** | 🟩 | shim called `event_generator(request)`; signature is `(request, current_user)`; no ticket dep | 307 to the real ticket-authed endpoint, preserving query | smoke test fails on any 5xx | `7cb0a2f` |
| Config | `OLLAMA_URL` = a comment string | 🟩 | inline comment on a value line; Compose passes it through as the value | comment moved to its own line in `.env.example` | warning documented in-file | `d478f17` |
| Sage | canned replies, no LLM | 🟥 | no provider configured; the garbage `OLLAMA_URL` put a doomed provider at the head of the chain | env slot prepared, `ENABLE_EXTERNAL_AI=true` set | — | **blocked on API key** |
| Nav | login screen flash | 🟩 | redirect ran in `useEffect` (post-paint) while render returned children | decide during render, hold loader | — | `dee149e` |
| Nav | slow tab switching | 🟩 | `pathname` in badge-fetch deps → 2 uncached calls per switch | 60s timer + refresh on arrival | — | `dee149e` |
| Nav | SSE re-handshake per nav | 🟩 | connection closed on last unsubscribe | 30s linger, exponential backoff, logout purge | — | `dee149e` |
| Flywheel | 17 routes empty | 🟨 | synthetic customer layer never generated | ran the product's own `POST /api/flywheel/seed` (400 customers, 8,890 events) | — | data-only |

---

## Verification

**Endpoint sweep** — 190 parameterless GETs under a real session: **0 × 5xx**.
The 18 remaining non-200s are all intended: `/stream/*` and `/api/public/v1/*`
correctly demand a stream ticket / API key, SSO and voice are feature-disabled,
and 3 × 422 are the probe omitting required query params.

**Browser sweep** — all 65 routes in headless Chromium, authenticated:

| Metric | Result |
|---|---|
| Hard-broken (blank / error boundary / nav fail / bounced to login) | **0** |
| Uncaught page exceptions | **0** |
| `NaN` / `undefined` / `[object Object]` reaching the DOM | **0** |
| Routes over 3s | **0** (median 987ms, p90 1286ms, max 1574ms) |
| Console errors | 2, both benign |

The only flagged routes are benign: `/flywheel/campaigns/[id]` and
`/flywheel/decisions/[id]` 404 on a fabricated `id=1` (those tables are empty by
design), and `/procurement` shows Next.js prefetch aborts on page close.

---

## Known issues / not fixed

- **Sage answers from rules, not an LLM.** Blocked on the API key. Until then it
  will misroute questions — the observed "how much stock is expiring" fell through
  to a greeting template. See DEMO_READINESS.md for the workaround.
- **Sage's SQL guardrail has never executed.** `nl2sql/guard.py` is genuinely
  strict (single-statement, SELECT/WITH only, relation allow-list, row cap, backed
  by a least-privilege `sage_ro` role) but no SQL has ever reached it, because no
  LLM has ever generated any. "Read-only safe" is currently an *untested claim*.
  It also looks prone to false positives: the keyword check tokenises the whole
  string including literals, so a query containing `'do not ship'` is rejected for
  the word `do`.
- **Fresh-database path verified by inspection only.** The seeder changes were
  tested on the already-provisioned path. Testing the fresh path means
  `docker compose down -v` and re-seeding 900k rows — **do not run that tonight.**
- **Empty workflow tables** (campaigns, approvals, holdout, trade, coalition,
  webhooks, SSO providers, POS connections). These populate when a user creates
  something; pages render correct empty states. Not defects.
- **`PRODUCT_NAME` mismatch**: `.env` says "Retail IQ", the frontend ships
  "Retail Intelligence". Sage may name the product differently than the UI.
- **Demo retailer is "Meridian Hypermarket"** in all seed data.
- **Week/month windows are 8 and 31 days**, not 7 and 30 (`>= today - 7`). Left
  alone deliberately — correct-ish, and not worth changing the night before.
