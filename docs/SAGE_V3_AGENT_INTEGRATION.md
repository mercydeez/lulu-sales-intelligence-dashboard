# Sage v3 — Multi-Agent Chatbot Integration Plan

> Goal: upgrade Retail IQ's existing "Sage v2" chatbot into a 14-node multi-agent
> graph (ported conceptually from the TechNova LangGraph chatbot), adding a
> self-validation stack, clarification loop, readback gate, and confidence scoring —
> while **reusing** the existing `nl2sql`, `rag`, `llm`, `federation`, RBAC, and
> SSE infrastructure. We keep Postgres, keep Ollama-first fallback, keep tenant/RLS.

---

## 1. What we already have vs. what we add

| Capability | Status in Retail IQ | Action |
|---|---|---|
| NL→SQL with guard + least-privilege role | ✅ `services/nl2sql/` | **Reuse** as SQL Agent node |
| Document RAG | ✅ `services/rag/retriever.py` | **Reuse** as RAG Agent node |
| Multi-part decompose→recompose | ✅ `services/sage2/` | **Reuse** as Planner + Synthesiser |
| LLM provider chain (Ollama→OpenAI→rule) | ✅ `services/llm/` | **Reuse** everywhere |
| Federated multi-source | ✅ `services/federation/` | **Reuse** in Hybrid Executor |
| RBAC / tenant / store scoping | ✅ `routes/ai.py`, `auth_service` | **Reuse** — inject into agent state |
| SSE streaming chat | ✅ `routes/ai.py` | **Reuse** — graph streams node-by-node |
| Voice STT/TTS | ✅ `services/voice_service` | **Reuse** unchanged |
| **Graph state machine (LangGraph)** | ❌ linear async funcs | **BUILD** — `services/sage3/graph/` |
| **Intent clarity scoring** | ⚠️ partial (keyword intents) | **EXTEND** with LLM clarity score |
| **Clarification loop** | ❌ | **BUILD** |
| **Readback gate** | ❌ | **BUILD** |
| **Critic (confidence)** | ❌ | **BUILD** |
| **Cross-Validator + Arbiter** | ❌ | **BUILD** |
| **Completeness checker** | ❌ | **BUILD** |
| **Per-answer confidence + trace** | ❌ | **BUILD** |

---

## 2. Architectural rules (do NOT violate these)

1. **Postgres stays.** No DuckDB. SQL Agent calls the existing `nl2sql` pipeline
   over `sage_*` views / `sales_fact_view`.
2. **LLM stays provider-agnostic.** Every node calls `services/llm.get_provider_chain()`.
   Must degrade gracefully to the rule-based responder when no provider is configured
   (this is a hard project invariant — the demo runs with no paid key).
3. **RBAC is non-negotiable.** `tenant_id` + `allowed_stores` + `role` flow into the
   graph's initial state and are passed to every SQL/RAG call. No node may widen scope.
4. **Units ≠ AED.** The synthesiser/finaliser must preserve the project convention:
   VOLUME in units, VALUE in AED, never mixed on one axis (see `routes/kpis.py`).
5. **Backward compatible.** Old `/api/ai/chat` keeps working. New graph lives behind
   a feature flag (`USE_SAGE_V3=true`) so we can A/B and roll back.
6. **Async throughout.** Existing code is `async`/asyncpg. LangGraph nodes are async.

---

## 3. Target module layout

```
backend/app/services/sage3/
  __init__.py
  state.py              # AgentState TypedDict (ported, + tenant_id/role/allowed_stores)
  orchestrator.py       # builds + compiles the LangGraph; get_graph()
  graph/
    router.py           # reuse sage2 route decision
    intent.py           # reuse sage2/intents + LLM clarity score
    clarification.py     # NEW
    readback.py          # NEW
    planner.py           # wraps sage2 llm_decompose / deterministic
    sql_agent.py         # wraps services/nl2sql pipeline
    rag_agent.py         # wraps services/rag.answer_from_docs
    hybrid_executor.py   # wraps sage2 + federation
    synthesiser.py       # wraps sage2 _recompose
    critic.py            # NEW
    cross_validator.py   # NEW
    arbiter.py           # NEW
    completeness.py      # NEW
    finaliser.py         # NEW
    prompts.py           # all node prompts, retail-domain-specific
```

Checkpointer: use the existing Redis (`services/redis_client.py`) via a Redis
checkpointer; fall back to in-memory if Redis is down (mirror the SessionInvalidation
"fail open" pattern).

---

## 4. Phased implementation

**Phase 0 — Scaffolding (no behavior change)**
- Add `langgraph`, `langgraph-checkpoint`, (optional) `langfuse` to `backend/requirements.txt`.
- Create `services/sage3/` skeleton with `state.py` + an orchestrator that wires only
  Router → Intent → SQL/RAG/Hybrid → Synthesiser → Finaliser (no validation yet).
- Add `USE_SAGE_V3` setting to `app/config.py` (default false).

**Phase 1 — Reuse-wrap the executors**
- Implement `sql_agent.py`, `rag_agent.py`, `hybrid_executor.py`, `planner.py`,
  `synthesiser.py` as thin wrappers that call the EXISTING services and write results
  into `AgentState`. Pass `tenant_id`/`allowed_stores`/`role` from state into every call.
- Wire `routes/ai.py` `/chat/stream` to use the v3 graph when `USE_SAGE_V3` is set.
- Verify parity: the old multi-part golden questions still produce correct answers.

**Phase 2 — Intent clarity + clarification loop**
- Extend `intent.py` to ask the LLM for a `clarity_score` + `ambiguities` (fall back to
  keyword-only when no LLM). Add `clarification.py` that emits a follow-up question and
  loops back through intent (cap at 2 rounds). Stream the question to the user via SSE.

**Phase 3 — Readback gate**
- `readback.py`: for complex/multi-part or write-shaped queries, paraphrase the plan and
  ask for confirmation before executing. Approve-by-default for simple reads.

**Phase 4 — Validation stack (the headline feature)**
- `critic.py`: score the draft answer (grounding, completeness, units/AED correctness)
  → confidence 0–1 + verdict pass/retry/uncertain/fail.
- `cross_validator.py`: independent re-check for borderline (0.4–0.7) answers.
- `arbiter.py`: tie-break when critic and cross-validator disagree.
- `completeness.py`: recall gate — "did we answer every sub-question / cover all stores
  in scope?"; allow ONE reground retry.

**Phase 5 — Finaliser + observability**
- `finaliser.py`: format final answer with confidence badge, SQL shown (collapsible),
  citations, and a human-readable agent trace. Stream incrementally.
- Wire Langfuse (optional, env-gated) to trace every node hop.

**Phase 6 — Frontend**
- Update `frontend` ChatBot component to render: confidence badge, "thinking" trace
  (which agents fired), clarification prompts, readback confirm button, citations.

**Phase 7 — Eval + hardening**
- Port the golden-question eval harness; add 20 retail goldens (SQL, RAG, hybrid,
  ambiguous→clarify). Assert RBAC scoping is never violated. Add tests mirroring
  `test_ai_rbac.py` / `test_ai_safety.py` for the new nodes.

---

## 5. Risks / decisions to make

- **Latency:** 14 nodes × LLM calls is slow on Ollama. Mitigation: only run the
  validation stack for borderline/complex answers (conditional edges, as TechNova does);
  simple reads skip straight to finaliser.
- **Cost:** if OpenAI is enabled, cap validation passes. Keep rule-based fallback fast.
- **Vector store for RAG:** Retail IQ's `rag/retriever.py` — confirm what backs it
  (pgvector? in-memory?). TechNova uses Qdrant; do NOT add Qdrant unless retriever needs
  it. Prefer pgvector to stay single-datastore.
- **Checkpoint store:** Redis is already a dependency — use it, fail open.
```
