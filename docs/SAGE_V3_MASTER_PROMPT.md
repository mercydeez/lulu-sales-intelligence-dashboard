# Master Prompt — Build "Sage v3" Multi-Agent Chatbot in Retail IQ

> Paste this into Claude Code with the Retail IQ repo open as the working directory.
> It encodes everything needed to graft a 14-node LangGraph agent system onto the
> EXISTING chatbot infrastructure. Run it phase by phase — do NOT let it do everything
> in one shot.

---

```
You are upgrading the EXISTING chatbot in this repo (Retail IQ — a FastAPI + Postgres +
Next.js retail sales-intelligence dashboard) into a multi-agent graph called "Sage v3".

CRITICAL CONTEXT — READ BEFORE WRITING ANY CODE:
This repo ALREADY has a working chatbot. You are extending it, NOT rebuilding it. First,
read and understand these existing files so you reuse them instead of duplicating:
- backend/app/routes/ai.py            (chat SSE endpoints + RBAC gates + voice)
- backend/app/services/ai_assistant.py (current chat orchestration)
- backend/app/services/sage2/         (decompose→route→recompose orchestrator, intents)
- backend/app/services/nl2sql/        (NL→SQL pipeline, guard, executor, schema, prompt)
- backend/app/services/rag/retriever.py (document RAG)
- backend/app/services/llm/           (provider chain: Ollama → OpenAI → rule-based)
- backend/app/services/federation/    (multi-source adapters)
- backend/app/services/auth_service.py + routes/auth.py (RBAC, tenant, store scoping)
- backend/app/config.py               (pydantic-settings)
- CLAUDE.md and docs/SAGE_V3_AGENT_INTEGRATION.md (the plan you must follow)

HARD INVARIANTS (violating any of these is a failure):
1. Postgres only — NO DuckDB, NO new datastore. SQL goes through the existing nl2sql
   pipeline over the sage_* views / sales_fact_view.
2. LLM stays provider-agnostic via services/llm.get_provider_chain(). The system MUST
   still work with NO LLM configured (rule-based deterministic fallback). This is a
   project invariant — the demo runs with no paid API key.
3. RBAC is mandatory. tenant_id, allowed_stores, and role flow from the request into the
   graph's initial state and into EVERY SQL/RAG call. No node may widen data scope.
4. Preserve the units≠AED convention: VOLUME metrics in units, VALUE metrics in AED,
   never mixed on one axis (reference: backend/app/routes/kpis.py).
5. Backward compatible. The current /api/ai/chat must keep working. The new graph is
   gated behind a USE_SAGE_V3 setting (default false) for A/B and rollback.
6. Everything async (asyncpg / async LangGraph nodes).

TARGET: backend/app/services/sage3/ with a LangGraph state machine of these nodes:
router → intent (clarity score) → [clarification loop] → [readback gate] →
{sql_agent | rag_agent | planner→hybrid_executor→synthesiser} → critic →
[cross_validator → arbiter] → [completeness checker → reground] → finaliser.
Use Redis (services/redis_client.py) as the LangGraph checkpointer; fail open to
in-memory if Redis is down (mirror the SessionInvalidation pattern).

Each EXECUTION node is a THIN WRAPPER over existing services:
- sql_agent      → call the nl2sql pipeline (guard + sage_ro executor)
- rag_agent      → call services/rag.answer_from_docs
- planner        → reuse sage2 llm_decompose / deterministic intents
- hybrid_executor→ reuse sage2 + federation
- synthesiser    → reuse sage2 _recompose (keep the bold-line, source-attributed format)

Each NEW node (clarification, readback, critic, cross_validator, arbiter, completeness,
finaliser) gets a prompt in sage3/graph/prompts.py written for the RETAIL domain
(stores, regions, SKUs, sales units vs AED revenue, promotions, inventory/expiry).

VALIDATION STACK must be CONDITIONAL (for latency): simple single-source reads skip
straight to finaliser; only borderline (critic confidence 0.4–0.7) or multi-part answers
trigger cross_validator/arbiter/completeness.

WORK PHASE BY PHASE. After each phase, STOP, run the relevant tests, and summarize what
changed before continuing. Do not proceed to the next phase until I confirm.

PHASE 0 — Scaffolding (no behavior change):
  - Add langgraph + langgraph-checkpoint (and optional langfuse) to backend/requirements.txt.
  - Add USE_SAGE_V3: bool = False to app/config.py.
  - Create services/sage3/ skeleton: state.py (AgentState TypedDict including session_id,
    user_query, conversation_history, tenant_id, role, allowed_stores, route, intent,
    sql_result, rag_result, draft_answer, critic_verdict, final_answer, final_confidence,
    evidence, trace) + an orchestrator.py that wires ONLY:
    router → intent → (sql|rag|hybrid) → synthesiser → finaliser. No validation yet.
  - Compile the graph behind get_graph() with lru_cache.

PHASE 1 — Reuse-wrap executors + route flag:
  - Implement router/intent/sql_agent/rag_agent/planner/hybrid_executor/synthesiser as
    wrappers over existing services, threading RBAC fields through.
  - In routes/ai.py, when settings.use_sage_v3 is true, run the v3 graph and stream node
    outputs over the existing SSE channel; else keep the current path untouched.
  - Verify the existing multi-part golden questions still produce correct answers.

PHASE 2 — intent clarity + clarification loop (LLM optional, keyword fallback).
PHASE 3 — readback gate for complex/multi-part queries.
PHASE 4 — validation stack: critic → cross_validator → arbiter → completeness (+1 reground).
PHASE 5 — finaliser (confidence badge, collapsible SQL, citations, agent trace) + optional
          Langfuse tracing, env-gated.
PHASE 6 — frontend ChatBot: confidence badge, agent-trace "thinking" view, clarification
          prompt UI, readback confirm button, citations.
PHASE 7 — eval: port a golden-question harness, add 20 retail goldens (sql/rag/hybrid/
          ambiguous→clarify), and tests proving RBAC scope is never violated (mirror
          tests/test_ai_rbac.py and tests/test_ai_safety.py).

Start with PHASE 0 now. Before writing code, give me a short numbered confirmation of:
(a) which existing functions you will call from each wrapper node, and
(b) what backs services/rag/retriever.py (pgvector? in-memory?) — because we must NOT add
    Qdrant unless the retriever already requires a vector server.
```

---

## How to use this prompt

1. Open a terminal in the Retail IQ repo root.
2. Run `claude` (or open the repo in your IDE with Claude Code).
3. Paste the fenced block above as your first message.
4. Answer its Phase 0 confirmation questions, then approve each phase one at a time.
5. Test after every phase: `docker exec sales_backend python -m pytest tests/ -v`.
6. Flip `USE_SAGE_V3=true` in your env only after Phase 1 parity passes.
