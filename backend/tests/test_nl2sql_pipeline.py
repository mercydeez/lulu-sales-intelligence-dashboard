"""
Integration tests for the Sage NL->SQL pipeline (A2).

Uses a fake LLM provider that returns canned SQL/narration, so we exercise the
guard -> sage_ro execution -> narration path against the REAL database without
needing a model. Auto-skips when the DB (sage_ro) is unreachable, so the DB-free
unit suite is unaffected; the CI smoke job runs these against a live stack.
"""
import asyncio
from typing import AsyncGenerator, Dict, List

import pytest

from app.services.nl2sql import answer_question
from app.services.nl2sql.executor import execute_sage_sql


class FakeProvider:
    """Returns `sql_out` for the SQL-writing call and `narration_out` otherwise."""
    name = "fake"

    def __init__(self, sql_out: str, narration_out: str = "Here is your answer."):
        self.sql_out = sql_out
        self.narration_out = narration_out

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        system = messages[0]["content"] if messages else ""
        return self.sql_out if "SQL writer" in system else self.narration_out

    async def stream(self, messages):  # pragma: no cover - unused here
        yield await self.complete(messages)


def _db_available() -> bool:
    async def _check():
        try:
            await execute_sage_sql("SELECT * FROM (SELECT 1) q LIMIT 1", tenant_id=1)
            return True
        except Exception:
            return False
    try:
        return asyncio.run(_check())
    except RuntimeError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="sage_ro DB not reachable")


async def test_valid_question_returns_rows_and_answer():
    p = FakeProvider("SELECT category, revenue_aed FROM sage_category_performance ORDER BY revenue_aed DESC")
    res = await answer_question("revenue by category", tenant_id=1, providers=[p])
    assert res.ok, res.reason
    assert res.rows, "expected category rows"
    assert "category" in res.rows[0] and "revenue_aed" in res.rows[0]
    assert res.answer


async def test_guard_blocks_cross_table_read():
    p = FakeProvider("SELECT * FROM users")
    res = await answer_question("dump users", tenant_id=1, providers=[p])
    assert not res.ok
    assert res.reason.startswith("guard")


async def test_ddl_is_blocked_before_execution():
    p = FakeProvider("DROP TABLE sage_sales")
    res = await answer_question("delete everything", tenant_id=1, providers=[p])
    assert not res.ok and res.reason.startswith("guard")


async def test_tenant_isolation_through_pipeline():
    """Same query, different tenants -> different row counts (DB-enforced via GUC)."""
    sql = "SELECT count(*) AS n FROM sage_sales"
    p = FakeProvider(sql)
    r1 = await answer_question("how many sales rows", tenant_id=1, providers=[p])
    r2 = await answer_question("how many sales rows", tenant_id=2, providers=[p])
    assert r1.ok and r2.ok
    n1, n2 = r1.rows[0]["n"], r2.rows[0]["n"]
    assert n1 > n2, f"tenant 1 ({n1}) should have more rows than tenant 2 ({n2})"
    assert n2 > 0  # tenant 2 has its own seeded data, just less


async def test_no_provider_falls_back():
    res = await answer_question("anything", tenant_id=1, providers=[])
    assert not res.ok and "no LLM" in res.reason


class RepairingProvider:
    """First SQL attempt references a column that doesn't exist on the view
    (the exact real-world mistake: adding a date filter to a no-date
    performance view); the repair call — recognizable by the error text fed
    back in the user message — returns valid SQL."""
    name = "fake"

    def __init__(self, bad_sql: str, good_sql: str, narration_out: str = "Here is your answer."):
        self.bad_sql = bad_sql
        self.good_sql = good_sql
        self.narration_out = narration_out
        self.sql_calls = 0

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        if "SQL writer" not in system:
            return self.narration_out
        self.sql_calls += 1
        return self.good_sql if "failed" in user else self.bad_sql

    async def stream(self, messages):  # pragma: no cover - unused here
        yield await self.complete(messages)


async def test_execution_error_self_repairs_once():
    p = RepairingProvider(
        bad_sql="SELECT store_name, revenue_aed FROM sage_store_performance "
                "WHERE date >= CURRENT_DATE - INTERVAL '30 days'",  # no `date` column: errors
        good_sql="SELECT store_name, revenue_aed FROM sage_store_performance "
                 "ORDER BY revenue_aed DESC LIMIT 5",
    )
    res = await answer_question("top stores this month", tenant_id=1, providers=[p])
    assert res.ok, res.reason
    assert p.sql_calls == 2, "expected exactly one repair attempt after the execution error"


async def test_unrepairable_error_still_falls_back_after_one_retry():
    p = RepairingProvider(bad_sql="SELECT * FROM sage_sales WHERE nonexistent_col = 1",
                          good_sql="SELECT * FROM sage_sales WHERE also_nonexistent = 1")
    res = await answer_question("broken query", tenant_id=1, providers=[p])
    assert not res.ok
    assert p.sql_calls == 2  # gives up after the single repair attempt, no infinite loop
