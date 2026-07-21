"""
The data trust gate — is the input good enough to spend money on?

Board pack v3 §10: before AI drives a decision, compute a data-readiness result
and return READY / READY_WITH_WARNINGS / NOT_READY with blocking reasons, because
"a stale or low-confidence model must not silently drive a financial commitment."
The go-to-market plan reaches the same requirement from the other side, rating
"real POS data quality poisons the holdout" as a HIGH risk: the lighthouse proof
is only worth having if the inputs underneath it were sound.

Both land on one artifact, so this is one artifact.

WHAT IT DOES NOT DO. It does not judge whether a campaign is a good idea — that
is the optimizer's job, and this runs before it. It only answers whether the
NUMBERS THE OPTIMIZER WILL READ can be trusted. A campaign can be perfectly
sensible and still be refused here because the price list has holes in it.

FAILING OPEN vs FAILING SHUT. Each check picks deliberately:
  * Absence of a SIGNAL fails open (a fresh install has no sales history yet;
    refusing every campaign on a new deployment is not shippable).
  * Presence of a CONTRADICTION fails shut (negative stock is not "no data", it
    is data that is definitely wrong, and every number derived from it is too).

Enforced at exactly two points, both money-adjacent: simulate() attaches the
verdict and refuses NOT_READY, and activate() refuses NOT_READY. Everything else
can read it advisory-only.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import inventory_atp

logger = logging.getLogger(__name__)

READY = "READY"
READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
NOT_READY = "NOT_READY"

#: Newest sale older than this and the demand baseline is describing the past.
MAX_SALES_STALENESS_DAYS = int(os.environ.get("FLYWHEEL_MAX_SALES_STALENESS_DAYS", "7"))
#: An active model trained longer ago than this is flagged, not blocked — the
#: rule tier is the documented production path, so age is information.
MAX_MODEL_AGE_DAYS = int(os.environ.get("FLYWHEEL_MAX_MODEL_AGE_DAYS", "90"))
#: Below this share of in-scope items carrying a cost, margin is mostly fiction.
MIN_COST_COVERAGE = float(os.environ.get("FLYWHEEL_MIN_COST_COVERAGE", "0.50"))
#: Below this share of contactable customers consenting, the audience is a
#: rump and the readout will not generalise.
MIN_CONSENT_COVERAGE = float(os.environ.get("FLYWHEEL_MIN_CONSENT_COVERAGE", "0.50"))
#: A treatment arm smaller than this cannot show a lift that means anything.
MIN_TREATMENT_ARM = int(os.environ.get("FLYWHEEL_MIN_TREATMENT_ARM", "30"))


class DataNotReady(ValueError):
    """Raised when a money-adjacent action is attempted on untrustworthy input."""

    def __init__(self, report: Dict[str, Any], action: str):
        self.report = report
        self.action = action
        blockers = "; ".join(f["detail"] for f in report["findings"]
                             if f["severity"] == "block")
        super().__init__(
            f"Refused to {action}: input data is NOT_READY — {blockers}")


@dataclass
class Finding:
    code: str
    severity: str          # 'block' | 'warn'
    detail: str
    evidence: Dict[str, Any]


def verdict_for(findings: List[Finding]) -> str:
    if any(f.severity == "block" for f in findings):
        return NOT_READY
    if findings:
        return READY_WITH_WARNINGS
    return READY


async def _campaign_stores(db: AsyncSession, tenant_id: int,
                           campaign_id: Optional[int]) -> List[int]:
    """The stores actually in play — the home stores of the built audience.

    Falls back to every store in the tenant when there is no audience yet, so the
    gate is answerable before the audience step as well as after it.
    """
    if campaign_id is not None:
        rows = (await db.execute(
            text("""SELECT DISTINCT c.home_store_id
                      FROM flywheel_campaign_audience a
                      JOIN flywheel_customers c ON c.id = a.customer_id
                     WHERE a.tenant_id = :t AND a.campaign_id = :c
                       AND c.home_store_id IS NOT NULL"""),
            {"t": tenant_id, "c": campaign_id})).fetchall()
        if rows:
            return [int(r[0]) for r in rows]
    rows = (await db.execute(
        text("SELECT id FROM stores WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    return [int(r[0]) for r in rows]


async def evaluate(db: AsyncSession, *, tenant_id: int,
                   campaign_id: Optional[int] = None) -> Dict[str, Any]:
    """Run every check and return the verdict. Read-only."""
    findings: List[Finding] = []
    stores = await _campaign_stores(db, tenant_id, campaign_id)

    # --- 1. sales history: can a no-campaign baseline exist at all? ---------
    sales = (await db.execute(
        text("""SELECT MAX(date), COUNT(*) FROM sales_fact_view WHERE tenant_id = :t"""),
        {"t": tenant_id})).fetchone()
    last_sale, sale_rows = (sales[0], int(sales[1] or 0)) if sales else (None, 0)

    if sale_rows == 0:
        findings.append(Finding(
            "no_sales_history", "block",
            "No sales history for this tenant — there is no baseline to measure a "
            "campaign against, so any 'incremental' number would be invented",
            {"rows": 0}))
    elif last_sale is not None:
        age_days = (date.today() - last_sale).days
        if age_days > MAX_SALES_STALENESS_DAYS:
            findings.append(Finding(
                "sales_feed_stale", "warn",
                f"Newest sale is {age_days} days old (limit {MAX_SALES_STALENESS_DAYS}) — "
                "the demand baseline describes the past, not the campaign window",
                {"last_sale": str(last_sale), "age_days": age_days}))

    # --- 2. contradictions in stock: negative is wrong, not merely absent ---
    if stores:
        neg = (await db.execute(
            text("""SELECT COUNT(*) FROM inventory
                     WHERE store_id = ANY(:s) AND current_stock < 0"""),
            {"s": stores})).scalar()
        if int(neg or 0) > 0:
            findings.append(Finding(
                "inventory_impossible", "block",
                f"{neg} inventory row(s) hold negative stock — available-to-promise "
                "and every allocation derived from it would be wrong",
                {"negative_rows": int(neg), "stores": len(stores)}))

        # --- 3. is the stock FEED alive? (reuses the ATP freshness rule) ----
        stale_stores = [s for s in stores
                        if not await inventory_atp.inventory_freshness_ok(
                            db, store_id=s, item_id=0)]
        if stale_stores:
            findings.append(Finding(
                "inventory_feed_stale", "warn",
                f"{len(stale_stores)} of {len(stores)} store(s) have an inventory feed "
                f"older than {inventory_atp.MAX_INVENTORY_STALENESS_HOURS}h — stock "
                "promises there rest on numbers nobody has confirmed recently",
                {"stale_store_ids": stale_stores[:20], "total_stores": len(stores)}))

    # --- 4. price and cost coverage: can margin be computed honestly? -------
    items = (await db.execute(
        text("""SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE unit_price_aed IS NULL OR unit_price_aed <= 0) AS no_price,
                       COUNT(*) FILTER (WHERE unit_cost_aed IS NULL OR unit_cost_aed <= 0) AS no_cost
                  FROM items WHERE tenant_id = :t"""),
        {"t": tenant_id})).mappings().fetchone()
    total_items = int(items["total"] or 0)
    no_price = int(items["no_price"] or 0)
    no_cost = int(items["no_cost"] or 0)

    if total_items == 0:
        findings.append(Finding(
            "no_item_catalogue", "block",
            "No items for this tenant — there is nothing to promote",
            {"items": 0}))
    else:
        if no_price:
            findings.append(Finding(
                "item_price_missing", "block",
                f"{no_price} of {total_items} item(s) have no sell price — a discount "
                "cannot be priced and margin cannot be checked against the floor",
                {"missing": no_price, "total": total_items}))
        cost_coverage = 1.0 - (no_cost / total_items)
        if cost_coverage < MIN_COST_COVERAGE:
            findings.append(Finding(
                "item_cost_coverage_low", "block",
                f"Only {cost_coverage:.0%} of items carry a unit cost (floor "
                f"{MIN_COST_COVERAGE:.0%}) — margin would be largely fabricated",
                {"coverage": round(cost_coverage, 3), "missing": no_cost,
                 "total": total_items}))
        elif no_cost:
            findings.append(Finding(
                "item_cost_missing_some", "warn",
                f"{no_cost} of {total_items} item(s) have no unit cost — margin for "
                "those is unknown and must not be reported as zero",
                {"missing": no_cost, "total": total_items}))

    # --- 5. consent coverage for the campaign's channel --------------------
    if campaign_id is not None:
        channel = (await db.execute(
            text("SELECT channel FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"),
            {"c": campaign_id, "t": tenant_id})).scalar()
        if channel:
            consent = (await db.execute(
                text("""SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE granted) AS granted
                          FROM flywheel_customer_consents
                         WHERE tenant_id = :t AND channel = :ch"""),
                {"t": tenant_id, "ch": channel})).mappings().fetchone()
            c_total = int(consent["total"] or 0)
            c_granted = int(consent["granted"] or 0)
            # No consent records at all is absence of signal, not a contradiction:
            # a tenant that has never captured consent is a setup gap, flagged as
            # a warning so the operator sees it before contacting anyone.
            if c_total == 0:
                findings.append(Finding(
                    "consent_not_captured", "warn",
                    f"No consent records for channel '{channel}' — nobody is "
                    "confirmed contactable on it",
                    {"channel": channel}))
            else:
                coverage = c_granted / c_total
                if coverage < MIN_CONSENT_COVERAGE:
                    findings.append(Finding(
                        "consent_coverage_low", "warn",
                        f"Only {coverage:.0%} of customers consent to '{channel}' "
                        f"(floor {MIN_CONSENT_COVERAGE:.0%}) — the reachable audience "
                        "is a rump and the readout will not generalise",
                        {"channel": channel, "coverage": round(coverage, 3),
                         "granted": c_granted, "total": c_total}))

        # --- 6. is the treatment arm big enough to mean anything? ----------
        arm = (await db.execute(
            text("""SELECT COUNT(*) FROM flywheel_campaign_audience
                     WHERE tenant_id = :t AND campaign_id = :c AND assignment = 'treatment'"""),
            {"t": tenant_id, "c": campaign_id})).scalar()
        arm = int(arm or 0)
        if arm and arm < MIN_TREATMENT_ARM:
            findings.append(Finding(
                "treatment_arm_thin", "warn",
                f"Treatment arm is {arm} customers (floor {MIN_TREATMENT_ARM}) — a lift "
                "measured on this few will not separate from noise",
                {"treatment": arm, "floor": MIN_TREATMENT_ARM}))

    # --- 7. model availability and age ------------------------------------
    model = (await db.execute(
        text("""SELECT version_label, trained_at,
                       EXTRACT(EPOCH FROM (now() - trained_at)) / 86400 AS age_days
                  FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = 'churn' AND is_active
                 ORDER BY trained_at DESC LIMIT 1"""),
        {"t": tenant_id})).mappings().fetchone()
    if not model:
        # This is the DOCUMENTED production state, not a fault: the rule tier
        # runs until real outcome windows justify promoting a model. It is
        # surfaced so nobody believes a model is driving decisions when none is.
        findings.append(Finding(
            "no_active_model", "warn",
            "No active churn model — decisions run on the deterministic rule tier "
            "(the documented state until real outcome data exists)",
            {"model_kind": "churn"}))
    elif model["age_days"] is not None and float(model["age_days"]) > MAX_MODEL_AGE_DAYS:
        findings.append(Finding(
            "model_stale", "warn",
            f"Active churn model '{model['version_label']}' was trained "
            f"{int(float(model['age_days']))} days ago (limit {MAX_MODEL_AGE_DAYS})",
            {"version_label": model["version_label"],
             "age_days": int(float(model["age_days"]))}))

    status = verdict_for(findings)
    return {
        "status": status,
        "campaign_id": campaign_id,
        "findings": [asdict(f) for f in findings],
        "blockers": [f.code for f in findings if f.severity == "block"],
        "warnings": [f.code for f in findings if f.severity == "warn"],
        "scope": {"stores_evaluated": len(stores), "items_evaluated": total_items},
        "thresholds": {
            "max_sales_staleness_days": MAX_SALES_STALENESS_DAYS,
            "max_inventory_staleness_hours": inventory_atp.MAX_INVENTORY_STALENESS_HOURS,
            "min_cost_coverage": MIN_COST_COVERAGE,
            "min_consent_coverage": MIN_CONSENT_COVERAGE,
            "min_treatment_arm": MIN_TREATMENT_ARM,
            "max_model_age_days": MAX_MODEL_AGE_DAYS,
        },
    }


async def assert_ready(db: AsyncSession, *, tenant_id: int, campaign_id: Optional[int],
                       action: str) -> Dict[str, Any]:
    """Evaluate and REFUSE on NOT_READY. Returns the report when it passes, so
    the caller can attach it to its own response."""
    report = await evaluate(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if report["status"] == NOT_READY:
        logger.warning("flywheel.data_trust refused %s for campaign=%s: %s",
                       action, campaign_id, report["blockers"])
        raise DataNotReady(report, action)
    return report
