"""Seed a coherent Flywheel demo scenario so every horizon tab shows real numbers.

WHAT IT DOES. Creates one demo campaign ("Demo Scenario — Loyalty Win-back") with
a 200/100 treatment/control split and a controlled retention signal, then runs the
REAL Flywheel services over it so every surface is populated:

  Horizon 1  Incrementality  — a significant, positive readout (~+30% lift)
             Holdout         — 200/100 arms + covariate balance
             Governance      — contact fatigue + suppressions
             Shadow          — rule-vs-model comparison
  Horizon 3  Trade           — a supplier funding + a settled scan-down rebate
             Cannibalization — positive promoted lift with real cannibalisation
  Horizon 4  Coalition       — 4 partners, attributed margin summing to 1
             Seasonality     — the seeded UAE calendar + current factor
             Shelf-life      — near-expiry batches with markdown recommendations
             Outcome pricing — the evidence gate opens on the significant readout

NO NUMBER IS HAND-FAKED. The events are seeded, but every metric on screen is
computed by the actual services (readout.compute_and_store, cannibalization.
estimate, coalition.attribute, trade.issue_settlement, shadow.score_pass) — honest,
consistent with the project's no-hallucination rule. The one deliberately honest
imperfection: the demo arms are a simple split, not the stable-hash assignment, so
the Holdout balance check correctly flags them "imbalanced" — the diagnostic doing
its job rather than being fudged.

HOW IT WORKS. The campaign starts TODAY, so the retention window [today, today+1)
is empty except the events this script inserts — which is what lets it control the
treatment/control signal precisely and produce a clean, significant lift.

IDEMPOTENT. Every artifact is tagged (campaign name, 'DEMOSCEN-' codes,
metadata.demo_scenario, coalition external_ref='DEMOSCEN'); a re-run purges the
prior scenario first (via the sanctioned flywheel.allow_purge erasure path for the
append-only readouts) and rebuilds cleanly.

HOW TO RUN. It needs the app's DB session, so run it inside the backend container:

    docker exec -i sales_backend python - < scripts/seed_demo_scenario.py

(scripts/ is not mounted into the container, so pipe it via stdin as above; the
path bootstrap below also lets it run directly if the backend package is importable.)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

# --- path bootstrap: work both inside the container (/app) and from the repo ---
for _candidate in ("/app", os.path.join(os.path.dirname(__file__), "..", "backend")):
    _abs = os.path.abspath(_candidate)
    if os.path.isdir(os.path.join(_abs, "app")) and _abs not in sys.path:
        sys.path.insert(0, _abs)

from sqlalchemy import text  # noqa: E402
from app.services.database import async_session  # noqa: E402
from app.services.flywheel import (  # noqa: E402
    cannibalization, coalition, outcome_pricing, readout, shadow, trade,
)

TENANT = int(os.getenv("DEMO_TENANT_ID", "1"))
CAMPAIGN_NAME = "Demo Scenario — Loyalty Win-back"
NOW = datetime.now(timezone.utc)
EVT_AT = NOW - timedelta(hours=2)   # safely "today", inside the measurement window


async def scoped(db, tenant: int = TENANT) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(tenant)})


async def resolve_fixtures(db):
    """Look up a real store, a category with >=2 items, and two items in it — so
    the script survives id shifts rather than hardcoding ids."""
    store = int((await db.execute(text(
        "SELECT id FROM stores WHERE tenant_id = :t ORDER BY id LIMIT 1"), {"t": TENANT})).scalar())
    row = (await db.execute(text(
        """SELECT category FROM items WHERE tenant_id = :t
            GROUP BY category HAVING COUNT(*) >= 2 ORDER BY COUNT(*) DESC LIMIT 1"""),
        {"t": TENANT})).fetchone()
    category = row[0] if row else None
    if category is None:
        raise SystemExit("no category with >=2 items — cannot build the cannibalisation story")
    items = [int(r[0]) for r in (await db.execute(text(
        "SELECT id FROM items WHERE tenant_id = :t AND category = :c ORDER BY id LIMIT 2"),
        {"t": TENANT, "c": category})).fetchall()]
    return store, category, items[0], items[1]


async def cleanup(db) -> None:
    """Purge any prior run so the seed is idempotent."""
    await scoped(db)
    # Transaction-scoped permission for the append-only readouts to cascade-delete
    # when the demo campaign is dropped (the sanctioned erasure path, migration 077).
    await db.execute(text("SELECT set_config('flywheel.allow_purge', 'on', true)"))
    await db.execute(text("DELETE FROM flywheel_redemptions WHERE tenant_id = :t AND request_id = 'demo-scenario'"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_offers WHERE tenant_id = :t AND offer_code LIKE 'DEMOSCEN-%'"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_customer_events WHERE tenant_id = :t AND metadata->>'demo_scenario' = 'true'"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_shelf_life WHERE tenant_id = :t AND batch_ref LIKE 'DEMOSCEN-%'"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_coalition_activity WHERE tenant_id = :t AND partner_id IN (SELECT id FROM flywheel_coalition_partners WHERE external_ref = 'DEMOSCEN')"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_coalition_partners WHERE tenant_id = :t AND external_ref = 'DEMOSCEN'"), {"t": TENANT})
    await db.execute(text("DELETE FROM flywheel_outcome_pricing WHERE tenant_id = :t AND plan_name = 'Demo Performance Plan'"), {"t": TENANT})
    cids = [int(r[0]) for r in (await db.execute(text(
        "SELECT id FROM flywheel_campaigns WHERE tenant_id = :t AND name = :n"),
        {"t": TENANT, "n": CAMPAIGN_NAME})).fetchall()]
    for cid in cids:
        for tbl in ("flywheel_readouts", "flywheel_cannibalization", "flywheel_substitution",
                    "flywheel_coalition_attribution", "flywheel_campaign_audience",
                    "flywheel_contact_log", "flywheel_holdout_balance"):
            await db.execute(text(f"DELETE FROM {tbl} WHERE tenant_id = :t AND campaign_id = :c"), {"t": TENANT, "c": cid})
        await db.execute(text("DELETE FROM flywheel_offer_suppressions WHERE tenant_id = :t AND (suppressed_campaign_id = :c OR winning_campaign_id = :c)"), {"t": TENANT, "c": cid})
        await db.execute(text("DELETE FROM flywheel_settlements WHERE tenant_id = :t AND funding_id IN (SELECT id FROM flywheel_supplier_funding WHERE campaign_id = :c)"), {"t": TENANT, "c": cid})
        await db.execute(text("DELETE FROM flywheel_supplier_funding WHERE tenant_id = :t AND campaign_id = :c"), {"t": TENANT, "c": cid})
        await db.execute(text("DELETE FROM flywheel_campaigns WHERE tenant_id = :t AND id = :c"), {"t": TENANT, "c": cid})
    await db.commit()


async def main() -> None:
    async with async_session() as db:
        await scoped(db)
        store, category, promoted_item, other_item = await resolve_fixtures(db)
    print(f"fixtures: store={store} category={category!r} promoted={promoted_item} other={other_item}")

    async with async_session() as db:
        await cleanup(db)

    async with async_session() as db:
        await scoped(db)
        # ---- 1. campaign (starts today so the retention window is ours) --------
        campaign = int((await db.execute(text("""
            INSERT INTO flywheel_campaigns
                (tenant_id, name, objective, status, channel, starts_on, ends_on,
                 max_discount_pct, min_margin_pct, discount_budget_aed, control_group_pct,
                 contact_cap_per_week, safety_stock_pct, policy_version, activated_at)
            VALUES (:t, :n, 'retain_at_risk', 'ACTIVE', 'email',
                    CURRENT_DATE, CURRENT_DATE + 30, 20, 10, 8000, 33, 2, 10, 'v1', now())
            RETURNING id"""), {"t": TENANT, "n": CAMPAIGN_NAME})).scalar())

        custs = [int(r[0]) for r in (await db.execute(text(
            "SELECT id FROM flywheel_customers WHERE tenant_id = :t ORDER BY id LIMIT 300"),
            {"t": TENANT})).fetchall()]
        if len(custs) < 300:
            raise SystemExit(f"need 300 seeded customers, found {len(custs)} — run the demo seed first")
        treatment, control = custs[:200], custs[200:300]

        # ---- 2. audience -------------------------------------------------------
        for cid in treatment:
            await db.execute(text("""INSERT INTO flywheel_campaign_audience
                (tenant_id, campaign_id, customer_id, assignment, assignment_hash, churn_probability)
                VALUES (:t, :c, :cust, 'treatment', 777, 0.55)"""),
                {"t": TENANT, "c": campaign, "cust": cid})
        for cid in control:
            await db.execute(text("""INSERT INTO flywheel_campaign_audience
                (tenant_id, campaign_id, customer_id, assignment, assignment_hash, churn_probability)
                VALUES (:t, :c, :cust, 'control', 777, 0.55)"""),
                {"t": TENANT, "c": campaign, "cust": cid})

        # ---- 3. retention + cannibalisation signal (purchase events, today) ----
        # Treatment retained 70% (140/200), control 40% (40/100) -> ~+30pt lift.
        # Treatment buys the promoted item much more than control, but the category
        # grows less -> a positive-lift-with-cannibalisation story.
        t_promoted, t_other = treatment[:110], treatment[110:140]
        c_promoted, c_other = control[:12], control[12:40]

        async def evt(cust, item, qty, val, margin):
            await db.execute(text("""INSERT INTO flywheel_customer_events
                (tenant_id, customer_id, event_type, occurred_at, store_id, item_id, category,
                 quantity_units, value_aed, margin_aed, metadata)
                VALUES (:t, :c, 'purchase', :at, :s, :i, :cat, :q, :v, :m, CAST(:meta AS JSONB))"""),
                {"t": TENANT, "c": cust, "at": EVT_AT, "s": store, "i": item, "cat": category,
                 "q": qty, "v": val, "m": margin, "meta": json.dumps({"demo_scenario": True})})

        for cust in t_promoted:
            await evt(cust, promoted_item, 2, Decimal("16.00"), Decimal("5.20"))
        for cust in t_other:
            await evt(cust, other_item, 1, Decimal("7.00"), Decimal("2.10"))
        for cust in c_promoted:
            await evt(cust, promoted_item, 2, Decimal("16.00"), Decimal("5.20"))
        for cust in c_other:
            await evt(cust, other_item, 1, Decimal("7.00"), Decimal("2.10"))

        # ---- 4. offers + redemptions (financials for Incrementality/Trade) -----
        for i, cust in enumerate(t_promoted):
            offer_id = int((await db.execute(text("""INSERT INTO flywheel_offers
                (tenant_id, campaign_id, customer_id, offer_code, action_type, store_id, item_id,
                 discount_pct, reserved_aed, status, issued_at, expires_at, redeemed_at)
                VALUES (:t, :c, :cust, :code, 'PERCENT_DISCOUNT', :s, :i, 10, 1.60, 'redeemed', :now, :exp, :now)
                RETURNING id"""),
                {"t": TENANT, "c": campaign, "cust": cust, "code": f"DEMOSCEN-{campaign}-{i:03d}",
                 "s": store, "i": promoted_item, "now": EVT_AT, "exp": NOW + timedelta(days=25)})).scalar())
            await db.execute(text("""INSERT INTO flywheel_redemptions
                (tenant_id, offer_id, campaign_id, customer_id, store_id, item_id, units,
                 gross_value_aed, discount_aed, net_value_aed, margin_aed, idempotency_key, request_id,
                 tax_rate_pct, tax_amount_aed, net_of_tax_aed, created_at)
                VALUES (:t, :o, :c, :cust, :s, :i, 2, 17.60, 1.60, 16.00, 5.20, :key, 'demo-scenario',
                        5, 0.80, 15.20, :now)"""),
                {"t": TENANT, "o": offer_id, "c": campaign, "cust": cust, "s": store, "i": promoted_item,
                 "key": f"demoscen-redeem-{campaign}-{i:03d}", "now": EVT_AT})
        await db.commit()
        print(f"1-4. campaign {campaign}: 200 treatment / 100 control, "
              f"{len(t_promoted)} redeemed, retention ~70/40")

    # ---- 5. incrementality readout (the real service) ----------------------
    async with async_session() as db:
        await scoped(db)
        r = await readout.compute_and_store(db, tenant_id=TENANT, campaign_id=campaign, computed_by="manual")
        await db.commit()
        print(f"5. incrementality: {r['interpretation']['state']} — "
              f"{r['interpretation']['headline']}  margin/AED={r['margin_per_aed_spent']}")

    # ---- 6. cannibalisation -------------------------------------------------
    async with async_session() as db:
        await scoped(db)
        c = await cannibalization.estimate(db, tenant_id=TENANT, campaign_id=campaign, persist=True)
        await db.commit()
        for res in c["results"]:
            print(f"6. cannibalisation {res['category']}: promoted_lift={res['promoted_lift_units']} "
                  f"cat_net={res['category_net_lift_units']} cannibalized={res['cannibalized_units']} "
                  f"rate={res['cannibalization_rate']}")

    # ---- 7. coalition -------------------------------------------------------
    async with async_session() as db:
        await scoped(db)
        partner_ids = []
        for name, ptype in [("ADNOC Rewards", "fuel"), ("Emirates Skywards", "travel"),
                            ("Address Hotels", "hospitality"), ("Carrefour SHARE", "grocery")]:
            pid = int((await db.execute(text("""INSERT INTO flywheel_coalition_partners
                (tenant_id, partner_name, partner_type, external_ref, status)
                VALUES (:t, :n, :ty, 'DEMOSCEN', 'active') RETURNING id"""),
                {"t": TENANT, "n": name, "ty": ptype})).scalar())
            partner_ids.append(pid)
        for idx, cust in enumerate(treatment[:60]):
            for k in range(2):  # each customer touches 2 partners
                await db.execute(text("""INSERT INTO flywheel_coalition_activity
                    (tenant_id, customer_id, partner_id, activity_type, points, value_aed, occurred_at)
                    VALUES (:t, :c, :p, 'earn', 100, 30, :at)"""),
                    {"t": TENANT, "c": cust, "p": partner_ids[(idx + k) % len(partner_ids)],
                     "at": NOW - timedelta(days=(idx % 20))})
        await db.commit()
        for cust in treatment[:60]:
            await coalition.attribute(db, tenant_id=TENANT, campaign_id=campaign, customer_id=cust,
                                      incremental_margin_aed=Decimal("12.00"), model="time_decay", persist=True)
        await db.commit()
        agg = await coalition.campaign_attribution(db, tenant_id=TENANT, campaign_id=campaign)
        print(f"7. coalition: {len(agg['by_partner'])} partners attributed")

    # ---- 8. trade (supplier scan-down funding + settlement) ----------------
    async with async_session() as db:
        await scoped(db)
        supplier = (await db.execute(text("SELECT id FROM suppliers WHERE tenant_id = :t AND name = :n"),
                                     {"t": TENANT, "n": "Al Rawabi Dairy Co"})).scalar()
        if not supplier:
            supplier = int((await db.execute(text(
                "INSERT INTO suppliers (tenant_id, name, status) VALUES (:t, 'Al Rawabi Dairy Co', 'active') RETURNING id"),
                {"t": TENANT})).scalar())
        await db.execute(text("""INSERT INTO product_suppliers (tenant_id, item_id, supplier_id, unit_cost, moq, lead_time_days)
                                 VALUES (:t, :i, :s, 4.50, 10, 3) ON CONFLICT DO NOTHING"""),
                         {"t": TENANT, "i": promoted_item, "s": supplier})
        await db.commit()
        f = await trade.propose_funding(db, tenant_id=TENANT, supplier_id=supplier, campaign_id=campaign,
                                        funding_type="scan_down", committed_aed=Decimal("5000"),
                                        item_ids=[promoted_item], rebate_per_unit_aed=Decimal("1.50"),
                                        agreement_ref="DEMOSCEN-SCAN")
        await trade.transition_funding(db, tenant_id=TENANT, funding_id=f["funding_id"], target="committed")
        s = await trade.issue_settlement(db, tenant_id=TENANT, funding_id=f["funding_id"],
                                         period_start=date.today() - timedelta(days=1),
                                         period_end=date.today() + timedelta(days=1))
        await db.commit()
        print(f"8. trade: funding {f['funding_id']} committed 5000, settlement {s['settlement_id']} "
              f"amount={s['amount_due_aed']}")

    # ---- 9. shelf-life batches ---------------------------------------------
    async with async_session() as db:
        await scoped(db)
        for i, (item, days, units, cost) in enumerate([
                (promoted_item, 2, 40, "4.50"), (other_item, 1, 25, "9.00"),
                (other_item, 4, 60, "3.20"), (promoted_item, 3, 80, "1.10")]):
            await db.execute(text("""INSERT INTO flywheel_shelf_life
                (tenant_id, store_id, item_id, batch_ref, units, received_on, expires_on, unit_cost_aed, status)
                VALUES (:t, :s, :i, :b, :u, CURRENT_DATE - 8, CURRENT_DATE + CAST(:d AS INTEGER), :cost, 'active')
                ON CONFLICT (tenant_id, store_id, item_id, batch_ref) DO NOTHING"""),
                {"t": TENANT, "s": store, "i": item, "b": f"DEMOSCEN-B{i}", "u": units, "d": days, "cost": cost})
        await db.commit()
        print("9. shelf-life: near-expiry batches")

    # ---- 10. governance: contact fatigue + a suppression -------------------
    async with async_session() as db:
        await scoped(db)
        for cust in treatment[:30]:
            for d in range(3):  # contacted several times this week
                await db.execute(text("""INSERT INTO flywheel_contact_log
                    (tenant_id, customer_id, campaign_id, channel, contacted_at)
                    VALUES (:t, :c, :camp, 'email', :at)"""),
                    {"t": TENANT, "c": cust, "camp": campaign, "at": NOW - timedelta(days=d)})
        other = (await db.execute(text("SELECT id FROM flywheel_campaigns WHERE tenant_id = :t AND id <> :c ORDER BY id LIMIT 1"),
                                  {"t": TENANT, "c": campaign})).scalar()
        for cust in control[:8]:
            await db.execute(text("""INSERT INTO flywheel_offer_suppressions
                (tenant_id, customer_id, suppressed_campaign_id, winning_campaign_id, reason_code, detail)
                VALUES (:t, :c, :sup, :win, 'LOWER_EIV', 'A higher-value offer won this customer')"""),
                {"t": TENANT, "c": cust, "sup": campaign, "win": other or campaign})
        await db.commit()
        print("10. governance: contact fatigue + suppressions")

    # ---- 11. shadow scoring pass -------------------------------------------
    async with async_session() as db:
        await scoped(db)
        sr = await shadow.score_pass(db, tenant_id=TENANT, limit=300)
        await db.commit()
        print(f"11. shadow: scored {sr['scored']}")

    # ---- 12. outcome pricing (gate opens on the significant readout) -------
    async with async_session() as db:
        await scoped(db)
        plan = await outcome_pricing.propose_plan(db, tenant_id=TENANT, plan_name="Demo Performance Plan",
                                                  margin_share_pct=Decimal("0.15"), gate_readouts_required=1)
        await db.commit()
        g = await outcome_pricing.evaluate_gate(db, tenant_id=TENANT, plan_id=plan["plan_id"])
        await db.commit()
        print(f"12. outcome pricing: gate_met={g['gate_met']} ({g['qualifying_readouts']}/{g['required']})")

    print(f"\nDONE. Demo campaign id = {campaign}. Every Flywheel tab now shows real numbers.")


if __name__ == "__main__":
    asyncio.run(main())
