# Implementation Plan — Retail Intelligence Platform

> Living remediation plan. Created after recovering the full product (`b888b34`) and
> auditing it against the Retail Intelligence vision. Tracks the gap-closing work:
> **promote → verify → fix real gaps**, not rebuild. Keep this in sync as steps land.

## Product vision
A Retail Intelligence Platform that runs the full loop **detect → diagnose → predict →
recommend → act → measure**, with **Sage** as a grounded, RBAC-safe assistant that answers
only from permitted business data, refuses out-of-scope questions, never invents numbers,
and respects tenant + store scope.

## Current verified repo state
- Branch `prototype-evolution-accuracy-bullmq` @ `b888b34` (146-commit product), promoted from a
  thin orphan snapshot `e5402e1`. Safety refs: `backup/e5402e1-cookie-auth`, `recovery/*`
  (local + origin).
- Real today: live SSE pipeline; tenant-scoped KPIs/analytics; backtested forecasting
  (MAPE/WAPE, LightGBM + optional deep tier); rebrand + centralized `product_name="Retail IQ"`,
  `chatbot_name="Sage"`; Sage NL→SQL engine (`sage_ro` least-priv role + `app.tenant_id` GUC/RLS)
  on the public API; BullMQ diagnostics worker → findings → recommended actions.
- Open gaps (this plan): in-app chat scopes tenant but **not store**; no server-side AI permission
  gate; client-trusted chat `session_id`; weak chat-path guardrails; missing AI safety tests;
  httpOnly cookie auth (only existed on the discarded `e5402e1`); README honesty.

## Runtime verification (Docker)
Stack: `postgres`, `redis`, `backend`, `frontend`, `worker` (Node/BullMQ); `ollama` behind the
`ai` profile (off by default).

| Check | Result |
|---|---|
| `docker compose config -q` | ✅ valid |
| `docker compose up -d --build` | ✅ all 5 services Up |
| `/health` | ✅ `{"status":"healthy","database":"healthy","redis":"healthy"}` |
| `curl -I :3000` | ✅ `200 OK` + full CSP/security headers |
| Migrations 014–033 | ✅ applied (verified via `schema_migrations`); data seeded |
| Worker diagnostics scan | ✅ after fix — 41 findings / 2 tenants (e.g. "Dairy revenue down 58.6%") |
| `pytest tests/` (in-container) | ✅ **187 passed, 8 skipped**; remaining non-passes are environment artifacts only (below) |

**Test baseline = GREEN (with documented environment artifacts).** Running the suite *inside the
backend container* produces a few non-passes that are **not product defects** and pass on host/CI:
- `test_tenant_isolation` file-existence checks (2) — compute `/database/migrations` but the backend
  image copies only `backend/` (the real copy is `/app/database`); pass from the repo root (host/CI).
- `test_golden_numbers` (5) — `TimeoutError` only under heavy concurrent load (forecast trainer +
  generator + parallel test run); **pass in isolation**.
- `test_forecasting_engine` — the optional deep tier (torch LSTM/GRU/CNN) trains very slowly on CPU
  and stalls the in-container run; excluded from the baseline tally. Classical/LightGBM forecasting
  tests (`test_forecast_service`) pass.
- `test_api.py` — a live aiohttp/SSE script (not a unit test); excluded.

**Known runtime note — `worker_rw` auth:** on a *stale* Postgres volume the worker can fail with
`password authentication failed for user "worker_rw"`. Root cause: migration `029_worker_role.sql`
only sets the role password in its `CREATE` branch; on a volume where the role pre-existed it took
the `ELSE` (attributes-only) path and never set a password. Fix applied in-place
(`ALTER ROLE worker_rw PASSWORD 'worker_rw_dev_pass'`, persisted in the volume). A fresh
`docker compose down -v && up` works via the `CREATE` branch.

## Prioritized roadmap (only real gaps)
- **P0 — security/trust/runtime:** promote ✅; runtime baseline ✅(pending tests); store-scope chat;
  server-side AI permission; bind session to user; AI safety tests.
- **P1 — credibility:** chat-path guardrail prompt; branding straggler; httpOnly cookie auth +
  cookie blacklist; README honesty.
- **P2 — intelligence loop:** verify detect→…→act (worker→findings→actions) end-to-end; add the
  smallest "measure/outcome" gap only.
- **P3 — cleanup:** dead mock data, duplicate API clients, duplicate forecasters, stale cruft, deps.

## Step ledger
| # | Step | Status |
|---|---|---|
| 0 | Promote `b888b34` (reset + force-push) | ✅ done |
| 1 | Runtime baseline (Docker) | ✅ green (187 passed; artifacts documented) |
| 2 | This plan committed to repo | ✅ done |
| 3 | P0.1 store-level scoping in chat | ✅ done (`e15b3a2`) |
| 4 | P0.2 server-side AI permission gate | ✅ done (`498afe4`) |
| 5 | P0.3 bind chat session to user | ✅ done (`dd61ef8`) |
| 6 | P1.2 grounded refusing guardrail prompt | ✅ done (`e92e49c`) |
| 7 | P0.4 consolidate AI safety tests (`test_ai_rbac.py`, 10 tests) | ✅ done (`e92e49c`) |
| 8 | P1.1 branding straggler (`ai_assistant.py`) | ✅ done (`e92e49c`) |
| 9 | P1.3 httpOnly cookie auth + cookie blacklist | 🟡 next |
| 10 | P1.4 README honesty pass | ⬜ |
| 11 | P2 verify intelligence loop; minimal measure/outcome gap | ⬜ |
| 12 | P3 cleanup | ⬜ |

**Milestone:** all P0 (AI RBAC/permission/session/safety-tests) + P1.1/P1.2 (branding,
guardrails) landed; `test_ai_rbac.py` = 10 tests green; regression across AI/RBAC/Sage/
federation/security suites = 68 passed, 1 skipped, 0 regressions.

## Per-step detail (acceptance · tests · files · rollback)

### Step 3 (P0.1) — Store-level scoping in chat
Thread `allowed_stores` (from `get_accessible_store_ids(current_user)`, `routes/auth.py:630`) through
`stream_chat_response`/`get_chat_response` → `build_data_context` → the `get_*` data functions →
`get_intelligent_fallback`/`get_dashboard_summary`; filter `Sale.store_id.in_(allowed_stores)` and the
`store_name` lookup when the list is non-empty (empty = super_admin = all). Defense-in-depth on top of
the existing `tenant_id` scoping.
- **Accept:** store_manager (`accessible_stores=[1]`) asking "all stores" sees only store 1; asking a
  store they can't access is refused/empty. Super-admin/regional unchanged.
- **Files:** `backend/app/services/ai_assistant.py`, `backend/app/routes/ai.py`.
- **Test:** `tests/test_ai_rbac.py::test_store_manager_scope`. **Rollback:** revert commit.

### Step 4 (P0.2) — Server-side AI permission gate
Add a `require_ai_chat` dependency on `/api/ai/chat*` and voice endpoints mirroring the UI rule
(roles super_admin/regional_manager/store_manager **or** `can_use_ai_chat`). `can_use_ai_chat` is
currently frontend-only — enforce server-side so a direct API call can't bypass the UI gate.
- **Accept:** a user without access gets 403 on a direct `curl` to `/api/ai/chat`.
- **Files:** `backend/app/routes/ai.py` (+ optional permission seed). **Test:** `test_ai_rbac.py::test_permission_denied`.

### Step 5 (P0.3) — Bind chat session to the authenticated user
Namespace the in-memory conversation store by user id (`key = f"{user_id}:{session_id}"`); `clear`
and `summary` only touch the caller's namespace.
- **Accept:** user A cannot read/clear user B's context. **Files:** `ai_assistant.py`, `routes/ai.py`.
- **Test:** `test_ai_rbac.py::test_session_isolation`.

### Step 6 (P1.2) — Grounded, refusing guardrail prompt
Rewrite `get_system_prompt`: answer only from the provided DATA context; refuse out-of-scope; never
invent numbers; say when data is unavailable; respect RBAC scope; summarize the data basis. Remove the
"NEVER say you don't have access" instruction. Delimit user input in the enhanced message vs injection.
Keep the deterministic fallback grounded.
- **Accept:** out-of-scope → refusal; injection can't exfiltrate other-store data (defense in depth on
  Step 3). **Files:** `ai_assistant.py`. **Test:** injection + out-of-scope + says-unknown in `test_ai_rbac.py`.

### Step 7 (P0.4) — Consolidate AI safety tests
`tests/test_ai_rbac.py` mirroring `tests/test_rbac.py` harness (mock users + `dependency_overrides`):
tenant scope, store scope, permission denial, session isolation, prompt-injection refusal,
out-of-context refusal, grounded-numbers/says-unknown. **Test:** `pytest tests/test_ai_rbac.py -v`.

### Step 8 (P1.1) — Branding straggler
`ai_assistant.py:535` hardcodes "Historical data from 2013-2017 (913,000+ records)" — verified true by
`tests/test_golden_numbers.py`, but source it honestly rather than as a literal claim; grep-sweep any
residual `Lulu AI`/`Lulu Hypermarket`. **Accept:** no stale strings; claims sourced.

### Step 9 (P1.3) — httpOnly cookie auth + cookie blacklist (port from `e5402e1`)
`routes/auth.py`: cookie helpers (`set/clear_auth_cookies`, `_cookie_kwargs`, `ACCESS_COOKIE`/
`REFRESH_COOKIE`); make `get_current_user`/`_optional` accept Bearer **or** cookie **without dropping**
b888b34's security-event logging, tenant-tamper rejection, `tenant_context` RLS binding; wire
login/refresh/signup to set cookies, logout to clear. `middleware.py`: `SessionInvalidationMiddleware`
also hash-checks the cookie token. Frontend `AuthContext.tsx` + fetch wrapper: `credentials:'include'`.
- **Accept:** login sets httpOnly cookies; cookie-only auth works; logout clears+blacklists; tenant
  tamper still rejected. **Test:** `test_tokens.py`/`test_security.py` cookie cases.

### Step 10 (P1.4) — README honesty pass
Align README to reality after fixes: synthetic data, units vs AED, what Sage can/can't do, what
forecasting predicts, what's not built. **Accept:** no claim contradicts code.

### Step 11 (P2) — Verify & minimally complete the intelligence loop
Confirm worker→findings→recommended_action→accept-action runs end-to-end; assess whether a
"measure/outcome" record exists. **If a real gap, update this plan with exact scope and confirm before
building** (large changes gated). Keep additions minimal.

### Step 12 (P3) — Cleanup (only after tests pass)
Re-evaluate post-promotion: stale `__pycache__`; `inventory/mockData.ts`; duplicate API clients
(`lib/api.ts` vs `lib/apiClient.ts`); duplicate forecasters (`predictor.py` vs `forecasting/engine.py`);
unused deps. Remove/simplify with tests green after each.

## Intentionally deferred
- Migrating the in-app ChatBot to the NL→SQL Sage engine (chose "harden legacy now").
- Voice expansion; multi-source federation beyond Postgres; agentic autonomy beyond level 0.

## Rollback (global)
- Undo promotion: `git reset --hard backup/e5402e1-cookie-auth`. Per-step: revert the single commit.
- Recovered work is triple-protected: `recovery/*` (local + origin), `backup/e5402e1-cookie-auth`, reflog.
