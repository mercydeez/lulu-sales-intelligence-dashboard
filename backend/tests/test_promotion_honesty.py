"""P1.1 honesty guard: promotion suggestions/performance must never present a
fabricated (random) number as an estimate. 'Honesty is the brand.'

These are source-inspection guards — they don't need a DB — so a future edit that
reintroduces random.randint/uniform/choice into a metric field fails CI.
"""
import inspect

from app.routes import promotions


def _fn_source(name: str) -> str:
    return inspect.getsource(getattr(promotions, name))


def test_suggestions_do_not_fabricate_lift_or_discount():
    src = _fn_source("get_promotion_suggestions")
    # No randomness in the derivation.
    assert "random." not in src, "promotion suggestions must not use random values"
    # The lift is derived and carries an explicit basis.
    assert "estimated_lift_pct" in src
    assert "basis" in src
    # Uses the real price, not a category cost constant.
    assert "unit_price_aed" in src
    assert "CATEGORY_COSTS" not in src


def test_performance_reports_real_revenue_and_no_invented_redemptions():
    src = _fn_source("get_promotion_performance")
    assert "random." not in src, "promotion performance must not use random values"
    # Revenue derived from units * real price.
    assert "unit_price_aed" in src
    # Redemptions/discounts are null (not invented) absent a promo-event source.
    assert "estimated_redemptions" in src
    assert '"estimated_redemptions": None' in src
