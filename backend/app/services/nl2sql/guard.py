"""
Allow-list SQL guard for Sage (A2).

The LLM is never trusted. Before any generated SQL touches the database it must
pass this guard, which enforces — in layers, with the least-privilege `sage_ro`
role and a read-only statement-timeout transaction as further backstops:

  1. A SINGLE statement (no `;`-stacking).
  2. No SQL comments (block comment-based bypasses).
  3. SELECT/WITH only — every DDL/DML/transaction/admin keyword is rejected.
  4. No dangerous functions or catalog access (pg_*, set_config, current_setting,
     dblink, lo_*, information_schema, ...). Notably set_config/current_setting are
     blocked so generated SQL can't change or probe the tenant GUC.
  5. Only the curated sage_* views (schema.ALLOWED_RELATIONS) or local CTEs may be
     read in FROM/JOIN position.
  6. A hard row cap: the query is wrapped so an outer LIMIT always applies.

`validate_sql` returns the sanitized, row-capped SQL or raises SqlGuardError.
"""
from __future__ import annotations

import re

from .schema import ALLOWED_RELATIONS


class SqlGuardError(Exception):
    """Raised when candidate SQL violates the allow-list policy."""


# Statement keywords that must never appear (word-boundary matched, case-insensitive).
_FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "merge", "call", "do", "vacuum", "analyze",
    "reindex", "cluster", "comment", "execute", "prepare", "deallocate",
    "listen", "notify", "unlisten", "lock", "set", "reset", "begin", "commit",
    "rollback", "savepoint", "into", "refresh", "declare", "fetch", "move",
}

# Function / identifier fragments that signal catalog access, file/network I/O,
# or GUC tampering. Substring-matched (case-insensitive) for breadth.
_FORBIDDEN_FRAGMENTS = (
    "pg_", "set_config", "current_setting", "dblink", "lo_import", "lo_export",
    "information_schema", "current_user", "session_user", "txid_", "query_to_",
    "to_regclass", "has_table_privilege", "current_database", "current_schema",
    "inet_client", "inet_server", "::regclass", "::regrole",
)

# Extracts the identifier in FROM/JOIN position.
_RELATION_RE = re.compile(r'\b(?:from|join)\s+("?[a-zA-Z_][\w$]*"?)', re.IGNORECASE)
# Extracts CTE names from `WITH name AS (` / `, name AS (`.
_CTE_RE = re.compile(r'(?:\bwith\b|,)\s*("?[a-zA-Z_][\w$]*"?)\s+as\s*\(', re.IGNORECASE)


def _strip_quotes(ident: str) -> str:
    return ident.strip().strip('"').lower()


def validate_sql(sql: str, max_rows: int) -> str:
    """Validate and sanitize LLM-generated SQL. Returns row-capped SQL or raises."""
    if not sql or not sql.strip():
        raise SqlGuardError("empty SQL")

    cleaned = sql.strip()

    # Strip a single trailing semicolon; any *interior* one means statement stacking.
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if ";" in cleaned:
        raise SqlGuardError("multiple statements are not allowed")

    # No comments — they're a classic guard-bypass vector.
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise SqlGuardError("SQL comments are not allowed")

    lowered = cleaned.lower()

    # Must be a read query.
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise SqlGuardError("only SELECT/WITH queries are allowed")

    # Tokenize on word boundaries for keyword checks.
    tokens = set(re.findall(r"[a-z_]+", lowered))
    bad = tokens & _FORBIDDEN_KEYWORDS
    if bad:
        raise SqlGuardError(f"forbidden keyword(s): {', '.join(sorted(bad))}")

    for frag in _FORBIDDEN_FRAGMENTS:
        if frag in lowered:
            raise SqlGuardError(f"forbidden reference: {frag}")

    # Relation allow-list: every FROM/JOIN target must be a sage_* view or a CTE.
    cte_names = {_strip_quotes(m) for m in _CTE_RE.findall(cleaned)}
    targets = [_strip_quotes(m) for m in _RELATION_RE.findall(cleaned)]
    if not targets:
        raise SqlGuardError("query reads no allowed relation")
    for t in targets:
        if t not in ALLOWED_RELATIONS and t not in cte_names:
            raise SqlGuardError(f"relation '{t}' is not in the allow-list")

    # Hard row cap: wrap so an outer LIMIT always bounds the result, regardless of
    # any inner LIMIT the model wrote.
    capped = max(1, int(max_rows))
    return f"SELECT * FROM (\n{cleaned}\n) AS sage_result LIMIT {capped}"
