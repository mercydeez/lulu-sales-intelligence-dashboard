"""
Deterministic sub-answerers for Sage v2 (the zero-LLM fallback + test oracle).

Each intent maps keyword triggers to a curated canonical SQL template over the
sage_* semantic layer, plus a label and answer kind. This makes multi-part
questions answerable WITHOUT an LLM (and gives the decompose→recompose pipeline a
deterministic test path). When an LLM provider is configured, the orchestrator
instead decomposes freely and generates per-sub NL→SQL — but every generated query
still passes the same allow-list guard and runs on the least-privilege sage_ro role.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

ZONES = ("North", "South", "East", "West", "Central")


def extract_zone(question: str) -> Optional[str]:
    for z in ZONES:
        if re.search(rf"\b{z}\b", question, re.IGNORECASE):
            return z
    return None


@dataclass
class Intent:
    name: str
    label: str                 # how the metric is labelled in the recomposed answer
    keywords: tuple            # any-match (lowercased substring) triggers this intent
    kind: str                  # 'scalar' | 'list' | 'document'
    zone_aware: bool = False   # filter by the detected zone when present
    doc_query: str = ""        # for kind=='document': the RAG search string

    def build_sql(self, zone: Optional[str]) -> str:
        raise NotImplementedError


@dataclass
class TemplateIntent(Intent):
    sql: str = ""              # may contain {zone_filter}
    def build_sql(self, zone: Optional[str]) -> str:
        zone_filter = ""
        if self.zone_aware and zone:
            # zone is validated against ZONES, so it is safe to inline.
            zone_filter = f" WHERE zone = '{zone}'"
        return self.sql.format(zone_filter=zone_filter)


# Order matters only for presentation; matching is independent.
INTENTS: List[TemplateIntent] = [
    TemplateIntent(
        name="revenue_target", label="2030 revenue target",
        keywords=("revenue target", "2030", "strategy target", "target per the strategy"),
        kind="scalar",
        sql="SELECT value, unit FROM sage_targets WHERE year = 2030 ORDER BY value DESC LIMIT 1",
    ),
    TemplateIntent(
        name="primary_sales_revenue", label="Total primary sales revenue",
        keywords=("primary sales", "total sales revenue", "sales revenue"),
        kind="scalar",
        sql="SELECT ROUND(SUM(revenue_aed), 2) AS primary_sales_revenue FROM sage_sales WHERE NOT is_return",
    ),
    TemplateIntent(
        name="crm_pipeline_revenue", label="CRM pipeline expected revenue",
        keywords=("crm", "pipeline", "expected revenue"),
        kind="scalar", zone_aware=True,
        sql="SELECT SUM(expected_revenue) AS crm_pipeline_expected_revenue FROM sage_crm_pipeline{zone_filter}",
    ),
    TemplateIntent(
        name="distributors_in_zone", label="Distributors serving the zone",
        keywords=("distributor", "distributors", "which distributors", "serve"),
        kind="list", zone_aware=True,
        sql="SELECT distributor_name FROM sage_distributors{zone_filter} ORDER BY distributor_name",
    ),
    TemplateIntent(
        name="avg_online_price", label="Average online selling price",
        keywords=("online selling price", "online price", "average online", "ecommerce price"),
        kind="scalar",
        sql="SELECT ROUND(AVG(price_aed), 2) AS avg_online_price_aed FROM sage_online_prices",
    ),
    # Document-grounded answer (RAG over the strategy doc). Keywords chosen NOT to
    # collide with the structured revenue_target intent.
    TemplateIntent(
        name="strategy_document", label="From the strategy document",
        keywords=("according to the strategy", "what does the strategy", "document say",
                  "per the document", "strategy says"),
        kind="document",
        doc_query="2030 revenue target ambition strategy",
    ),
    # A few general extras so it's useful beyond the flagship question.
    TemplateIntent(
        name="top_stores", label="Top stores by revenue",
        keywords=("top stores", "best stores", "store ranking"),
        kind="list",
        sql="SELECT store_name, revenue_aed FROM sage_store_performance ORDER BY revenue_aed DESC LIMIT 5",
    ),
    TemplateIntent(
        name="returns", label="Total returns (units)",
        keywords=("returns", "returned"),
        kind="scalar",
        sql="SELECT SUM(ABS(units)) AS returned_units FROM sage_sales WHERE is_return",
    ),
]


def match_intents(question: str) -> List[TemplateIntent]:
    q = question.lower()
    matched: List[TemplateIntent] = []
    seen = set()
    for intent in INTENTS:
        if intent.name in seen:
            continue
        if any(kw in q for kw in intent.keywords):
            matched.append(intent)
            seen.add(intent.name)
    return matched
