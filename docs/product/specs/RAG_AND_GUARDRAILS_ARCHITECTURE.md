# RAG & Guardrails — production architecture & framework

> Originally the planning doc; the pipeline is now IMPLEMENTED — see §0.5 for
> the stage→module map and `services/rag/pipeline.py` for the orchestrator.
> Builds on `SAGE_GROUNDED_INTELLIGENCE.md` (four-tier answering) and
> `STAGE1_SEMANTIC_LAYER.md` (pgvector foundation). This doc goes deep on the
> **RAG pipeline** and the **guardrail system** (all types), and on the one thing
> most RAG builds get wrong: **RBAC-aware retrieval** — the model must never see,
> retrieve, or cite what the caller isn't allowed to.

---

## 0. Framing — challenge the premise first

**"Implement RAG throughout the SaaS" is the wrong goal if taken literally.**
RAG is a tool for *unstructured knowledge*. Our product is mostly *structured
numbers* (sales, inventory, forecasts). The #1 RAG pitfall here would be routing
"what was Dubai revenue last week?" through vector search — you'd get a fuzzy,
possibly-wrong number. That question must go to **SQL over curated views**, not RAG.

So the honest framing: **RAG is one lane in a router**, used for:
- product knowledge / docs / runbooks / policies / changelog
- findings *narratives* and decision *rationales* (the "why", in prose)
- the tenant **Product State** pack ("what's happening") — retrieved, then
  narrated with citations to SQL-computed evidence

Numbers always come from SQL (the existing `nl2sql` guard path). **RAG narrates;
it never computes.** Keeping that boundary is 80% of "accuracy."

---

## 0.5 Zero-hallucination pipeline — implementation map (10 stages, all live)

One call runs the whole thing: `rag/pipeline.py::answer_grounded()`.

| # | Stage | Module | Notes |
|---|-------|--------|-------|
| 1 | Ingest + normalize | `rag/ingest.py` | content-hash dedup; **versioning**: re-ingest supersedes stale chunks of the same doc |
| 2 | Hybrid retrieval | `rag/retriever.py` + `fusion.py` | BM25 ∪ vector, RRF; RBAC filter BEFORE scoring |
| 3 | ANN + rerank | `idx_documents_embedding` (HNSW) + `rag/rerank.py` | two-stage: ANN candidates → lexical cross-scorer |
| 4 | Source confidence | `rag/confidence.py` | freshness × trust × cross-arm consistency × overlap; floor 0.30 filters weak evidence |
| 5 | Constrained generation | `rag/pipeline.py` | context-only prompt (LLM) or extractive top-chunk; no external knowledge |
| 6 | Citation-backed | `rag/rerank.py::assemble_context` | every answer carries its citations; enforcement rail vetoes uncited output |
| 7 | Hallucination fallback | `rag/pipeline.py` | aggregate confidence < **0.45** → honest "insufficient evidence", never a guess; refusals not cached |
| 8 | Continuous evals | `rag/evaluation.py` + red-team tests | recall/MRR gates, 6 injections blocked, 53 tests in CI |
| 9 | Caching + memory | `rag/cache.py` | answer + embedding cache keyed by tenant+role+store filter_hash (never leaks across scopes) |
| 10 | Observability | `rag/observability.py` | per-answer `RagTrace`: stage latencies, arm counts, trips, refusals |

Guardrails (`services/guardrails/`) wrap both ends: INPUT rails run before
stage 2 (injection block, PII redaction), OUTPUT rails after stage 5
(faithfulness, citation enforcement, PII leak, numeric sanity) — a vetoed
answer degrades to the stage-7 refusal, never to an unchecked reply.

---

## 1. The RAG pipeline, end-to-end (with trade-offs, not just picks)

### 1.1 Ingestion
- **Sources:** uploaded docs (PDF/DOCX/CSV notes), runbooks, changelog, policy
  text, findings narratives, metric-registry descriptions, NL2SQL exemplars,
  Product-State slices. Each is a *corpus* with its own trust level.
- **Pipeline:** extract → normalize (strip boilerplate) → chunk → embed →
  upsert with metadata. Idempotent by `(tenant_id, source, ref_id, chunk_no,
  content_hash)` so re-ingest doesn't duplicate.
- **Trade-off:** ingest-time enrichment (summaries, titles, extracted entities)
  costs more but massively improves retrieval. Do it for high-value corpora
  (policies, runbooks), skip for ephemeral ones.
- **Pitfall:** PDF extraction garbage (tables, headers) poisons retrieval. Gate
  ingestion on an extraction-quality check; quarantine low-confidence extracts.

### 1.2 Chunking — strategy matters more than model
- **Options & trade-offs:**
  - *Fixed-size (token) + overlap* — simple, predictable; splits mid-thought. OK baseline.
  - *Recursive/structural* (by heading/section/paragraph) — respects meaning;
    best for docs/runbooks. **Recommended default.**
  - *Semantic chunking* (split on embedding-distance shifts) — highest quality,
    higher ingest cost; use for the policy/knowledge corpus.
  - *Sentence-window / parent-doc* — embed small, return the surrounding parent
    on hit. Excellent for precision+context; more storage.
- **Recommendation:** structural chunking, ~300–500 tokens, 15% overlap, with
  **parent-document retrieval** (embed the chunk, return its section). Store
  `parent_ref` in metadata.
- **Pitfall:** one chunk size for all corpora. A changelog entry, a 40-page
  runbook, and a one-line finding need different granularity. Chunk per corpus.

### 1.3 Embeddings — model selection
- **Axes:** quality (MTEB retrieval), dimension (storage/latency), local-vs-hosted
  (PDPL/cost), max sequence length, multilingual (**we need Arabic**).
- **Candidates:**
  - `all-minilm` (384d, local/Ollama) — cheap, fast; **weak on Arabic**, mediocre quality.
  - `bge-m3` / `multilingual-e5-large` (1024d) — strong multilingual (Arabic!),
    local-capable, bigger vectors.
  - OpenAI `text-embedding-3-small/large` — strong, hosted (PDPL trade-off), pay-per-token.
- **Recommendation:** start `all-minilm` (already wired in `embeddings.py`) to
  ship the pipeline, but plan a swap to a **multilingual model (bge-m3)** before
  any Arabic-content retrieval — English-only embeddings will silently fail on
  Arabic queries. The `embedding_model` tag already lets us re-embed without
  downtime.
- **Pitfall (already designed against):** mixing embedders. Query and doc
  vectors MUST share a model tag — enforced by `documents.embedding_model`.

### 1.4 Vector database — the real trade-off analysis
| Option | For us | Against |
|---|---|---|
| **pgvector** (current) | one system, RLS = tenant isolation for free, transactional with the data, no new ops | slower at >10M vectors, HNSW rebuilds, no native hybrid |
| **Qdrant** | fast ANN, native payload filters + hybrid, horizontal scale | another service to run/secure, tenant isolation is app-enforced (no RLS) |
| **Weaviate / Milvus** | feature-rich, hybrid built-in | heavier ops, overkill at our scale |
| **pgvector + pgvectorscale (StreamingDiskANN)** | pgvector's isolation + near-Qdrant speed | newer extension, another dependency |
- **Decision:** **pgvector now** (the isolation-for-free from RLS is worth more
  than raw speed at our tenant count), with **pgvectorscale** as the in-place
  upgrade and **Qdrant** reserved for >100 tenants / >10M chunks. Don't adopt a
  dedicated vector DB before the isolation story is worth re-solving outside RLS.

### 1.5 Metadata schema (this is where RBAC lives — see §3)
Per chunk: `tenant_id`, `corpus`, `ref_id`, `chunk_no`, `parent_ref`,
`content`, `embedding`, `embedding_model`, `source`, `created_at`,
`visibility` (roles/permissions that may see it), `store_scope` (store ids or
null=all), `sensitivity` (public/internal/restricted), `lang`, `content_hash`.
**Metadata is not decoration — it's the security boundary and the rerank signal.**

### 1.6 Indexing
- HNSW (cosine) `m=16, ef_construction=64`, `ef_search` tuned per latency budget.
- Partial index on `WHERE embedding IS NULL` (backfill) — already in migration 054.
- **Hybrid needs a BM25/tsvector index too** (already have `documents.tsv`).
- Re-index strategy for model swaps: dual-write new tag, cut over, drop old.

### 1.7 Retrieval — semantic + hybrid + rerank
1. **Pre-filter (hard):** tenant + RBAC + corpus + freshness (see §3) — applied
   in SQL WHERE before ANN, so ANN only ever scores permitted chunks.
2. **Hybrid:** BM25 (tsv) ∪ vector (cosine) → **Reciprocal Rank Fusion**
   (`rag/fusion.py` already built) — robust to the two incomparable score scales.
3. **Rerank (stage 2):** a cross-encoder (bge-reranker / cohere-rerank) over the
   top ~20 fused → top ~5. Biggest single accuracy lever after hybrid; adds
   latency+cost, so gate behind a flag and only for T2 answers.
- **Pitfall:** retrieving top-k by similarity alone. Similarity ≠ relevance;
  rerank is what closes that gap. And **more chunks ≠ better** — noise dilutes.

### 1.8 Context assembly
- Dedup near-identical chunks; order by rerank score; **respect a token budget**
  (reserve room for the answer). Parent-doc expansion on the top hits only.
- Every chunk carries an inline citation id the narrator must reference.
- **Pitfall:** "lost in the middle" — LLMs under-attend to mid-context. Put the
  strongest evidence first and last.

### 1.9 Prompt construction
- System prompt: role/persona (from `role_experience`), the **grounding
  contract** ("answer ONLY from the provided context; if it's not there, say so
  and stop"), citation format, units≠AED honesty, refusal instruction.
- Structured: pass context as delimited blocks with ids; ask for citations.
- **Pitfall:** stuffing instructions the model ignores. Keep the grounding
  contract short, explicit, and reinforced by an *output* guardrail (§2).

### 1.10 Hallucination mitigation (defense in depth)
- Grounding contract in the prompt (necessary, insufficient).
- **Post-hoc faithfulness check:** a cheap verifier (NLI model or LLM-judge)
  scores whether the answer is entailed by the retrieved context; below
  threshold → refuse/regenerate.
- **Citation enforcement:** every claim must map to a chunk id; unciteable
  claims are stripped or trigger refusal.
- **Self-consistency** for high-stakes: sample twice, disagree → clarify.
- **Calibrated refusal** counts as correct (the honesty convention).

### 1.11 Evaluation (you can't improve what you don't measure)
- **Retrieval:** recall@k, MRR, nDCG on a labeled query→relevant-chunk set.
- **Generation:** faithfulness/groundedness, answer-relevance, citation coverage
  (RAGAS-style), plus exact-match for any number (must equal the SQL truth).
- **End-to-end:** golden Q/A set in CI (seed from `ai_evals.py`), scenario
  replays for "what's happening & why", **RBAC-leak tests** (§3), red-team suite.
- **Gate CI** on: recall@k ≥ target, faithfulness ≥ target, **0 RBAC leaks**,
  **0 fabricated numbers**.

### 1.12 Caching
- **Embedding cache** (content_hash → vector) — never re-embed unchanged text.
- **Semantic cache**: embed the question; cosine-near a *previously verified*
  answer (same tenant + same RBAC scope + TTL) → serve cached. **Careful:** the
  cache key MUST include the RBAC scope or you leak across roles. Fail-safe: on
  any scope mismatch, miss.
- Retrieval result cache keyed on (query_embedding_bucket, filter_hash).

### 1.13 Scalability
- Reads are pure SELECTs → route to a **read replica** (E10-7).
- Rerank + embed are the hot CPU paths → separate worker/queue, autoscale.
- Ingestion is bursty → queue + batch (mirror the K1 telemetry buffer pattern).
- Cache hit-rate is the cheapest scaler; instrument it.

### 1.14 Security & multi-tenancy → **see §3 (the core ask)**

### 1.15 Cost optimization
- Route by tier: most traffic is T0/T1 (no LLM / small local). Reserve the
  hosted LLM + rerank for T2/T3.
- Semantic + embedding caches cut the biggest line items.
- Small local embedder by default; hosted only when quality demands.
- Token budgeting in context assembly caps per-answer cost.
- **Pitfall:** reranking/embedding everything. Gate expensive stages on need.

### 1.16 Observability
- Per stage: retrieval latency, #candidates, fused/rerank scores, faithfulness
  score, refusal rate, cache hit-rate, tokens, cost, guardrail trips.
- A rising **refusal rate = retrieval gap** (fix the corpus), not a model problem.
- Trace id per answer linking query → chunks → prompt → answer → verdict, into
  telemetry (`CX_LOOPS_PLAN.md`) / Sentry.

---

## 2. Guardrails — the full taxonomy & where each runs

Think of it as **three gates** (INPUT → RETRIEVAL → OUTPUT) plus cross-cutting
(STRUCTURAL, SEMANTIC, ACTION, COST). Each guardrail declares **fail-open vs
fail-closed** — security guardrails fail *closed*, UX ones fail *open*.

### 2.1 INPUT guardrails (before anything runs)
- **PII detection/redaction** — strip/责 mask emails, phone, IDs from the query
  before it hits logs/LLM (fail-closed on obvious secrets).
- **Prompt-injection / jailbreak detection** — classifier + heuristics ("ignore
  previous instructions", role-play escapes). Fail-closed.
- **Topical scope** — is this about the user's retail operation? Off-topic →
  polite refusal (the moat: Sage answers about *your data*, or declines).
- **Abuse / rate / token limits** — max query length, per-user quota (ties to
  usage metering), repeated-query throttle.
- **Language/encoding** — normalize; detect Arabic to pick the right embedder/prompt.

### 2.2 RETRIEVAL guardrails (the security boundary)
- **Tenant isolation** — RLS + explicit `tenant_id` filter (never trust one alone).
- **RBAC/ACL filter** — chunk `visibility`/`store_scope`/`sensitivity` vs the
  caller's grants (§3). Fail-closed.
- **Source allowlist** — only approved corpora for this query type.
- **Freshness/staleness** — exclude expired docs; prefer recent for time-sensitive Qs.

### 2.3 OUTPUT guardrails (before the answer reaches the user)
- **Groundedness/faithfulness** — answer entailed by context? (§1.10). Fail-closed → refuse.
- **Citation enforcement** — claims map to chunk ids.
- **PII/secret leakage** — scan the *answer* for anything sensitive that slipped through.
- **Toxicity/safety** — standard content safety.
- **Relevance** — does the answer address the question? (avoid confident non-answers).
- **Honesty/units** — units≠AED convention; "insufficient data" over a guess.

### 2.4 STRUCTURAL guardrails
- **Schema-constrained output** — JSON-schema / function-calling / grammar so the
  model *cannot* emit malformed structure (for decisions, actions, extractions).
- **The SQL allowlist guard** (`nl2sql/guard.py`) — already the gold-standard
  structural guardrail: single SELECT, curated views only, row cap, read-only role.
  This is the template for all "the LLM proposes, a validator disposes" flows.

### 2.5 SEMANTIC guardrails
- **Answer-relevance & contradiction** — does it contradict the context or itself?
- **Confidence thresholds** — low retrieval/faithfulness confidence → clarify or refuse.
- **Numeric sanity** — any number is cross-checked against the metric registry's
  historical range + unit; magnitude/unit mismatch → block.

### 2.6 ACTION guardrails (agentic / writes)
- **Human-in-the-loop** for any state change (draft → approve), per `approval_rules`.
- **Per-action-type kill switch** and audit (matches the E10-1 autonomy design).
- Least-privilege execution role; never let the LLM's output directly mutate data.

### 2.7 COST guardrails
- Per-request + per-tenant token/$ budgets; degrade to the deterministic/template
  path when exceeded rather than failing.

### 2.8 The guardrail architecture (framework)
- A **`GuardrailPipeline`** with ordered, declarative stages, each: `name`,
  `phase` (input/retrieval/output), `severity` (block/warn/log), `fail_mode`
  (open/closed), `check(ctx) -> Result`. Config-driven so new guardrails are
  added, not hard-wired. Every trip is logged with the trace id.
- **Layering, not a single check:** input classifier + retrieval filter + output
  verifier together. No single guardrail is trusted alone (defense in depth) —
  same philosophy as the SQL guard's layered checks.

---

## 3. RBAC-aware retrieval — "admin sets a role → the pipeline knows what it can see"

**This is the differentiator and the part most RAG systems get dangerously wrong.**
The model, the retriever, and the cache must all respect the caller's authorization.

### 3.1 The principle
> The AI can only ever retrieve, read, cite, or act on what the *authenticated
> caller* is authorized to see — derived from the SAME RBAC source the data
> routes use, never a parallel/looser copy.

### 3.2 The pipeline (admin grant → backend → retrieval)
1. **Admin assigns a role/permissions** (existing admin UI → `users` /
   `user_permissions`).
2. **Auth aggregates** the effective grants at login (`auth_service` →
   `permissions`, `role`, `accessible_stores`, `tenant_id`) — already embedded
   in the JWT.
3. **Every AI request carries that context** (the request is already scoped;
   `sage3/runtime` passes `tenant_id/role/allowed_stores` into the graph — extend
   it to carry the full permission set).
4. **Retrieval derives a hard filter** from the grants:
   `tenant_id = :tid AND (visibility_roles && :roles OR visibility_public)
    AND (store_scope IS NULL OR store_scope && :accessible_stores)
    AND sensitivity <= :max_sensitivity_for_role`.
   Applied in SQL (pre-ANN) **and** backed by RLS (defense in depth).
5. **Answer verification** re-asserts scope: no citation may reference a chunk
   outside the caller's grant (catches any filter bug before the user sees it).
6. **Cache is scoped:** semantic-cache key includes a hash of the RBAC filter —
   a manager and an admin asking the same question get separately-scoped answers.

### 3.3 Document-level ACLs
Each ingested chunk is tagged at ingest with `visibility` (roles/permissions),
`store_scope`, `sensitivity` — from the source's own access rules. E.g. a
store-level runbook is `store_scope=[that store]`; an HQ policy is
`sensitivity=restricted, visibility=[super_admin, regional_manager]`.

### 3.4 The invariant test (must be in CI)
> Seed a doc visible only to role/store A. Assert role/store B's query returns
> **zero** of A's chunks — through the vector arm, the BM25 arm, the cache, and
> the final answer. A single leak fails the build.

### 3.5 Pitfalls (challenge assumptions)
- **RLS alone isn't enough** for ANN — some vector search paths bypass row
  policies or run as a service role; enforce the filter in the query too.
- **The cache is the classic leak** — unscoped semantic cache serves role A's
  answer to role B. Scope every cache key.
- **Metadata drift** — if a doc's ACL changes, stale embeddings keep the old
  `visibility`; re-tag on ACL change, not just on content change.
- **Reranker/LLM see the text** — so pre-retrieval filtering (not post-hoc
  filtering of results) is mandatory; never retrieve-then-hide.

---

## 4. The verification loop (covers RAG + guardrails + RBAC)

A single CI-gated harness, run on every push and nightly:
1. **Retrieval quality** — recall@k / nDCG on the labeled set.
2. **Groundedness** — faithfulness ≥ target; 0 fabricated numbers.
3. **Guardrail suite** — one test per guardrail: injection blocked, PII redacted,
   off-topic refused, malformed-structure rejected, toxic-output blocked, numeric
   sanity trips, action requires approval.
4. **RBAC-leak suite** — §3.4, across vector/BM25/cache/answer, for every role pair.
5. **Red-team / jailbreak** — a growing corpus of adversarial prompts.
6. **Semantic-cache correctness** — same scope hits, different scope misses.
7. **Regression** — every 👎 (feedback loop, Y6) auto-drafts an eval case.
**Gate:** recall/faithfulness thresholds met, **0 RBAC leaks, 0 fabricated
numbers, 0 unblocked injections**. Accuracy becomes a number, not a vibe.

---

## 5. Decisions summary (fast reference)

| Decision | Pick (now) | Revisit at |
|---|---|---|
| What uses RAG | unstructured knowledge only; numbers → SQL | never (invariant) |
| Chunking | structural + parent-doc, per-corpus sizing | eval-driven |
| Embedder | all-minilm now → **bge-m3 before Arabic content** | Arabic corpus |
| Vector DB | pgvector (+RLS) → pgvectorscale | >10M chunks / >100 tenants |
| Retrieval | hybrid (BM25∪vector) + RRF + gated rerank | latency budget |
| Guardrails | layered pipeline, fail-closed on security | continuous |
| RBAC | pre-retrieval hard filter from JWT grants + RLS + scoped cache | never loosen |
| Eval | CI gate: recall, faithfulness, 0 leaks, 0 fake numbers | thresholds ratchet |

## 6. Common pitfalls (the counter-brainstorm)
- Treating RAG as the answer to everything (numbers aren't RAG).
- One chunk size / one embedder / English-only for an Arabic market.
- Similarity == relevance (skip rerank at your peril).
- Post-filtering results for ACLs (leaks); the filter must be pre-retrieval.
- Unscoped semantic cache (cross-role leak).
- No eval gate → silent accuracy decay.
- Fine-tuning before retrieval+guardrails are solid (tuning locks in yesterday's schema).

## 7. Explicitly NOT doing (yet)
Agentic web browsing, open-domain QA, LLM fine-tuning (pre-Stage-3), a dedicated
vector DB, letting the LLM see raw tables or mutate data directly, or building a
LangChain-style framework (the sage3 graph + a small guardrail pipeline is the
right amount of structure). **API-key / PostHog CI-CD work is deferred per the
owner** — revisit after this lands.
