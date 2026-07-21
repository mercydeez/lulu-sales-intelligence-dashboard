# Architecture Decision Records

Lightweight ADRs capturing the **why** behind the significant choices in this project. Each records the context, the decision, and the tradeoffs we accepted. They are deliberately short. Newest concerns last.

Format: **Context → Decision → Consequences (good & bad)**. Status is one of `Accepted`, `Superseded`, `Revisit`.

---

## ADR-001 · Three-table sales model unified by a view
**Status:** Accepted (migration 007)

**Context.** Two data sources had to coexist: ~900k rows of CSV history (immutable, bulk-loaded) and an unbounded stream of generated live events. An early version kept everything in one `sales` table with an `is_streaming` flag.

**Decision.** Split storage into `sales_historical` (CSV) and `sales_stream_raw` (live events), and expose a `sales_fact_view` UNION that every reader queries. Live ids are offset by 1e9 so the ORM identity map stays correct across the union. The legacy `sales` table was dropped.

**Consequences.**
- 👍 Writers and readers are decoupled; the history table is never mutated; each table can be indexed for its own access pattern.
- 👍 Readers are oblivious — they select from one view shaped like the old columns.
- 👎 The view exposes the stream's `timestamp` as `timestamp::date`, a non-IMMUTABLE expression, so the live side can't use a date *expression index* (see ADR-009). Acceptable while that table stays small.

---

## ADR-002 · Synthetic data, units-not-currency, derived revenue
**Status:** Accepted (migration 005)

**Context.** The Kaggle dataset is a **unit-demand** dataset (10 stores × 50 items, 2013–2017) with **no price column**. A retail dashboard wants AED revenue.

**Decision.** Treat the raw `sales` value as **units**. Add a per-item `unit_price_aed` and derive revenue as `units × unit_price_aed`, but apply that derivation **only** in `/api/analytics/*` and KPIs. Date-shift the history on fresh load so "today" has data. The **Reports** screen reports raw **units** and says so.

**Consequences.**
- 👍 The product reads as a money dashboard where it makes sense, without pretending the source data has prices.
- 👍 The units-vs-AED split is documented in the README and surfaced in the Reports PDF footer — an honesty signal, not a hidden inconsistency.
- 👎 Two screens (Analytics vs Reports) show different scales for "the same" number; this *must* be explained, or it looks like a bug. We chose explanation over silent uniformity.

---

## ADR-003 · Server-Sent Events for real-time, with ticket auth
**Status:** Accepted

**Context.** The dashboard needs server→client push. Options: polling, WebSockets, SSE.

**Decision.** Use **SSE** (sse-starlette) relaying Redis pub/sub. Authenticate streams with a short-lived **stream ticket** (`POST /api/auth/stream-ticket` → `?ticket=…`) because the browser `EventSource` API cannot set an `Authorization` header.

**Consequences.**
- 👍 One-directional push is exactly what dashboards need; SSE is simpler than WebSockets, auto-reconnects, and rides plain HTTP.
- 👍 Tickets keep streams authenticated without putting the long-lived JWT in a URL.
- 👎 No client→server messaging over the same channel (fine here). A future bidirectional feature would justify the WebSocket upgrade noted in the roadmap.

---

## ADR-004 · Local-first AI provider chain
**Status:** Accepted

**Context.** The assistant should be useful in a demo without forcing a reviewer to supply (and pay for) an API key, and without hard-failing if no model is reachable.

**Decision.** A provider chain: **Ollama** (local, zero-cost) is the default; **OpenAI** is opt-in via env var; both raise `LLMError` on failure and the caller falls through to a **deterministic rule-based responder** that always answers from live DB aggregates.

**Consequences.**
- 👍 Runs out-of-the-box with no key; degrades gracefully instead of erroring; no paid dependency to demo.
- 👍 The fallback can't hallucinate business numbers — it reads them from the database.
- 👎 The rule-based path answers a fixed set of intents, not free-form questions. Accepted: a wrong-but-confident LLM answer is worse than a narrower honest one.

---

## ADR-005 · Custom SQL migration runner instead of Alembic
**Status:** Accepted

**Context.** The repo shipped an empty `alembic/` scaffold but migrations were authored as plain numbered `.sql` files (DO blocks, functions, triggers, bulk loads) that don't map cleanly onto Alembic's autogenerate.

**Decision.** A small runner applies `database/migrations/00*.sql` in order on startup, tracking applied versions in a `schema_migrations` table, executing each script through the raw driver so multi-statement PostgreSQL runs as-is. `init.sql` still auto-runs on a fresh volume. The unused Alembic dependency was removed.

**Consequences.**
- 👍 Zero manual migration steps; the SQL is readable and reviewable as-is; idempotent (`IF NOT EXISTS`) and safe to re-run.
- 👎 No down-migrations / autogenerate. For a fixed, forward-only demo schema that's a fair trade; a long-lived product would adopt a real migration tool.
- ⚠️ The runner wraps each script in a transaction, so migrations can't use `CREATE INDEX CONCURRENTLY` — a real constraint that shaped ADR-009.

---

## ADR-006 · RBAC by region→store, scoped server-side
**Status:** Accepted

**Context.** Three role tiers (super admin, regional manager, store manager) must see different slices of the same screens.

**Decision.** Permissions and a region→store expansion live in the DB; JWTs embed the user's permissions at login. Every scoped query filters by the user's `accessible_stores` **on the server**; the UI merely reflects what comes back. Logout blacklists token hashes in Redis.

**Consequences.**
- 👍 Scoping can't be bypassed by poking the client; the same component renders correctly for any role.
- 👎 Permissions are snapshotted into the token at login, so a permission change takes effect on next login/refresh. Acceptable for this domain.

---

## ADR-007 · Thin page composers + feature folders + one API client
**Status:** Accepted

**Context.** The original screens were large `'use client'` pages mixing data-fetching, mock fallbacks, and presentation, with ~22 scattered raw `fetch()` calls.

**Decision.** Each screen became a **thin composer** over a `components/<feature>/` folder (types, format, components, barrel). All data flows through a single **auth-aware API client** (`AuthContext.authFetch` / `lib/apiClient`) handling JWT, 401→refresh→retry, and a user-aware cache. Mock fallbacks were removed — each screen serves only what its real endpoints return.

**Consequences.**
- 👍 Consistent auth/refresh behaviour; screens are small and testable; no fake data masking missing endpoints.
- 👎 More files per feature. Worth it for clarity and reuse.

---

## ADR-008 · Build only what the backend really supports
**Status:** Accepted

**Context.** Several original screens shipped buttons (Add User, Edit, Save Settings, assignee pickers) with **no backend behind them**.

**Decision.** Scope the UI to real endpoints. The **Admin** console is read-only because the admin API is GET-only. The Alerts assignee picker was dropped because the only user-listing endpoint is super-admin-only. Gaps are tracked as backend work, not faked in the UI.

**Consequences.**
- 👍 Nothing on screen lies about what it does.
- 👎 The product looks slightly less "complete" than a mock-driven version — a deliberate honesty/quality trade.

---

## ADR-009 · Pragmatic production hardening (Phase 4)
**Status:** Accepted

**Context.** Closing the gap from "works on my machine" to "wouldn't embarrass me in prod," within the constraints above.

**Decisions & tradeoffs.**
- **CORS:** enumerate methods/headers — the spec forbids `*` wildcards once `allow_credentials=True`, so the original config was actually invalid for credentialed requests.
- **CSP:** drive `connect-src` from config (no localhost baked into prod), add `object-src 'none'` and prod `upgrade-insecure-requests`. Kept `'unsafe-inline'` for script/style because the bundled Swagger UI and Next.js runtime need it — nonces are the next step, not a quick win.
- **Structured logging:** a `request_id` contextvar + log filter stamps **every** log line (not just middleware lines); optional JSON output. Chosen over passing ids through call signatures.
- **DB index:** added one **covering** index `(date, store_id, item_id) INCLUDE (sales)` after EXPLAIN showed the hot aggregation heap-scanning; it became an index-only scan (heap fetches 0). Did **not** add a stream-side date index (non-IMMUTABLE cast, ADR-001/005) or redundant indexes the schema already had.
- **Transaction safety:** replaced two silent `except: pass` blocks in alert generation with `begin_nested()` **savepoints** + logging, so one failing optional sub-query can't abort the shared asyncpg transaction.
- **Pagination:** audited every list endpoint; only `/api/auth/users` was genuinely unbounded, so only it was changed — the rest were already paginated or naturally bounded.

**Consequences.**
- 👍 Each change is measured/justified rather than cargo-culted; verified against the live stack with 92 passing tests.
- 👎 A few "production-grade" ideals (CSP nonces, down-migrations, ML forecasting) are explicitly deferred rather than half-done.

---

## ADR-010 · Basket grain lives beside the daily grain, not inside it
**Status:** Accepted (E2-5, migration 059)

**Context.** Every sale is stored as a daily aggregate — `sales_historical` / `sales_stream_raw`
carry `(date, store, item, units)` and are unified by `sales_fact_view`. That grain cannot answer
"what else was in the basket?", "when do returns spike?", "which register voids the most?", or
"did this promo cannibalise the item beside it?". Shrink, promo-cannibalisation and customer
intelligence all need line grain. The blueprint (E2-5) wants the schema in place *before* the POS
connector (E2-1) so the connector has somewhere to write, and so E10-8 (waste/expiry) has a base.

**Decision.** Create `transactions` + `transaction_lines` as a **standalone, parallel grain**.
Do **not** union or aggregate them into `sales_fact_view`, `metric_*`, `sage_*` or the `mv_*`
matviews. Leave them empty until a real source fills them.

**Why not bridge them now.**
- The E2-1 connector will land *daily aggregates* in `external_sales` → `sales_rollup_daily`.
  If `transactions` also fed `sales_fact_view`, the first connected POS would **double-count every
  dirham** — the same sale arriving down two paths.
- Bridging would force changes to migration-007's dependents (`mv_*`, `metric_*`, `sage_*`), which
  the whole revenue surface reads. That is a large, reversible-only-with-pain change to make on
  speculation, before a single real basket exists.
- An empty table costs nothing. A wrong aggregation costs trust in every number on the dashboard.

**Consequences.**
- 👍 Revenue keeps exactly one source of truth (the daily grain). The connector can start writing
  line detail without any downstream number moving.
- 👍 Ingest is idempotent by construction: `UNIQUE (tenant_id, source, txn_ref)` means replaying a
  POS export cannot duplicate a receipt.
- 👎 Basket-level questions cannot be answered until a source fills the tables — the schema exists,
  the intelligence does not. That is stated plainly rather than faked.
- 🔁 Revisit when a real POS source lands: decide then whether the daily grain is *derived from*
  the basket grain (one source of truth) rather than sitting alongside it.

**Naming.** Three existing tables sound related and are not: `inventory_transactions` (stock
movements), `employee_transactions` (synthetic demo rows, tenant-unscoped), `basket_associations`
(the *output* of market-basket analysis). Nothing backfills this grain from them.

---

## ADR-011 · Operations Copilot — one auditable state machine, DB as checkpoint, draft-only execution
**Status:** Accepted (migration 081, services/operations/)

**Context.** The diagnostics loop already detects problems (worker rules → `findings`) and can measure outcomes (the measure job → `metric_before/after`). What it lacked was the middle: turning a verified finding into an evidence-backed, human-approved, auditable action. The brief asked for a "Retail Operations Copilot" — explicitly NOT multi-agent theatre, and explicitly safe: no external order without human approval, every number deterministic, the LLM treated as untrusted.

**Decision.**
- **One LangGraph finite-state machine, run in two short invocations, with the database row as the checkpoint.** Invocation A (recommend) runs `load_finding → check_freshness → gather_and_recommend → narrate` and stops at an `awaiting_approval` proposal. Invocation B (approve→revalidate→execute) resumes from that row after a human decides. We did NOT adopt langgraph's own checkpointer: the pinned `langgraph 0.1.19` predates its Postgres saver, invocation A is loop-free, and "persist and stop, resume by run_id" is exactly what the approval flow needs anyway. Nothing is left waiting on an open request.
- **The LLM writes prose, never numbers.** Evidence and every quantity come from pure deterministic functions (`calculations.py`, `tools_read.py`). The only model step, `narrate`, may replace the summary and hypotheses *only after* a mechanical grounding check (`ungrounded_numbers`) confirms it introduced no figure absent from the evidence. No provider, a timeout, bad JSON, or an ungrounded number all fall back to the deterministic recommendation — the copilot works with the LLM off.
- **Four tables, not seven** (`operations_runs`, `operations_proposals`, `operations_events`, `tenant_operations_policies`). Approvals and executions are events on the append-only audit log plus columns on the proposal; measurement reuses the existing `findings` metric loop rather than forking a second definition of "did it improve".
- **Draft-only execution.** A code-side connector registry (empty today) gates real execution; no tenant JSON flag can enable a connector that isn't implemented, so execution only ever writes an INTERNAL `action_drafts` row and schedules measurement by stamping the finding. Nothing is submitted to a supplier or warehouse.
- **Safety is layered, not trusted to one control.** Approval authority is a tenant-configurable policy (`policy.can_approve`) checked at approval AND execution; scope comes only from the verified auth context; the audit log is append-only at the DB (UPDATE/DELETE revoked, and un-cascadable via NO-ACTION FKs); intra-module FKs are composite `(tenant_id, id)` so a row can't reference another tenant's; approvals use optimistic-concurrency version CAS; mutations are idempotency-keyed. FORCE RLS on every table.

**Consequences.**
- 👍 Every recommendation is traceable to evidence; every number is reproducible from inputs; the UI can show exactly how a quantity was reached.
- 👍 The system degrades safely — no LLM, stale data, missing inventory, a lost permission, a concurrent approver, a duplicate request all resolve to a refusal, an escalation, or an idempotent no-op, never an invented action or a double-execution.
- 👍 Reuses the existing worker measure loop, `action_drafts`, SSE/ticket auth, RLS role, and the local-first provider chain — small new surface.
- 👎 "Execution" is a labelled internal draft, not a real purchase order or warehouse transfer. That is deliberate (no connector exists) but means the demo must be honest about it, and a pilot needs the integration work in `PILOT_INTEGRATION_CHECKLIST.md` before any action leaves the building.
- 👎 Inventory evidence is stamped "now" because `metric_inventory_state` carries no observation timestamp, so the freshness gate protects the *finding*, not the seeded stock number. Documented; a real POS/inventory feed with timestamps closes it.
