"""Atelier Advisor — plain-language client need -> catalog-mapped configuration.

A platform developer describes what a client wants ("they run tills and want
receipts flowing in nightly, plus a dark UI"); the advisor answers with concrete
suggestions mapped to the customization catalog (services/customization.py
FLAG_CATALOG) and HONEST gaps for anything the catalog cannot express — those
become bespoke-work drafts, never fabricated capabilities.

HONESTY RULES (Platform Console brand):
  * `engine` says truthfully whether the answer came from an LLM ("llm") or the
    deterministic keyword fallback ("rules"). Any LLM failure => "rules".
  * Suggestions may only reference real FLAG_CATALOG keys — unknown keys from the
    model are DROPPED, invalid values are replaced by the catalog default (and the
    reason says so). Nothing in the output is invented.
  * Every gap carries a ready-to-file `draft_request` so "we don't have this"
    turns into tracked bespoke work with one click.

The LLM path reuses the shared plumbing: get_provider_chain() (Ollama-first,
optional OpenAI) + sage3's complete_json(). With no provider configured the
advisor still works — that is the same no-LLM invariant the Sage graph keeps.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.services.customization import FLAG_CATALOG, plan_allows, validate_value
from app.services.llm import LLMError, get_provider_chain
from app.services.sage3.graph.llm_util import complete_json

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 10
MAX_GAPS = 5


# ---------------------------------------------------------------------------
# Catalog rendering — the LLM may only pick from these lines.
# ---------------------------------------------------------------------------

def _catalog_prompt_block() -> str:
    """Every FLAG_CATALOG entry as one line:
    key | type (options) | default | plan_min | category | label — description
    """
    lines: List[str] = []
    for key, entry in FLAG_CATALOG.items():
        t = entry["type"]
        if t == "enum":
            t = f"{t} ({'|'.join(entry.get('options', []))})"
        elif t == "int":
            t = f"{t} ({entry.get('min')}..{entry.get('max')})"
        lines.append(
            f"{key} | {t} | default={entry['default']!r} | "
            f"plan_min={entry.get('plan_min') or 'any'} | {entry['category']} | "
            f"{entry['label']} — {entry['description']}"
        )
    return "\n".join(lines)


def _system_prompt(tenant_context: Optional[dict]) -> str:
    product = get_settings().product_name
    ctx = ""
    if tenant_context:
        ctx = (
            "\nTENANT CONTEXT (the client this is for):\n"
            f"  plan: {tenant_context.get('plan')!r}\n"
            f"  current effective values: {tenant_context.get('effective')}\n"
        )
    return (
        f"You are the configuration advisor for the \"{product}\" platform.\n"
        "A platform developer will describe what a client wants in plain language. "
        "Map the need onto the customization catalog below and respond with STRICT "
        "JSON only (no prose, no markdown fences):\n"
        '{"summary": str, "suggestions": [{"key": <catalog key>, "value": <valid '
        'value for that key>, "reason": str}], "gaps": [{"title": str, "why": str}]}\n'
        "RULES:\n"
        "  * suggestions may ONLY use keys from the catalog below — never invent a key.\n"
        "  * values must be valid for the key's type/options/range.\n"
        "  * anything the catalog cannot express goes in gaps (honest 'we do not "
        "have this — candidate for bespoke work'), never a made-up suggestion.\n"
        f"{ctx}\n"
        "CATALOG (key | type | default | plan_min | category | label — description):\n"
        f"{_catalog_prompt_block()}"
    )


# ---------------------------------------------------------------------------
# Deterministic fallback — keyword mapper. (keywords, key, value or None=default)
# ---------------------------------------------------------------------------

_KEYWORD_MAP: List[Tuple[Tuple[str, ...], str, Any]] = [
    (("forecast", "demand"), "modules.forecasting", True),
    (("promo", "discount", "offer"), "modules.promotions", True),
    (("procurement", "supplier", "purchase"), "modules.procurement", True),
    (("stock", "inventory", "reorder"), "modules.inventory", True),
    (("report", "export", "excel"), "modules.reports", True),
    (("report", "export", "excel"), "limits.export_rows", None),
    (("chat", "assistant", "ai"), "assistant.ai_chat", True),
    (("voice", "speech"), "assistant.voice", True),
    (("copilot", "proactive"), "assistant.mode", "copilot"),
    (("theme", "dark", "brand"), "interface.default_theme", None),
    (("api", "integration", "webhook"), "integrations.public_api", True),
    (("api", "integration", "webhook"), "integrations.webhooks", True),
    (("pos", "till", "receipt", "basket"), "integrations.pos", True),
    (("pay", "checkout", "collect"), "integrations.payments", True),
    (("invoice", "fta", "tax", "vat"), "integrations.einvoicing", True),
    (("sftp", "imap", "email import", "schedule"), "integrations.imports_scheduled", True),
    (("rate limit", "throughput"), "limits.api_rate_multiplier", None),
]

_CLAUSE_SPLIT = re.compile(r"[.;\n]+")


def _kw_hit(keywords: Tuple[str, ...], low: str) -> Optional[str]:
    """First keyword matching at a word START ("promo" matches "promotions",
    but "ai" does not match "daily")."""
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw), low):
            return kw
    return None


def _rules_fallback(description: str) -> dict:
    """Keyword-map the description onto catalog keys; unmatched clauses become
    honest gaps. Purely deterministic — used whenever no LLM answered."""
    seen: set = set()
    suggestions: List[dict] = []
    gaps: List[dict] = []
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(description or "") if c.strip()]

    for clause in clauses:
        low = clause.lower()
        matched = False
        for keywords, key, value in _KEYWORD_MAP:
            hit = _kw_hit(keywords, low)
            if hit is None:
                continue
            matched = True
            if key in seen:
                continue
            seen.add(key)
            entry = FLAG_CATALOG[key]
            val = value if value is not None else entry["default"]
            # Small deterministic niceties for value-bearing keys.
            if key == "interface.default_theme" and "dark" in low:
                val = "dark"
            suggestions.append({
                "key": key,
                "value": val,
                "reason": f"Matched '{hit}' in: \"{clause[:80]}\" -> {entry['label']}.",
            })
        if not matched:
            gaps.append({
                "title": clause[:60],
                "why": "No catalog capability matches this — candidate for bespoke work",
            })

    n_clauses = len(clauses)
    summary = (
        f"Deterministic keyword mapping: {n_clauses - len(gaps)} of {n_clauses} "
        f"request clause(s) mapped to {len(suggestions)} catalog suggestion(s); "
        f"{len(gaps)} gap(s) need bespoke work."
    )
    return {"summary": summary, "suggestions": suggestions, "gaps": gaps}


# ---------------------------------------------------------------------------
# Post-validation — runs on BOTH engines' output, so the LLM cannot fabricate.
# ---------------------------------------------------------------------------

def _coerce(key: str, value: Any) -> Any:
    """Light type coercion before validation (LLMs love stringified values)."""
    t = FLAG_CATALOG[key]["type"]
    if isinstance(value, str):
        if t == "bool" and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        if t == "int":
            try:
                return int(value.strip())
            except ValueError:
                return value
    return value


def _post_validate(raw_suggestions: Any, raw_gaps: Any, description: str,
                   plan: Optional[str]) -> Tuple[List[dict], List[dict]]:
    suggestions: List[dict] = []
    seen: set = set()
    for item in raw_suggestions if isinstance(raw_suggestions, list) else []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key not in FLAG_CATALOG or key in seen:
            continue  # unknown/duplicate keys are dropped — never surfaced
        seen.add(key)
        entry = FLAG_CATALOG[key]
        reason = str(item.get("reason") or "").strip()
        value = _coerce(key, item.get("value"))
        ok, _err = validate_value(key, value)
        if not ok:
            value = entry["default"]
            reason = (reason + f" (proposed value was invalid; using catalog "
                               f"default {entry['default']!r})").strip()
        if plan is not None and not plan_allows(key, plan):
            reason = (reason + f" (requires plan upgrade to {entry.get('plan_min')})").strip()
        suggestions.append({"key": key, "value": value, "available": True, "reason": reason})
        if len(suggestions) >= MAX_SUGGESTIONS:
            break

    gaps: List[dict] = []
    for item in raw_gaps if isinstance(raw_gaps, list) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = str(item["title"]).strip()[:120]
        gaps.append({
            "title": title,
            "why": str(item.get("why") or "").strip(),
            # One-click filing into the bespoke ledger.
            "draft_request": {
                "title": title,
                "client_description": description,
                "priority": "medium",
            },
        })
        if len(gaps) >= MAX_GAPS:
            break
    return suggestions, gaps


# ---------------------------------------------------------------------------
# The advisor.
# ---------------------------------------------------------------------------

async def suggest(description: str, tenant_context: Optional[dict] = None) -> dict:
    """Map a plain-language client need to catalog suggestions + bespoke gaps.

    Returns {"engine": "llm"|"rules", "model": str|None, "summary", "suggestions",
    "gaps"}. `engine` is honest: "llm" only when a provider actually produced the
    JSON; every other path (no providers, provider error, unparseable reply) is
    the deterministic "rules" fallback.
    """
    system = _system_prompt(tenant_context)
    raw: Optional[dict] = None
    model: Optional[str] = None
    try:
        providers = get_provider_chain()
        # One provider at a time so `model` names the provider that actually
        # answered — not just the first in the chain.
        for provider in providers or []:
            raw = await complete_json([provider], system, description)
            if raw is not None:
                model = getattr(provider, "model", None) or getattr(provider, "name", None)
                break
    except (LLMError, Exception):  # noqa: BLE001 — any LLM failure => rules
        raw, model = None, None

    if raw is not None:
        engine = "llm"
        summary = str(raw.get("summary") or "").strip() or "Configuration suggestions."
        raw_suggestions, raw_gaps = raw.get("suggestions"), raw.get("gaps")
    else:
        engine = "rules"
        model = None
        fb = _rules_fallback(description)
        summary = fb["summary"]
        raw_suggestions, raw_gaps = fb["suggestions"], fb["gaps"]

    plan = (tenant_context or {}).get("plan")
    suggestions, gaps = _post_validate(raw_suggestions, raw_gaps, description, plan)
    return {
        "engine": engine,
        "model": model,
        "summary": summary,
        "suggestions": suggestions,
        "gaps": gaps,
    }
