# Security posture — Sage + the platform (defense in depth)

How the platform resists the named attack classes, where each defense lives,
and how it's continuously proven. The governing principle: **never trust the
LLM, never trust the client, enforce authorization in the data layer.** Every
attack class has ≥2 independent layers so one bug isn't a breach.

Proven by `backend/scripts/redteam_live.py` — a re-runnable adversarial loop
that fires the whole battery at the LIVE stack as real users and fails CI if
any vector succeeds (`--loop N` for N backtracking passes). Latest: **19/19
blocked**.

---

## Attack surface → defenses

### 1. Prompt injection / jailbreak
Goal: make the LLM ignore its rules, change scope, or leak the system prompt.

| Layer | Where | What |
|---|---|---|
| **Entry screen** | `guardrails/entry.py::screen_input` | ONE deterministic screen at the chat door (`/chat`, `/chat/stream`), BEFORE any lane or model. A jailbreak is refused here; no LLM ever sees it. |
| Input rails | `guardrails/rails.py` (`prompt_injection`, BLOCK/fail-closed) | Broad regex family: instruction-override, role-play (DAN/dev-mode), scope/RBAC manipulation ("pretend the filter is off"), "reveal system prompt", `### SYSTEM`, cross-tenant dump. |
| RAG pipeline rails | `rag/pipeline.py` | INPUT rails re-run inside the grounded path (defense in depth). |
| Prompt framing | `ai_assistant.py` | User text is delimited in `<user_question>` tags and marked data-not-instructions — a last line if a novel phrasing slips the regex. |

The LLM is the *last* line, not the first. A pattern miss degrades to
framing + the SQL/RBAC layers below, never to an executed injection.

### 2. SQL injection
Goal: exfiltrate/mutate via generated or user-influenced SQL.

| Layer | Where | What |
|---|---|---|
| **Allow-list guard** | `nl2sql/guard.py::validate_sql` | Single statement, no comments, SELECT/WITH only, forbidden-keyword *and* fragment denylist (`pg_`, `information_schema`, `set_config`, `current_user`, …), FROM/JOIN restricted to curated `sage_*` views, hard row cap. |
| **Least privilege** | `sage_ro` DB role (migration 023) | Generated SQL executes as a role with SELECT on `sage_*` views only — no tables, no writes, even if the guard were bypassed. |
| Read-only txn + timeout | `nl2sql/executor.py` | Statement timeout + read-only transaction. |
| Parameterization | everywhere else | All app queries use bound params (asyncpg/SQLAlchemy), never string interpolation. |

Result: `DROP TABLE`, `UNION SELECT password`, stacked `; DELETE` are all
rejected at the guard; tables verifiably intact after the attack battery.

### 3. Cross-role / cross-tenant data exfiltration
Goal: read another store's, role's, or tenant's data.

| Layer | Where | What |
|---|---|---|
| **JWT scope** | `routes/auth.py` | `tenant_id`, `role`, `allowed_stores` are embedded at login and set ONCE per request — the client can't widen them. |
| **API row scope** | every data router | Queries filter to `get_accessible_store_ids(user)`; a store manager's rows never include another store. |
| **RAG pre-retrieval ACL** | `rag/acl.py` (RAG-5) | Retrieval is filtered by role + store + sensitivity BEFORE scoring — a forbidden chunk is never retrieved, reranked, or cited. Threaded through Sage (`_run_doc`, `rag_agent`) this session. |
| **Store GUC** | migration 040 + `nl2sql/executor.py` | `app.allowed_store_ids` GUC enforces store scope in the DB for generated SQL. |
| Postgres RLS | migrations 010–020 | Defense-in-depth tenant isolation (opt-in `USE_RLS_ROLE`). |
| Cache scoping | `rag/cache.py`, `services/cache.py` | Cache keys fold in tenant+role+store `filter_hash` — a cached answer never crosses scopes. |

Asking Sage to "show all stores" or "as a super admin…" does **not** widen
what the caller can pull — verified: scope unchanged after widen-scope prompts.

### 4. Authorization bypass
Admin-only routes (bulk import, admin dashboards) depend on `require_role`;
a non-admin JWT is 403. UI gates are mirrored server-side so a direct API call
can't bypass them.

### 5. Path traversal
`routes/bulk_import.py::_safe_drop_path` confines every ingest path to the drop
dir via `realpath` prefix check — `../../app/config.py` is 400.

### 6. SSRF
`sage2/api_source.py::is_safe_url` blocks non-http(s) schemes and any private /
loopback / link-local / reserved target (incl. cloud metadata 169.254.169.254)
before an external source is fetched. Source URLs are operator-configured today;
this makes SSRF impossible even if that changes.

### 7. PII exfiltration
Output rails (`pii_output_leak`, BLOCK/fail-closed) veto an answer that would
emit a card/email/secret; input redaction strips PII from the query. A vetoed
answer degrades to the refusal, never leaks.

### 8. Abuse / DoS
Per-IP Redis sliding-window rate limit; body-size cap; session-invalidation
middleware (fail-closed on Redis down by default). Usage metering soft-caps
Sage per plan.

---

## Continuous verification

- **Unit** (`tests/`): `test_security_hardening.py` (entry screen + SSRF),
  `test_rag_redteam.py` (injection corpus), `test_nl2sql_guard.py` (SQL guard),
  `test_rag_acl.py` (ACL isolation), `test_rag_cache.py` (cache scoping).
- **Live loop** (`scripts/redteam_live.py`): the whole chain, as real users,
  re-runnable — the "backtracking" security regression gate.

## Known follow-ups (honest)
- Postgres RLS is defense-in-depth but `USE_RLS_ROLE` is off by default — turn
  it on in production for a second wall under the app-layer scope.
- The prompt-injection screen is regex + LLM-framing; add an LLM-classifier
  screen when a provider budget exists (the entry seam is already there).
