# Operations Copilot — Demo Script (5–8 minutes)

A CTO-ready walkthrough of the three MVP workflows plus a failure/refusal
demonstration. **Repeatable after a database reset** — the seed script puts the
data in a known state every time.

## Setup (once, ~30s)

```bash
# From a running stack (docker compose up -d). Reset-safe: re-run any time.
docker exec sales_backend python -m app.commands.seed_operations_demo
```

This shapes real Meridian-tenant inventory and inserts three findings:
- **Replenishment** — Basmati Rice (5kg) out of stock at Al Barsha, no surplus sibling.
- **Transfer** — Fresh Chicken (1kg) out of stock at Deira, overstocked at Karama.
- **Investigation** — revenue down 22% week-over-week at Mushrif Mall.

Log in as `atharva@retaildemo.app` (super admin) — password `Demo@2026!` — and open
**Operations Copilot** in the nav. Regional-manager approvals can be shown with
`krishna@retaildemo.app`.

> Say up front: *"Everything you'll see is on synthetic demo data, and every
> action the copilot produces is an internal draft — nothing is submitted to a
> supplier. That's a deliberate safety boundary, not a limitation of the demo."*

---

## Act 1 — Replenishment draft (≈90s)

1. In the queue, open the **Basmati Rice out of stock at Al Barsha** finding and
   click **Analyze / Recommend** (or it's already `awaiting_approval` if you
   pre-ran recommend).
2. Walk the recommendation panel:
   - **Measured facts** (cited to evidence) vs an empty/blank hypotheses list —
     "the copilot doesn't guess when it can calculate."
   - **Evidence table**: current stock 0, average daily sales, reorder point —
     each badged *Estimated — no POS/ERP connected*.
   - **Calculated parameters**: the order-up-to steps and the resulting quantity
     (~360 units), with the assumption *"no supplier lead time on record —
     assuming 7 days"* and *"no supplier selected (no supplier data connected)"*.
   - **Measurement plan**: days-of-cover baseline, a 14-day window, success = cover
     back above reorder point.
3. Point at the **"Internal draft — not submitted to any supplier"** banner.
4. Click **Approve** (as regional manager). Show the status move to
   `executed` → run `measuring`, and the audit timeline gain
   `approval.granted` → `action.executed`.

> Key line: *"The quantity came from deterministic code, not the model. The model
> only wrote the sentence — and if it had invented a number, we'd have rejected it."*

## Act 2 — Stock transfer with a live revalidation abort (≈2min)

1. Open **Fresh Chicken out of stock at Deira**. Recommend.
2. The copilot proposes a **stock transfer** from Karama (overstocked) to Deira,
   not a purchase — because a sibling store in the region can safely spare stock.
   Show the calculation: destination need, source spare *after keeping its own
   safety cover*, and the share cap. "It protects the source store first."
3. Show that it requires **regional-manager** approval and names **both** stores —
   "you can only approve a transfer between stores you can already see."
4. **The revalidation demo.** Before approving, change the world:
   ```bash
   docker exec sales_db psql -U salesuser -d salesdb \
     -c "UPDATE inventory SET current_stock = 0 WHERE store_id = 3 AND item_id = 3;"
   ```
   Now click **Approve**. The copilot **revalidates against live inventory**, finds
   the donor can no longer spare stock, and returns **superseded** with
   `execution.aborted_revalidation` in the audit — no transfer is executed.

> Key line: *"Approval isn't a blank cheque. Between approving and executing, it
> re-checks reality. If the numbers moved, it aborts and asks again."*

(Re-run the seed to restore the transfer scenario for a fresh run.)

## Act 3 — Investigation task (≈60s)

1. Open **Revenue down 22% at Mushrif Mall**. Recommend.
2. Here the copilot **separates measured facts from labelled hypotheses** — the
   22% drop is a fact; "a top-selling line went out of stock" is a *hypothesis*
   with a stated way to check it. Expected effect is honestly **"unknown"** —
   "an investigation finds the cause; it isn't itself the fix."
3. It proposes a **bounded checklist** and requires **store-manager** approval.
   Approve it; show the assigned task and the measurement plan (the same revenue
   metric, re-checked over the window).

## Act 4 — The failure / refusal demonstration (≈60s)

Two quick proofs the system is safe under stress:

1. **LLM unavailable.** Stop the model and re-recommend:
   ```bash
   docker compose stop ollama
   ```
   The recommendation still appears — fully formed from deterministic code — with
   the banner *"AI narrative unavailable — deterministic recommendation."* Nothing
   breaks. (`docker compose start ollama` after.)
2. **Stale decision / double action.** With a proposal open in two tabs, approve
   in one, then approve in the other — the second gets *"changed since you loaded
   it — refresh"* (optimistic concurrency), and a repeated approve is an idempotent
   no-op. "You can't accidentally approve or execute twice."

> Optional: show a **refusal** — re-run recommend on a finding whose item is now
> well-stocked; the copilot **refuses** ("stock already meets the order-up-to
> level") rather than drafting a pointless order.

---

## Expected screens & outcomes (cheat sheet)

| Step | Screen | Outcome |
|---|---|---|
| Recommend (replenish) | Recommendation panel | `awaiting_approval`, replenishment_draft ~360 units, supplier = none |
| Approve (replenish) | Queue + timeline | `executed` → `measuring`; audit shows granted + executed |
| Recommend (transfer) | Recommendation panel | stock_transfer_draft, both stores named, source protected |
| Approve after stock change | Timeline | `superseded`, `execution.aborted_revalidation` — nothing executed |
| Recommend (revenue) | Recommendation panel | investigation_task, facts vs hypotheses, effect "unknown" |
| Ollama stopped | Recommendation panel | deterministic recommendation, "AI narrative unavailable" |
| Double approve | Toast | 409 "changed since you loaded it"; idempotent replay |

## Closing line

*"Detect, diagnose, recommend, get a human to approve, execute a draft, and
measure whether it worked — every number auditable, nothing autonomous, and it
degrades safely when the AI is down. That's the shape of an operations agent a
supermarket group can actually trust to pilot."*
