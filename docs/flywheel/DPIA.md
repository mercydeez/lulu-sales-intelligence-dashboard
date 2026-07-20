# Data Protection Impact Assessment — Flywheel automated profiling

**Regulation:** UAE Personal Data Protection Law (Federal Decree-Law No. 45 of 2021, "PDPL")
**System:** Flywheel retention & commercial orchestration
**Status:** Draft for review. Not legal advice — to be reviewed by qualified counsel before a production deployment processes real personal data.
**Last updated:** 21 July 2026

---

## 1. Why a DPIA is required

The PDPL requires a DPIA where processing is likely to result in a high risk to
data subjects — expressly including **automated decision-making and profiling**.
The Flywheel scores individuals' churn risk and decides, automatically, what
commercial offer (if any) each person receives. That is profiling with a
commercial effect on the individual, so a DPIA is mandatory, not optional, and
must be **audit-ready** before real personal data is processed.

This document records the processing, the risks, and the mitigations that are
**already implemented in code**, so the assessment reflects the system as built
rather than as hoped.

## 2. The processing, described honestly

| Question | Answer |
|---|---|
| What personal data? | Behavioural only: purchase recency/frequency/monetary value, basket composition, promo response. **No special-category data** — no gender, ethnicity, religion, nationality, or health is stored or used (`flywheel_customers` has none by design; migration 075). |
| Whose data? | Enrolled loyalty customers of the tenant retailer. |
| What decision? | Whether to make a retention offer, and which one — computed by the deterministic EIV optimizer from model-produced scores. |
| Is it solely automated? | The decision is automated; **money and stock only move through deterministic, policy-checked services** (`optimizer.py` contains no model), and a human approval chain gates campaign activation. |
| Legal basis | The retailer's legitimate commercial interest in customer retention, balanced against the data subject's rights below. |

## 3. Identified risks and the mitigations in code

1. **Risk: a person is profiled who does not want to be.**
   *Mitigation — implemented.* PDPL grants the right to object to automated
   processing. `flywheel_profiling_objections` records an objection;
   `decisioning.evaluate` checks it **before any scoring** and returns
   `PROFILING_OBJECTION` — no score, no offer. Verified live: an objecting
   customer is excluded. (`services/flywheel/objections.py`.)

2. **Risk: a person cannot have their data erased.**
   *Mitigation — implemented.* Right to erasure. `services/flywheel/erasure.py`
   is the sole audited path through the append-only guard; it deletes the
   customer and their linked personal data while retaining only aggregate,
   non-identifying measurement rows. (Migration 077 guard + erasure service.)

3. **Risk: two people are wrongly merged during ingestion, corrupting one
   person's record with another's data.**
   *Mitigation — implemented.* Identity resolution links deterministically where
   a loyalty id is present, probabilistically only above a high threshold, and
   **leaves a record unlinked rather than guessing** when the match is ambiguous.
   (`services/flywheel/identity.py`.)

4. **Risk: a person cannot get an explanation of an automated decision about
   them.**
   *Mitigation — implemented.* Every decision carries a `trace_id`;
   `trace.decision_timeline` reconstructs the inputs, the action, the reasons and
   the outcome as the explanation. (`services/flywheel/trace.py`.)

5. **Risk: data leaks across tenants (or, for trade promotion, across
   suppliers).**
   *Mitigation — implemented.* Postgres FORCE RLS on every table, mandatory in
   production (ruling #2); supplier-facing views are additionally scoped to the
   supplier's funded SKUs (`trade.supplier_scope`). Both proven at the database.

6. **Risk: a person is contacted too often.**
   *Mitigation — implemented.* Global contact governance caps contact per
   customer across all campaigns and channels, with consent re-checked at issue
   time. (`services/flywheel/contact_governance.py`; visible on the Governance
   surface.)

## 4. Cross-border transfer position

Personal data is processed within the deployment's own database. Cross-border
transfer of personal data is subject to PDPL restrictions; the data-residency
controls (migration set E5-3, `test_data_residency.py`) keep processing in-region
and a transfer must not be enabled without a lawful basis under the PDPL. **This
is a position statement, not a completed control — confirm the deployment region
and any onward transfer with counsel.**

## 5. Breach procedure

A personal-data breach must be notified in line with the PDPL timeline
(**within 72 hours** of becoming aware, to the regulator, and to affected data
subjects where the risk is high). The operational runbook for detection,
containment and notification is the platform incident runbook; this DPIA records
only that the obligation exists and is owned.

## 6. What is NOT yet done (stated plainly)

- **This DPIA has not been reviewed by counsel.** It reflects the system as built;
  it is not a legal sign-off.
- **No real personal data has been processed.** All data to date is synthetic.
  The controls above are implemented and tested against synthetic data; they must
  be re-validated against real data before a pilot.
- **SOC 2 Type II** is a separate assurance process on a separate (calendar)
  track; it is not part of this DPIA.

## 7. Conclusion

The high-risk profiling this system performs is accompanied by implemented,
tested controls for objection, erasure, explanation, isolation, safe identity
resolution and contact governance. Residual actions before a real-data pilot:
counsel review of this DPIA, confirmation of the cross-border position, and
re-validation of every control against real data.
