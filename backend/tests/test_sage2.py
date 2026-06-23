"""
Sage v2 (decompose-route-recompose) tests. Intent matching / zone extraction /
multipart detection are pure (DB-free). The end-to-end recompose of the flagship
multi-part question is integration (skips without sage_ro DB; runs in CI smoke).
"""
import asyncio
import pytest

from app.services.sage2 import is_multipart
from app.services.sage2.intents import match_intents, extract_zone
from app.services.sage2.orchestrator import answer_multipart
from app.services.nl2sql.executor import execute_sage_sql

FLAGSHIP = ("For the North zone versus our 2025-2030 strategy: what is the company 2030 revenue "
            "target per the strategy document, the total primary sales revenue, the total CRM "
            "pipeline expected revenue, which distributors serve the North zone, and the average "
            "online selling price of our brands?")


# --- pure ------------------------------------------------------------------
def test_zone_extraction():
    assert extract_zone(FLAGSHIP) == "North"
    assert extract_zone("total revenue last week") is None


def test_flagship_matches_five_intents():
    names = {i.name for i in match_intents(FLAGSHIP)}
    assert {"revenue_target", "primary_sales_revenue", "crm_pipeline_revenue",
            "distributors_in_zone", "avg_online_price"} <= names
    assert is_multipart(FLAGSHIP)


def test_single_part_not_multipart():
    assert not is_multipart("what was total revenue last week?")


# --- integration (needs sage_ro DB) ----------------------------------------
def _db_up() -> bool:
    async def _c():
        try:
            await execute_sage_sql("SELECT * FROM (SELECT 1) q LIMIT 1", 1)
            return True
        except Exception:
            return False
    try:
        return asyncio.run(_c())
    except RuntimeError:
        return False


pytestmark_db = pytest.mark.skipif(not _db_up(), reason="sage_ro DB not reachable")


@pytestmark_db
async def test_flagship_recomposes_all_parts():
    res = await answer_multipart(FLAGSHIP, tenant_id=1, role="admin", providers=[])
    assert res.ok, res.reason
    labels = {p.label for p in res.parts}
    assert len(res.parts) == 5
    # CRM North pipeline must equal the seeded total; distributors list must be present.
    crm = next(p for p in res.parts if p.label.startswith("CRM pipeline"))
    assert crm.ok and crm.rows and list(crm.rows[0].values())[0] == 3447836
    dist = next(p for p in res.parts if p.label.startswith("Distributors"))
    assert dist.ok and len(dist.rows) == 8
    assert "| Metric | Value | Source |" in res.answer
