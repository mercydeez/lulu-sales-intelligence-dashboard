"""
SQL safety gate for Sage.

The model is never trusted. Every generated statement must pass this validator
before it can touch the database:

  - exactly one statement (no `;`-chained injection)
  - starts with SELECT or WITH
  - no DDL/DML/admin keywords, no system schemas, no write/file/GUC functions
  - every FROM/JOIN relation is on the allow-list (plus CTE names it defines)
  - a LIMIT is appended if the model didn't add one

Comments are rejected outright rather than stripped, so no comment-based trick
can smuggle a keyword past the regexes.
"""
from __future__ import annotations

import re
from typing import Set

# Whole-word keywords that must never appear in a read-only analytics query.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|"
    r"MERGE|CALL|DO|VACUUM|ANALYZE|REINDEX|CLUSTER|LOCK|SET|RESET|REFRESH|"
    r"COMMENT|EXECUTE|PREPARE|DEALLOCATE|LISTEN|NOTIFY|INTO)\b",
    re.IGNORECASE,
)
_SYSTEM = re.compile(r"\b(pg_catalog|information_schema|pg_[a-z_]+)\b", re.IGNORECASE)
_DANGER_FUNCS = re.compile(
    r"\b(nextval|setval|pg_sleep|dblink|lo_import|lo_export|pg_read_file|"
    r"pg_ls_dir|set_config|current_setting|pg_terminate_backend)\b",
    re.IGNORECASE,
)
_FROM_JOIN = re.compile(r"(?is)\b(?:from|join)\s+([a-zA-Z_][\w\.\"]*)")
_CTE = re.compile(r"(?is)(?:\bwith\b|,)\s+([a-zA-Z_]\w*)\s+as\s*\(")
_LIMIT = re.compile(r"(?is)\blimit\b")
_STARTS_OK = re.compile(r"(?is)^\s*(select|with)\b")


class SQLValidationError(Exception):
    """Raised when a generated statement fails a safety check."""


def _strip_fences(sql: str) -> str:
    s = sql.strip()
    if s.startswith("```"):
        # ```sql\n...\n``` -> inner
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    # Some models prefix "SQL:" or "Query:".
    s = re.sub(r"(?is)^\s*(sql|query)\s*:\s*", "", s)
    return s.strip()


def clean_and_validate(sql: str, allowed: Set[str], max_rows: int) -> str:
    """Return a safe, LIMIT-bounded single SELECT, or raise SQLValidationError."""
    s = _strip_fences(sql)
    s = s.rstrip().rstrip(";").strip()

    if not s:
        raise SQLValidationError("empty statement")
    if "--" in s or "/*" in s:
        raise SQLValidationError("comments are not allowed")
    if ";" in s:
        raise SQLValidationError("only a single statement is allowed")
    if not _STARTS_OK.match(s):
        raise SQLValidationError("only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(s):
        raise SQLValidationError("statement contains a forbidden keyword")
    if _SYSTEM.search(s):
        raise SQLValidationError("system catalogs are not queryable")
    if _DANGER_FUNCS.search(s):
        raise SQLValidationError("statement uses a disallowed function")

    cte_names = {m.lower() for m in _CTE.findall(s)}
    permitted = {r.lower() for r in allowed} | cte_names
    for ref in _FROM_JOIN.findall(s):
        base = ref.split(".")[-1].strip('"').lower()
        if base not in permitted:
            raise SQLValidationError(f"relation '{ref}' is not allowed")

    if not _LIMIT.search(s):
        s = f"{s}\nLIMIT {int(max_rows)}"
    return s
