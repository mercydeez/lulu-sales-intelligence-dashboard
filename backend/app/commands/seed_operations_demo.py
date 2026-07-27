"""Seed the three Operations Copilot demo scenarios — reset-safe and repeatable.

Run after a clean stack (docker compose down -v; up) or any time you want the
demo in a known state:

    docker exec sales_backend python -m app.commands.seed_operations_demo

It shapes real demo-tenant inventory and inserts three findings so the copilot
deterministically produces one of each MVP action:

  1. REPLENISHMENT — an item out of stock at one store, with NO surplus sibling,
     so the only safe move is to draft a replenishment.
  2. TRANSFER — an item out of stock at one store while another store of the same
     tenant is heavily overstocked, so a stock transfer is the safe move.
  3. INVESTIGATION — a revenue_drop finding that needs a bounded investigation.

Idempotent: findings upsert on their dedupe_key, inventory is set (not added),
and any prior demo copilot rows for these findings are cleared first. It never
touches another tenant and never fabricates a completed order — everything it
creates is a finding the copilot then reasons about.
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import text

from app.services.database import async_session, apply_tenant_guc, tenant_context
from app.config import get_settings

logger = logging.getLogger(__name__)

TENANT = get_settings().demo_tenant_id

# Deterministic picks from the demo seed (Meridian tenant). Chosen so the three
# scenarios use different items/stores and never collide.
REPLENISH_ITEM = 1     # Basmati Rice (5kg)
REPLENISH_STORE = 1    # Al Barsha
TRANSFER_ITEM = 3      # Fresh Chicken (1kg)
TRANSFER_OOS_STORE = 2     # Deira — out of stock
TRANSFER_SURPLUS_STORE = 3  # Karama — overstocked donor
INVESTIGATE_STORE = 4  # Mushrif Mall

DEMO_DEDUPE = ("opsdemo:replenish", "opsdemo:transfer", "opsdemo:investigate")


async def _clear_prior(db):
    """Remove any copilot rows from a previous demo run so it is repeatable.
    Order matters: audit events reference runs with ON DELETE NO ACTION."""
    run_ids = (await db.execute(text(
        "SELECT r.id FROM operations_runs r JOIN findings f ON f.id = r.finding_id "
        "WHERE r.tenant_id = :t AND f.dedupe_key = ANY(:dk)"),
        {"t": TENANT, "dk": list(DEMO_DEDUPE)})).scalars().all()
    if run_ids:
        await db.execute(text("DELETE FROM operations_events WHERE run_id = ANY(:r)"),
                         {"r": run_ids})
        await db.execute(text("DELETE FROM operations_proposals WHERE run_id = ANY(:r)"),
                         {"r": run_ids})
        await db.execute(text("DELETE FROM operations_runs WHERE id = ANY(:r)"),
                         {"r": run_ids})
    await db.execute(text(
        "DELETE FROM action_drafts WHERE tenant_id = :t AND created_by = 'copilot' "
        "AND finding_id IN (SELECT id FROM findings WHERE dedupe_key = ANY(:dk))"),
        {"t": TENANT, "dk": list(DEMO_DEDUPE)})


async def _set_stock(db, store_id, item_id, stock, reorder=50, ads=None):
    """Force an inventory row to a known posture (idempotent upsert)."""
    await db.execute(text(
        "UPDATE inventory SET current_stock = :s, reorder_point = :r "
        + (", average_daily_sales = :a " if ads is not None else "")
        + "WHERE store_id = :st AND item_id = :it"),
        {"s": stock, "r": reorder, "st": store_id, "it": item_id,
         **({"a": ads} if ads is not None else {})})


async def _velocity(db, store_id, item_id) -> float:
    v = (await db.execute(text(
        "SELECT average_daily_sales FROM metric_inventory_state "
        "WHERE tenant_id = :t AND store_id = :s AND item_id = :i"),
        {"t": TENANT, "s": store_id, "i": item_id})).scalar_one_or_none()
    return float(v or 0)


async def _upsert_finding(db, *, rule, category, severity, title, detail, evidence,
                          entity_type, entity_id, entity_name, metric_value,
                          action_type, dedupe_key) -> int:
    return (await db.execute(text(
        "INSERT INTO findings (tenant_id, rule, category, severity, title, detail, "
        "evidence, entity_type, entity_id, entity_name, metric_value, status, "
        "recommended_action, action_type, dedupe_key) VALUES "
        "(:t, :rule, :cat, :sev, :title, :detail, CAST(:ev AS jsonb), :etype, :eid, "
        ":ename, :mv, 'open', :rec, :atype, :dk) "
        "ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET status = 'open', "
        "detected_at = now(), updated_at = now(), evidence = EXCLUDED.evidence, "
        "metric_value = EXCLUDED.metric_value RETURNING id"),
        {"t": TENANT, "rule": rule, "cat": category, "sev": severity, "title": title,
         "detail": detail, "ev": json.dumps(evidence), "etype": entity_type,
         "eid": str(entity_id), "ename": entity_name, "mv": metric_value,
         "rec": "See Operations Copilot", "atype": action_type, "dk": dedupe_key},
    )).scalar_one()


async def seed() -> dict:
    tenant_context.set(TENANT)
    async with async_session() as db:
        await apply_tenant_guc(db)
        await _clear_prior(db)

        # --- Scenario 1: REPLENISHMENT (no surplus sibling) -----------------
        # Out of stock at one store; make every OTHER store's stock modest so no
        # donor qualifies -> the copilot must replenish, not transfer.
        for sid in range(1, 11):
            await _set_stock(db, sid, REPLENISH_ITEM, stock=(0 if sid == REPLENISH_STORE else 40),
                             reorder=50)
        v1 = await _velocity(db, REPLENISH_STORE, REPLENISH_ITEM)
        f1 = await _upsert_finding(
            db, rule="stockout", category="inventory", severity="high",
            title="Basmati Rice (5kg) is out of stock at Al Barsha",
            detail="Zero on-hand at Al Barsha with steady daily demand.",
            evidence={"average_daily_sales": v1, "current_stock": 0},
            entity_type="item", entity_id=REPLENISH_ITEM, entity_name="Basmati Rice (5kg)",
            metric_value=v1, action_type="reorder", dedupe_key="opsdemo:replenish")

        # --- Scenario 2: TRANSFER (surplus sibling exists) ------------------
        await _set_stock(db, TRANSFER_OOS_STORE, TRANSFER_ITEM, stock=0, reorder=50)
        # Heavy surplus at the donor store, and a low velocity there so it can spare.
        await _set_stock(db, TRANSFER_SURPLUS_STORE, TRANSFER_ITEM, stock=600, reorder=50, ads=2)
        for sid in range(1, 11):
            if sid in (TRANSFER_OOS_STORE, TRANSFER_SURPLUS_STORE):
                continue
            await _set_stock(db, sid, TRANSFER_ITEM, stock=30, reorder=50)
        v2 = await _velocity(db, TRANSFER_OOS_STORE, TRANSFER_ITEM)
        f2 = await _upsert_finding(
            db, rule="stockout", category="inventory", severity="critical",
            title="Fresh Chicken (1kg) is out of stock at Deira City Centre",
            detail="Zero on-hand at Deira while Karama is heavily overstocked.",
            evidence={"average_daily_sales": v2, "current_stock": 0},
            entity_type="item", entity_id=TRANSFER_ITEM, entity_name="Fresh Chicken (1kg)",
            metric_value=v2, action_type="reorder", dedupe_key="opsdemo:transfer")

        # --- Scenario 3: INVESTIGATION (revenue drop) -----------------------
        f3 = await _upsert_finding(
            db, rule="revenue_drop", category="sales", severity="high",
            title="Revenue down 22% week-over-week at Mushrif Mall",
            detail="Week-over-week revenue fell 22% at Mushrif Mall.",
            evidence={"current_week": 8000, "prior_week": 10256},
            entity_type="store", entity_id=INVESTIGATE_STORE, entity_name="Mushrif Mall",
            metric_value=-0.22, action_type="investigate", dedupe_key="opsdemo:investigate")

        await db.commit()
        result = {"replenishment_finding_id": f1, "transfer_finding_id": f2,
                  "investigation_finding_id": f3}
        logger.info("operations demo seeded: %s", result)
        return result


if __name__ == "__main__":
    out = asyncio.run(seed())
    print("Operations Copilot demo seeded:")
    for k, v in out.items():
        print(f"  {k}: {v}")
    print("\nRun the copilot on each with:")
    print("  POST /api/operations/findings/{finding_id}/recommend")
