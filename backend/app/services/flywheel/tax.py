"""Tax — because a margin floor checked on a tax-inclusive price is a lie.

THE PROBLEM THIS SOLVES. UAE retail displays tax-inclusive shelf prices. If a
tomato is 10.00 AED on the shelf, 0.48 of that is VAT the retailer collects and
remits — it was never revenue. v1 treated the whole 10.00 as revenue, so a
campaign passing a "10% minimum margin" gate was actually earning about 4.8%.
The gate looked like a control and was quietly off by the VAT rate on every
single decision.

THE RULE, ONCE: **margin is always evaluated net of tax.** Tax is not revenue
and not margin; it is money held on behalf of the tax authority.

ROUNDING POLICY (§A1 of the hardening addendum). Money is quantized to fils
(2dp) with ROUND_HALF_EVEN — banker's rounding — at each PERSISTED boundary,
not at every intermediate step. Half-even is used rather than half-up because
half-up is biased upward: over many roundings it systematically inflates
totals, which is exactly the error a finance team will eventually find. Per-line
rounding is applied (each line item is rounded, then summed) to match how a
receipt is printed, so the system's total equals the customer's total.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: Used when a tenant has configured no rule at all. Zero, not 5% — assuming a
#: tax rate nobody configured would silently change every margin figure. Absence
#: of configuration must mean "no tax applied", visibly.
DEFAULT_RATE = Decimal("0")

_HUNDRED = Decimal("100")


def bankers(value: Any) -> Decimal:
    """Quantize to fils with ROUND_HALF_EVEN. The one rounding door."""
    if value is None:
        return ZERO
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class TaxRule:
    rate_pct: Decimal
    prices_include_tax: bool
    name: str = "none"

    @property
    def multiplier(self) -> Decimal:
        """1 + rate, e.g. 1.05 for 5% VAT."""
        return Decimal("1") + (self.rate_pct / _HUNDRED)

    def net_of_tax(self, gross: Decimal) -> Decimal:
        """Strip tax from a displayed price.

        When prices EXCLUDE tax the displayed figure is already net, so this is
        the identity — returning gross/1.05 there would under-count revenue by
        the rate, which is the same class of bug in the opposite direction.
        """
        if self.rate_pct <= 0 or not self.prices_include_tax:
            return bankers(gross)
        return bankers(Decimal(str(gross)) / self.multiplier)

    def tax_on(self, gross: Decimal) -> Decimal:
        """The tax component of a displayed price."""
        return bankers(Decimal(str(gross)) - self.net_of_tax(gross))

    def gross_from_net(self, net: Decimal) -> Decimal:
        if self.rate_pct <= 0 or not self.prices_include_tax:
            return bankers(net)
        return bankers(Decimal(str(net)) * self.multiplier)


NO_TAX = TaxRule(rate_pct=DEFAULT_RATE, prices_include_tax=True, name="none")

#: Per-process cache. Tax rules change perhaps yearly; re-reading them on every
#: decision would add a query to the hot path for data that is effectively
#: static. Keyed by (tenant, category) so a category-specific rule still wins.
_CACHE: Dict[tuple, TaxRule] = {}


async def rule_for(
    db: AsyncSession, *, tenant_id: int, category: Optional[str] = None,
    use_cache: bool = True,
) -> TaxRule:
    """The applicable tax rule, preferring a category-specific one.

    Falls back to NO_TAX rather than to a guessed national rate: a system that
    invents a tax rate is worse than one that visibly applies none.
    """
    key = (tenant_id, category)
    if use_cache and key in _CACHE:
        return _CACHE[key]

    row = (await db.execute(
        text("""SELECT rate_pct, prices_include_tax, name
                  FROM flywheel_tax_rules
                 WHERE tenant_id = :t AND is_active = TRUE
                   AND valid_from <= CURRENT_DATE
                   AND (valid_until IS NULL OR valid_until > CURRENT_DATE)
                   AND (category = :cat OR category IS NULL)
                 ORDER BY (category IS NOT NULL) DESC, valid_from DESC
                 LIMIT 1"""),
        {"t": tenant_id, "cat": category},
    )).fetchone()

    rule = TaxRule(rate_pct=Decimal(str(row[0])), prices_include_tax=bool(row[1]),
                   name=row[2]) if row else NO_TAX
    if use_cache:
        _CACHE[key] = rule
    return rule


def clear_cache() -> None:
    """Drop the cached rules — call after editing tax configuration."""
    _CACHE.clear()


def margin_net_pct(
    *, gross_price: Decimal, unit_cost: Decimal, discount_pct: Decimal,
    rule: TaxRule,
) -> Dict[str, Decimal]:
    """Margin on the NET-OF-TAX selling price, after discount.

    Returns every intermediate so the Decision Trace can show the arithmetic
    rather than assert a percentage. The discount is applied to the GROSS
    (shelf) price because that is what the customer sees and what the till
    charges; tax is then stripped from the discounted amount.

    Cost is treated as already net of recoverable input VAT, which is the normal
    retail convention — input VAT is reclaimed, so it is not a cost of goods.
    """
    gross_price = money(gross_price)
    unit_cost = money(unit_cost)
    discount_pct = Decimal(str(discount_pct))

    discount_amount = bankers(gross_price * discount_pct / _HUNDRED)
    gross_after_discount = bankers(gross_price - discount_amount)

    net_revenue = rule.net_of_tax(gross_after_discount)
    tax_amount = bankers(gross_after_discount - net_revenue)
    margin_amount = bankers(net_revenue - unit_cost)

    margin_pct = (bankers(margin_amount / net_revenue * _HUNDRED)
                  if net_revenue > ZERO else Decimal("-100.00"))

    return {
        "gross_price": gross_price,
        "discount_amount": discount_amount,
        "gross_after_discount": gross_after_discount,
        "tax_amount": tax_amount,
        "net_revenue": net_revenue,
        "unit_cost": unit_cost,
        "margin_amount": margin_amount,
        "margin_pct": margin_pct,
        "tax_rate_pct": rule.rate_pct,
    }


def breakdown_note(result: Dict[str, Decimal], rule: TaxRule) -> str:
    """One human-readable line for the UI, showing the tax was handled."""
    if rule.rate_pct <= 0:
        return (f"No tax rule configured — margin {result['margin_pct']}% is on "
                f"the full {result['gross_after_discount']} AED.")
    return (
        f"{result['gross_after_discount']} AED incl. {rule.rate_pct}% VAT "
        f"({result['tax_amount']} AED) = {result['net_revenue']} AED net; "
        f"less {result['unit_cost']} cost = {result['margin_amount']} AED "
        f"({result['margin_pct']}% net margin)."
    )
