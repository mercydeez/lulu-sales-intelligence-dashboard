# Operations Copilot — Pilot Integration Checklist

What a customer must provide, and what we must build, to move the copilot from
**draft-only on synthetic data** to **acting on a customer's real operations**.

**Pilot-readiness, stated honestly.** Today the copilot is a complete, auditable
*decision* engine on demo data: it detects, gathers evidence, calculates,
recommends, takes human approval, executes an **internal draft**, and measures the
finding's recovery. It does **not** submit purchase orders, commit warehouse
transfers, send supplier emails, or read a live POS/ERP. Every item below that is
unchecked is deliberately draft-only until a real connector is implemented **and**
contracted — flipping a config flag cannot enable a connector that does not exist
in code (`AVAILABLE_CONNECTORS` is the gate).

Use this as the pilot scoping conversation.

---

## 1. Point-of-sale (POS) integration
- [ ] Which POS system(s), and how many lanes/stores?
- [ ] How do we receive transactions — streaming, batch export, API pull?
- [ ] Latency: how fresh is "current" sales data (real-time, hourly, end-of-day)?
- [ ] Do transactions carry store id, item id (SKU), quantity, unit price, timestamp?
- [ ] Are **returns** distinguishable, and do they carry a **reason code**? (Today
      returns are inferred from negative units with no reason — this blocks
      return-cause investigations.)
- [ ] Currency and tax handling; multi-currency stores?

## 2. ERP / inventory source of truth
- [ ] Which ERP/inventory system holds authoritative **on-hand stock**?
- [ ] Per store-item stock levels available via API, with an **observation
      timestamp**? (Critical: our freshness gate currently protects the *finding*,
      not the stock number, because the demo inventory has no timestamp.)
- [ ] Reorder points, safety stock, max levels — system-of-record or do we compute?
- [ ] Reserved vs available stock, in-transit/on-order quantities?
- [ ] Lead times per item/supplier (drives replenishment sizing)?
- [ ] Case/pallet sizes (order rounding)?

## 3. Supplier & procurement workflow
- [ ] Which procurement system issues purchase orders?
- [ ] Supplier master data: preferred supplier per item, MOQ, unit cost, lead time?
- [ ] Approval thresholds and who signs off at each level (feeds the policy engine)?
- [ ] Does a draft PO get created in **your** system for a human to submit, or does
      the copilot submit directly? (MVP = draft only; direct submit is a later,
      contracted connector.)
- [ ] PO acknowledgement/confirmation events back to us (to close "completed")?

## 4. Stock transfer / warehouse workflow
- [ ] How are inter-store transfers requested and fulfilled today?
- [ ] Is there a WMS/TMS, or is it a manual request-and-pick process?
- [ ] What counts as "executed" — a transfer request, a pick, a receipt at
      destination? (MVP creates an internal transfer *task* only.)

## 5. Approval hierarchy & policy
- [ ] Role-to-action approval matrix (who approves replenishment, transfers,
      investigations, high-impact drafts)?
- [ ] Any monetary or quantity thresholds (kept as **configuration**, never
      hard-coded)?
- [ ] Region → store structure, and who has authority over which stores?
- [ ] Delegation / out-of-office approval rules?
- [ ] Required proposal lifetime and evidence-freshness windows for your business?

## 6. Identity & SSO
- [ ] SSO provider (SAML/OIDC)? SCIM for provisioning? (Both already exist in the
      platform — confirm the customer's IdP.)
- [ ] How do roles and store/region scope map from your directory to our RBAC?
- [ ] MFA requirements for approvers?

## 7. Data residency & privacy
- [ ] Required data residency region(s)?
- [ ] Any PII in the operational data path? (The copilot handles no employee or
      customer PII by design; confirm nothing leaks in via finding text.)
- [ ] Constraints on sending any data to an external LLM? (Default is local-first
      Ollama; the external provider is off unless explicitly enabled, and no PII
      is placed in prompts.)
- [ ] Encryption-at-rest / in-transit requirements beyond the platform defaults?

## 8. SLA, recovery & operations
- [ ] Uptime/latency expectations for recommend and approve?
- [ ] RPO/RTO for the operational data and the audit log?
- [ ] Backup/restore and audit-retention requirements (see the platform's
      backup runbooks; the operations audit log is append-only and immutable)?
- [ ] Alerting/on-call expectations for the diagnostics worker and the copilot?

## 9. Audit & retention
- [ ] How long must approval/execution audit records be retained?
- [ ] Any regulatory audit-export format required?
- [ ] Who may read the audit trail; any segregation-of-duties constraints?
- [ ] Immutability/e-discovery requirements? (Audit is DB-append-only today.)

## 10. Store & SKU master data
- [ ] Store master: id, name, region, and the region→store hierarchy?
- [ ] SKU master: item id, name, category, unit price, cost/margin, case size?
- [ ] Category taxonomy (currently a free-text field; a real taxonomy improves
      category-level findings)?
- [ ] Change frequency of master data and how we receive updates?

---

## Connector build order (our side, once the above is answered)

1. **Inventory source of truth** with observation timestamps — unlocks accurate,
   freshness-gated replenishment/transfer on real stock.
2. **Procurement/PO connector** — turns a replenishment draft into a real (still
   human-submitted) purchase order in the customer's system.
3. **Stock-transfer/WMS connector** — turns a transfer draft into a real request.
4. **Returns with reason codes** — unlocks genuine return-cause investigations.
5. **Notification connector** — supplier/stakeholder alerts (explicitly out of the
   MVP; off until contracted).

Each connector implements the same interface and stays **disabled** until it is
both implemented and the customer has signed off — the copilot will keep producing
labelled internal drafts until then, never a silent "successful integration".
