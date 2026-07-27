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

# A single-quoted SQL string, tolerating the doubled-quote ('') escape.
_STRING_RE = re.compile(r"'(?:[^']|'')*'")
# Dollar-quoting ($$...$$ / $tag$...$tag$) can hide anything from a lexical scan
# and has no place in an analytical SELECT, so it is refused outright.
_DOLLAR_QUOTE_RE = re.compile(r"\$[a-zA-Z_]*\$")

# `EXTRACT(MONTH FROM date)` and `SUBSTRING(x FROM 1)` put a NON-relation token in
# FROM position. Without this the guard reads `date` as a table name and rejects
# "sales by month" — one of the most ordinary questions Sage will ever be asked.
# Only fixed SQL date-part keywords are skipped; a real table can never be one,
# and the sage_ro grants remain the backstop either way.
_NON_RELATION_TOKENS = frozenset({
    "year", "quarter", "month", "week", "day", "hour", "minute", "second",
    "dow", "doy", "epoch", "isodow", "isoyear", "millisecond", "microsecond",
    "century", "decade", "millennium", "timezone", "timezone_hour",
    "timezone_minute", "both", "leading", "trailing",
})


def _strip_quotes(ident: str) -> str:
    return ident.strip().strip('"').lower()


_FUNC_FROM_RE = re.compile(
    r"\b(extract|substring|trim|overlay)\s*\(([^()]*?)\bfrom\b", re.IGNORECASE
)


def _neutralize_func_from(sql: str) -> str:
    """Drop the FROM that lives *inside* EXTRACT/SUBSTRING/TRIM/OVERLAY.

    In `EXTRACT(MONTH FROM date)` the token after FROM is the column `date`, not a
    table, but the relation regex cannot tell the difference and rejected the
    query as "relation 'date' is not in the allow-list". That killed the single
    most ordinary analytical question there is — sales grouped by month. Only the
    inner FROM is removed; the statement's real FROM clause is untouched.
    """
    prev = None
    while prev != sql:
        prev = sql
        sql = _FUNC_FROM_RE.sub(lambda m: f"{m.group(1)}({m.group(2)} ", sql)
    return sql


def _mask_literals(sql: str) -> str:
    """Blank the contents of string literals so lexical checks see only SQL.

    The checks below scan the raw statement for keywords, comment markers and
    forbidden fragments. Run against the original text they also scan DATA, so a
    perfectly ordinary query was rejected because a literal contained the letters
    'do' ("do not ship"), 'set', 'create', 'into', or '--'. Masking removes that
    entire class of false rejection without weakening anything: a quoted literal
    is a value, never an executable statement, and the structural checks
    (SELECT/WITH-only, no statement stacking, relation allow-list) all still run
    on the masked text.
    """
    return _STRING_RE.sub("''", sql)


def validate_sql(sql: str, max_rows: int) -> str:
    """Validate and sanitize LLM-generated SQL. Returns row-capped SQL or raises."""
    if not sql or not sql.strip():
        raise SqlGuardError("empty SQL")

    cleaned = sql.strip()

    # Dollar-quoted bodies would survive literal masking and hide arbitrary text.
    if _DOLLAR_QUOTE_RE.search(cleaned):
        raise SqlGuardError("dollar-quoted strings are not allowed")

    # Every lexical check below runs against `scan`, where string literals are
    # emptied, so query DATA can never trip a keyword rule. Structure is
    # unaffected: masking preserves the statement's shape exactly.
    scan = _mask_literals(cleaned)

    # An unpaired quote means the literals did not mask cleanly — refuse rather
    # than scan text we may have mis-parsed.
    if "'" in scan.replace("''", ""):
        raise SqlGuardError("unbalanced string literal")

    # Strip a single trailing semicolon; any *interior* one means statement stacking.
    if scan.rstrip().endswith(";"):
        scan = scan.rstrip()[:-1].rstrip()
        cleaned = cleaned.rstrip()[:-1].rstrip()
    if ";" in scan:
        raise SqlGuardError("multiple statements are not allowed")

    # No comments — they're a classic guard-bypass vector.
    if "--" in scan or "/*" in scan or "*/" in scan:
        raise SqlGuardError("SQL comments are not allowed")

    lowered = scan.lower()

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
    # Read from the masked text so a table-like word inside a literal is not
    # mistaken for a relation.
    rel_scan = _neutralize_func_from(scan)
    cte_names = {_strip_quotes(m) for m in _CTE_RE.findall(rel_scan)}
    targets = [_strip_quotes(m) for m in _RELATION_RE.findall(rel_scan)]
    # Drop date-part keywords: these come from EXTRACT(MONTH FROM date) and
    # friends, not from a real FROM clause.
    targets = [t for t in targets if t not in _NON_RELATION_TOKENS]
    if not targets:
        raise SqlGuardError("query reads no allowed relation")
    for t in targets:
        if t not in ALLOWED_RELATIONS and t not in cte_names:
            raise SqlGuardError(f"relation '{t}' is not in the allow-list")

    # Hard row cap: wrap so an outer LIMIT always bounds the result, regardless of
    # any inner LIMIT the model wrote.
    capped = max(1, int(max_rows))
    return f"SELECT * FROM (\n{cleaned}\n) AS sage_result LIMIT {capped}"
