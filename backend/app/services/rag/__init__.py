"""
Document RAG for Sage v2 — answer "according to the document" questions grounded in
retrieved chunks (never invented). Retrieval is Postgres full-text today (zero
deps); the retriever interface is embedding-ready (pgvector + Ollama embeddings)
for a drop-in semantic upgrade when the LLM provider is configured.
"""
from .retriever import RagAnswer, answer_from_docs, search_documents

__all__ = ["search_documents", "answer_from_docs", "RagAnswer"]
