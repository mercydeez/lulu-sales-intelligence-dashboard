"""
The orchestrated zero-hallucination answer path — all ten stages in one call.
Diagram: "RAG PIPELINE FOR 10M+ DOCS (ZERO HALLUCINATION)"; repo mapping in
docs/product/specs/RAG_AND_GUARDRAILS_ARCHITECTURE.md.

    answer_grounded(query, tenant_id, role=, allowed_stores=)
      1  ingest+versioning ......... rag/ingest.py (upstream of this call)
      2  hybrid retrieval .......... rag/retriever.py (BM25 ∪ vector, RRF)
      3  ANN + rerank .............. hnsw index + rag/rerank.py
      4  source confidence ......... rag/confidence.py (filter + gate)
      5  constrained generation .... context-only prompt (or extractive)
      6  citation-backed ........... every answer carries its citations
      7  hallucination fallback .... confidence < τ → "insufficient evidence"
      8  continuous evals .......... rag/evaluation.py (CI gate, upstream)
      9  caching + memory .......... rag/cache.py (RBAC-scoped answer cache)
      10 observability ............. rag/observability.py (RagTrace per answer)

Guardrails wrap both ends (services/guardrails): INPUT rails can block or
transform the query before retrieval; OUTPUT rails (faithfulness, citation
enforcement, PII leak, numeric sanity) can veto the generated answer — a
vetoed answer degrades to the refusal, never to an unchecked reply.

The refusal is a feature, not a failure: below-threshold evidence yields an
honest "insufficient evidence" instead of a guess. Refusals are never cached —
the very next ingest may fill the gap.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from app.services.rag.acl import build_acl_filter
from app.services.rag.cache import answer_cache_get, answer_cache_set
from app.services.rag.confidence import (
    ANSWER_CONFIDENCE_THRESHOLD, answer_confidence, filter_confident,
)
from app.services.rag.observability import RagTrace
from app.services.rag.rerank import assemble_context
from app.services.rag.retriever import search_documents
from app.services.guardrails import GuardrailContext, Phase, default_pipeline

INSUFFICIENT_EVIDENCE = (
    "I don't have enough grounded evidence in the documents I can access to "
    "answer that reliably, so I won't guess. Try rephrasing, or ask an admin "
    "whether the relevant document has been ingested (and is visible to your role)."
)

_CONSTRAINED_SYSTEM = (
    "You answer ONLY from the provided document excerpts — no external "
    "knowledge, no assumptions. Cite the source title in parentheses after "
    "each claim. If the excerpts do not contain the answer, reply exactly: "
    "INSUFFICIENT_EVIDENCE"
)


@dataclass
class GroundedAnswer:
    ok: bool                      # True = a grounded answer; False = refusal
    answer: str = ""
    citations: List[str] = field(default_factory=list)
    confidence: float = 0.0
    refused: bool = False
    refusal_reason: str = ""
    cached: bool = False
    trace: dict = field(default_factory=dict)
    # The chunk(s) the answer was generated from — downstream validation
    # (sage3 critic/cross_validator) needs real text to check numbers against,
    # not just citation labels.
    chunks: List[dict] = field(default_factory=list)


async def answer_grounded(
    query: str,
    tenant_id: int,
    *,
    role: Optional[str] = None,
    allowed_stores: Optional[Sequence[int]] = None,
    providers: Optional[list] = None,
    top_k: int = 8,
    use_cache: bool = True,
) -> GroundedAnswer:
    trace = RagTrace(trace_id=uuid.uuid4().hex[:12], tenant_id=tenant_id, role=role or "")
    rails = default_pipeline()

    def _refuse(reason: str, conf: float = 0.0) -> GroundedAnswer:
        trace.refuse(reason)
        return GroundedAnswer(ok=False, answer=INSUFFICIENT_EVIDENCE, confidence=conf,
                              refused=True, refusal_reason=reason, trace=trace.emit())

    # ── INPUT guardrails (block injections; PII redaction may transform) ────
    ctx = GuardrailContext(trace_id=trace.trace_id, query=query, tenant_id=tenant_id,
                           role=role or "", allowed_stores=list(allowed_stores or []))
    res = rails.run(Phase.INPUT, ctx)
    for t in res.trips:
        trace.trip(t.guardrail)
    if not res.allowed:
        return _refuse("input_guardrail:" + (res.trips[0].guardrail if res.trips else "blocked"))
    query = ctx.query  # PII-redacted form if a rail transformed it

    # ── RBAC-scoped answer cache (stage 9) ──────────────────────────────────
    acl = build_acl_filter(tenant_id, role, allowed_stores)
    if use_cache:
        hit = await answer_cache_get(query, acl.filter_hash, tenant_id)
        if hit:
            trace.cache_hit = True
            trace.emit()
            return GroundedAnswer(ok=True, cached=True, **{
                k: hit[k] for k in ("answer", "citations", "confidence", "chunks") if k in hit})

    # ── Hybrid retrieval (2) + confidence filter/gate (4, 7) ────────────────
    trace.start("retrieval")
    chunks = await search_documents(query, tenant_id, top_k=top_k,
                                    role=role, allowed_stores=allowed_stores)
    trace.stop("retrieval")
    kept, dropped = filter_confident(query, chunks)
    conf = answer_confidence(kept)
    trace.record_retrieval(
        fts=sum(1 for c in chunks if c.get("in_fts")),
        vec=sum(1 for c in chunks if c.get("in_vec")),
        fused=len(chunks), semantic=True)
    trace.reranked_returned = len(kept)
    if not kept or conf < ANSWER_CONFIDENCE_THRESHOLD:
        return _refuse("insufficient_evidence", conf)

    # ── Rerank + context assembly (3) then constrained generation (5, 6) ────
    trace.start("generation")
    ctx_text, kept, citations = assemble_context(query, kept)
    answer = ""
    for provider in providers or []:
        try:
            out = await provider.complete([
                {"role": "system", "content": _CONSTRAINED_SYSTEM},
                {"role": "user", "content": f"Excerpts:\n{ctx_text}\n\nQuestion: {query}"},
            ])
            if out and out.strip():
                answer = out.strip()
                break
        except Exception:
            continue
    if answer.strip().upper().startswith("INSUFFICIENT_EVIDENCE"):
        trace.stop("generation")
        return _refuse("llm_reported_insufficient", conf)
    if not answer:
        # No LLM configured: extractive answer — top chunk verbatim, cited.
        top = kept[0]
        answer = f"{top['content']}  ({top['title']} (chunk {top['chunk_no']}))"
    trace.stop("generation")

    # ── OUTPUT guardrails: faithfulness, citations, PII, numeric sanity ─────
    ctx.answer, ctx.chunks, ctx.citations = answer, kept, citations
    res = rails.run(Phase.OUTPUT, ctx)
    for t in res.trips:
        trace.trip(t.guardrail)
    if not res.allowed:
        return _refuse("output_guardrail:" + (res.trips[0].guardrail if res.trips else "blocked"), conf)

    trace.faithfulness = conf
    trace.answer_chars = len(answer)
    trace.citations = len(citations)
    evidence_chunks = [{"title": c.get("title"), "chunk_no": c.get("chunk_no"),
                        "content": c.get("content")} for c in kept]
    if use_cache:
        await answer_cache_set(query, acl.filter_hash, tenant_id,
                               answer, citations, confidence=conf, chunks=evidence_chunks)
    return GroundedAnswer(ok=True, answer=answer, citations=citations,
                          confidence=conf, trace=trace.emit(), chunks=evidence_chunks)
