"""Flywheel — closed-loop retention & commercial orchestration.

The module is deliberately a package of EXPLICIT TYPED SERVICES rather than an
agent framework. The governing rule, restated here because every file in this
package depends on it:

    Models propose. Only deterministic, policy-checked services touch money or
    stock, inside row-locked database transactions.

Layout mirrors the six stages of the loop:

    types           — enums, money helpers, the shared dataclasses
    seeder          — stage 1, fixed-seed synthetic customer/event layer
    features        — stage 1→2, point-in-time feature snapshots (no leakage)
    churn           — stage 2, calibrated risk score (+ rule-based fallback)
    uplift          — stage 2, "would an offer actually change this?"
    optimizer       — stage 3, deterministic EIV next-best-action
    inventory_atp   — stage 4, available-to-promise + the shortage ladder
    procurement     — stage 4, aggregated requisitions (never one PO per customer)
    budget          — stage 4, the Decimal ledger; Postgres is the money truth
    approvals       — stage 4, configurable stacked/parallel approval chains
    campaign_state  — stage 5, the persisted, service-validated state machine
    decisioning     — stage 5, real-time evaluate + idempotent redemption
    outbox          — stage 5, transactional outbox → Redis/SSE relay
    guardrails      — stage 5, auto-pause on budget/stock/margin breach
    measurement     — stage 6, treatment vs control; feeds back into stage 1
"""
