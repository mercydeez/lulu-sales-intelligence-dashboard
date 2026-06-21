"""
Sage — Foresia's natural-language analyst.

Turns a free-form business question into a single, safe, tenant-scoped SQL
SELECT, executes it read-only, and hands the rows back for narration. The
pieces:

  schema_catalog  curated, tenant-safe description of the queryable relations
  validator       hard SQL safety gate (SELECT-only, single statement, allow-listed
                  relations, no system tables / write funcs)
  executor        runs the SELECT as the non-owner app_rw role in a READ ONLY
                  transaction with the tenant GUC set, so Postgres RLS scopes rows
  nl2sql          orchestrates generate -> validate -> execute and infers a chart

Defense in depth: even if the model emits something unexpected, the validator
rejects it, the read-only transaction blocks writes, and RLS blocks cross-tenant
reads. ai_assistant uses this as the primary data path and falls back to the
keyword-intent responder when there's no query to run.
"""
from .nl2sql import SageResult, answer_question

__all__ = ["SageResult", "answer_question"]
