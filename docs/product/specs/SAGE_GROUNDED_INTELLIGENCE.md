# Sage Grounded Intelligence — scaling architecture for ≥98% answer accuracy

> Brainstorm output (July 2026), cross-team architecture — deliberately ignores
> the ownership split; seams get assigned when this becomes epics.
> Builds ON the existing stack: `llm/` provider abstraction, `nl2sql/` guard +
> curated `sage_*` views, `sage2` intents, `sage3` dialogue graph, `rag/`
> FTS retriever (with its own "pgvector upgrade path" comment), `root_cause.py`,
> `050_krishna_metric_views.sql`, findings/decision engine.
> **Convergence note:** the parked main-branch Track 10 work (pgvector semantic
> layer, guarded RAG, `embeddings.py`, `knowledge.py`, `ai_evals.py` — currently
> in Yash's `stash@{0}` / main commits) is essentially Stage 1 of this plan.
> Port it deliberately; don't rebuild it.

## 0. What "98% accuracy" honestly means

No open-ended chatbot hits 98% on free generation. The claim is achievable only as:

1. **Numbers never come from the LLM.** Postgres computes; the LLM narrates
   results it was handed. (Already the repo's instinct — keep it absolute.)
2. **Route every question to the most deterministic tier that can answer it.**
3. **Accuracy is a measured, CI-gated metric** over a golden eval set — not a vibe.
4. **Calibrated refusal counts as correct.** "I can't answer that reliably" is a
   pass; a confident wrong number is the only real failure. The product honesty
   convention (units≠AED, "insufficient baseline") extends to the bot.

Target SLOs: Tier 0/1 numeric-exactness ≥ 99% · Tier 2 grounded-or-refused ≥ 97%
· hallucinated-number rate = 0 · overall weighted ≥ 98%.

## 1. The four grounding tiers

```
question ─► intent router (rules + small local model; sage2 intents today)
  ├─ T0 DETERMINISTIC   known intent → parametrized semantic-view query → template
  │                     narration. ~50-60% of traffic, ≈100% accurate.
  ├─ T1 CONSTRAINED     free-form analytics → NL2SQL bound to curated sage_* views
  │    NL2SQL           through guard.py (single stmt, SELECT-only, allowlist,
  │                     row-cap, sage_ro). Upgrades: few-shot exemplars retrieved
  │                     by vector similarity; self-consistency (2 samples must
  │                     agree on result shape or → clarify); post-exec unit +
  │                     magnitude verification against the metric registry;
  │                     sage3 readback-confirm on ambiguity (exists).
  ├─ T2 HYBRID RAG      product knowledge/docs/runbooks/changelog/past findings →
  │                     FTS (exists) + pgvector cosine + reciprocal-rank fusion
  │                     (+ cross-encoder rerank at Stage 2). Citations mandatory;
  │                     low retrieval confidence → refuse, never wing it.
  └─ T3 PRODUCT STATE   "what is happening and why" → answered from a pre-computed
       GRAPH            tenant state snapshot (below), never from speculation.
```

## 2. Tier 3 — the Product State Graph ("read the whole product")

**Principle: don't make the LLM figure out what's happening — the platform
already knows; Sage voices it.** A `product_state` snapshot service refreshes a
per-tenant context pack every few minutes (or on finding-write):

| Slice | Source (already exists) |
|---|---|
| What changed | metric deltas from `050` canonical views (day/week/region/category) |
| Why | `root_cause.py` decompositions — top contributors with AED deltas (pure SQL) |
| Findings | worker diagnostics findings + evidence + severity |
| Seasonal context | UAE calendar active/upcoming events (`uae_intelligence`) |
| Ops health | E0-2 heartbeat, public-status components, SSE degradation |
| Product motion | changelog entries, recent imports, active promotions |
| Usage | usage meters / quota state (Track 5/7) |

Storage: one JSONB row per tenant (`product_state`), versioned, plus embedded
slices in the vector table so T2 retrieval can also see state. Answering
"what's happening in Dubai this week and why?" = select the relevant slices,
narrate with citations to finding ids / decomposition rows. The *why* is a SQL
decomposition, not an LLM guess — that's what makes an explanatory answer
98%-grade.

## 3. Vector layer — pgvector, staged

- **Stage 1 (now):** `CREATE EXTENSION vector`; `embeddings` table
  (tenant_id, corpus, ref_id, chunk_no, content, embedding vector(768|1536),
  model_tag, created_at) + **RLS like every other table** + HNSW index.
  Embedder behind the existing `llm/` provider abstraction: Ollama
  (nomic-embed / bge) for the local/PDPL tier, OpenAI-compatible for hosted.
  `model_tag` enables re-embedding migrations without downtime.
  Corpora: docs/runbooks, changelog, findings narratives, metric registry
  descriptions, NL2SQL exemplars, product_state slices.
  Hybrid retrieval: FTS rank ∪ cosine rank → reciprocal-rank fusion.
- **Stage 2:** route vector + analytics reads to the planned read replica
  (E10-7); add a small cross-encoder reranker; exemplar store grows from eval
  misses.
- **Stage 3 (>100 tenants / >10M chunks):** dedicated vector store (e.g.
  Qdrant) + ClickHouse for events. **Explicitly deferred** — before that,
  pgvector on a replica is faster to operate and one less thing to secure.

## 4. Accuracy machinery (how 98% stays a number)

1. **Metric registry = semantic layer as single source of truth.** One
   definition per metric (formula, unit, grain) — the `050` views + ADR-002
   units/AED convention formalized into a registry the router, NL2SQL prompt,
   verifier, and narrator all read.
2. **Golden eval set in CI** (seed: main-branch `ai_evals.py` + `test_sage*`):
   150→500 Q/A pairs. T0/T1 scored by exact numeric match vs direct SQL;
   T2 by citation coverage + LLM-judge groundedness; T3 by scenario replays
   (seed a known anomaly → expect the right why). Deploy gate on the SLOs in §0.
3. **Runtime verification layer** after every answer: tenant-scope assertion,
   unit check, magnitude sanity (vs registry historical ranges), citation
   presence (T2/T3). Any failure → sage3 clarify/refuse path (exists).
4. **Semantic cache:** embed the question; if cosine-near a previously
   *verified* answer (same tenant, same scope, TTL) → serve cached. Cost ↓,
   latency ↓, consistency ↑.
5. **Feedback flywheel:** 👍/👎 on every Sage answer (frontend seam);
   every 👎 auto-drafts an eval case. Accuracy compounds instead of decaying.
6. **AI observability:** per-tier answer rates, refusal rate, verification
   failures, retrieval confidence histograms — into telemetry/Prometheus.
   A rising refusal rate is a retrieval gap, not a model problem.

## 5. Model tiers (cost/latency envelope)

- **Router/embedder:** small local (Ollama) — cheap, fast, PDPL-clean.
- **Narrator:** hosted LLM tier (E7 "hosted-LLM Sage") for T1/T2/T3 prose;
  falls back to the existing zero-LLM template path (honest fallback exists).
- **Judge (evals only, offline):** any strong hosted model; never in the
  request path.
- All behind `llm/base.py` — swapping vendors stays a provider-file change.

## 6. Staged roadmap

| Stage | Scope | Exit criterion |
|---|---|---|
| **1** (~4-6 wks) | Port Track 10 (pgvector, embeddings, guarded RAG, ai_evals) onto this branch; hybrid retrieval in `rag/retriever.py` (interface unchanged); metric registry v1; golden set ≥150 in CI; product_state v1 (findings+root-cause+calendar+health); 👍/👎 capture | CI accuracy gate live; "what's happening & why" answers with citations |
| **2** | Reranker; NL2SQL exemplar store + self-consistency; semantic cache; read-replica routing; eval set ≥500; per-tenant thresholds (E3-6) | measured overall ≥98% for 30 consecutive days |
| **3** | Dedicated vector store + ClickHouse only when replica saturates; optional fine-tune on accumulated Q→semantic-query pairs | >100 tenants without SLO regression |

## 7. Explicitly NOT doing (so nobody re-litigates)

- **Agentic web browsing / open-domain answers** — Sage answers about *your
  retail operation*, or refuses. Scope is the accuracy moat.
- **Fine-tuning before Stage 3** — retrieval + constraints beat tuning at this
  data volume, and tuning locks in yesterday's schema.
- **LangChain-style framework adoption** — sage3's graph is already the right
  shape; a framework adds abstraction debt, not accuracy.
- **Letting the LLM see raw tables** — curated views only, forever. The guard
  stays even when models get better; defense in depth is the product.
