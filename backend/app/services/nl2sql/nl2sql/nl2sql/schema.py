"""
Sage's curated semantic layer (A2).

The LLM is shown ONLY these tenant-filtered `sage_*` views (migration 023), and
the guard rejects any SQL that reads anything else. The descriptions encode the
units/AED convention so Sage never mixes volume and value.
"""
from __future__ import annotations

# The ONLY relations Sage's SQL may read. Anything else -> guard rejection
# (and the sage_ro DB role can't read it anyway). Keep in sync with migration 023.
ALLOWED_RELATIONS: frozenset[str] = frozenset({
    "sage_sales",
    "sage_daily_sales",
    "sage_store_performance",
    "sage_category_performance",
    "sage_item_performance",
    "sage_stores",
    "sage_items",
})

# Human/LLM-readable schema. Deliberately compact so it fits a small local model's
# context. Every money column is named *_aed; every volume column is `units`.
SCHEMA_PROMPT = """\
You can query ONLY these read-only views. They are already scoped to the current
tenant — do NOT add tenant filters. All are PostgreSQL.

VIEW sage_sales        -- one row per sale line (the grain)
  date DATE, store_id INT, store_name TEXT, item_id INT, item_name TEXT,
  category TEXT, units INT (volume; negative = a return),
  unit_price_aed NUMERIC, revenue_aed NUMERIC (= units * unit_price_aed),
  is_streaming BOOL, is_return BOOL

VIEW sage_daily_sales  -- per-day totals
  date DATE, units BIGINT, revenue_aed NUMERIC, line_count BIGINT

VIEW sage_store_performance  -- per store
  store_id INT, store_name TEXT, units BIGINT, revenue_aed NUMERIC, line_count BIGINT

VIEW sage_category_performance  -- per category
  category TEXT, units BIGINT, revenue_aed NUMERIC

VIEW sage_item_performance  -- per item
  item_id INT, item_name TEXT, category TEXT, unit_price_aed NUMERIC,
  units BIGINT, revenue_aed NUMERIC

VIEW sage_stores  -- store dimension: store_id INT, store_name TEXT, location TEXT
VIEW sage_items   -- item dimension: item_id INT, item_name TEXT, category TEXT, unit_price_aed NUMERIC

CONVENTIONS (critical for correctness):
- VOLUME questions ("how many units / sold / quantity") -> use `units`.
- VALUE / money questions ("revenue / sales in AED / how much money") -> use `revenue_aed`.
- NEVER multiply by price yourself; revenue_aed is already units * unit_price_aed.
- Returns are rows where units < 0 (is_return = true). Exclude them with
  `WHERE NOT is_return` for gross-sales questions unless the user asks about returns.
- Dates: "today" = CURRENT_DATE, "this week" = last 7 days, "this month" = last 30 days.
"""

# Few-shot NL -> SQL pairs that demonstrate the conventions. The model echoes the
# style: a single SELECT, no trailing semicolon, no tenant filter.
FEW_SHOTS: list[dict[str, str]] = [
    {
        "q": "What was total revenue last week?",
        "sql": "SELECT SUM(revenue_aed) AS revenue_aed FROM sage_sales "
               "WHERE date >= CURRENT_DATE - INTERVAL '7 days' AND NOT is_return",
    },
    {
        "q": "Top 5 stores by revenue",
        "sql": "SELECT store_name, revenue_aed FROM sage_store_performance "
               "ORDER BY revenue_aed DESC LIMIT 5",
    },
    {
        "q": "How many units did we sell per category?",
        "sql": "SELECT category, units FROM sage_category_performance ORDER BY units DESC",
    },
    {
        "q": "Which items had the most returns this month?",
        "sql": "SELECT item_name, SUM(ABS(units)) AS returned_units FROM sage_sales "
               "WHERE is_return AND date >= CURRENT_DATE - INTERVAL '30 days' "
               "GROUP BY item_name ORDER BY returned_units DESC LIMIT 10",
    },
]
