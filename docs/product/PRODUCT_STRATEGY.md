# Product Strategy — From Class Project to Retail Operations MVP

> Positioning: **a real-time store operations intelligence platform for hypermarket chains**, demonstrated with a fictional Lulu-style UAE deployment using synthetic data.
> Constraint: built by students, free/local-first, must remain explainable end-to-end in an interview.

---

## 1. The honest one-liner

> "Hypermarket chains lose margin in the gaps between what headquarters knows and what's happening on the floor *right now*. This platform closes that gap: live sales telemetry, inventory risk alerts, and demand forecasts — scoped per role, per store, per region."

This matters because the project's strongest existing assets (Redis→SSE live pipeline, RBAC model, synthetic event generator) all serve *that* story. We sharpen, not pivot.

---

## 2. Real hypermarket business problems — and our stance on each

| Business problem | Real-world pain | Fits a student MVP? | Our plan |
|---|---|---|---|
| **Stockouts & overstocking** | Lost sales / tied-up capital; buyers react days late | ✅ core | Inventory positions per store + velocity-based days-of-cover + reorder alerts (tables already exist in migration 002) |
| **Expiring inventory & food waste** | Fresh/dairy shrink is a top-3 cost in GCC grocery; ESG angle | ✅ **differentiator** | Add `expiry_date` batches to inventory; "expiry risk" queue with markdown suggestions — cheap to build, very demo-able |
| **Demand forecasting** | Manual ordering, Ramadan/holiday spikes missed | ✅ core | Upgrade predictor to seasonal model on the 5-year Kaggle history; show forecast vs. actual overlay |
| **Multi-branch inventory visibility** | Region managers can't compare branches without spreadsheets | ✅ core | Already half-built: region→store RBAC + store comparison charts; add transfer-suggestion view |
| **Inefficient promotions** | Promos run blind; cannibalization unmeasured | ✅ core | Promotions module exists; add baseline-vs-promo uplift chart from generator's `promotional_sale` events |
| **Store manager dashboards** | Managers get day-old PDFs | ✅ core | Role-scoped landing page (Yash sees only Al Barsha) — the RBAC demo moment |
| **Staff task management** | Shelf-gap fixes, expiry pulls not tracked | ⚠ light version | Convert alerts into assignable "tasks" with done/ack states; skip full workforce mgmt |
| **Customer loyalty & personalization** | CRM-scale; needs real customer data | ❌ out of MVP | Future enterprise (would require PII handling we deliberately avoid) |
| **Long checkout queues** | Needs camera/IoT or POS integration | ❌ out | Mention in pitch as roadmap (queue-length estimate from transaction velocity is a future hack) |
| **Poor product discovery / e-commerce** | Different product entirely | ❌ out | Stay ops-side; avoids competing with Lulu's actual app |
| **Supplier / order management** | EDI integrations, approvals | ⚠ thin slice | Auto-generated "suggested purchase orders" from reorder alerts (a screen, not an integration) |
| **Customer support / FAQs** | Call-center tooling | ❌ out | The AI assistant stays an *analyst copilot* for staff, not customer support |
| **Multilingual EN/AR experience** | UAE workforce reality; almost no student project does RTL properly | ✅ **differentiator** | EN/AR toggle with full RTL layout on the dashboard (scoped to key screens) |

---

## 3. Feature tiers

### A. Current features (exist today, keep & harden)
- Live sales feed + KPIs via Redis pub/sub → SSE
- JWT auth, roles (super_admin / regional_manager / store_manager / analyst), region→store permissions, audit log, lockout
- Analytics: trends, category breakdown, store comparison, returns tracking
- Inventory & alert modules (migrations 002), promotions module (003), employee performance (004)
- AI assistant with data-driven fallback; PDF report export; system monitoring page
- Synthetic data generator (sentiment, seasonality, returns) — *this is the demo engine; treat it as a feature*

### B. Must-have MVP features (gaps that make the current set credible)
1. **Server-side RBAC enforcement on all data APIs** — the product's central claim (GAP C3).
2. **Revenue model**: item prices → real AED figures; units and revenue shown distinctly (GAP C5).
3. **Continuous timeline**: date-shifted history so KPIs/forecasts/charts share one era (GAP H9).
4. **Reliable first-run**: `docker compose up` → working app, seeded users, zero manual psql steps (GAP C1/H5).
5. **Store-manager scoped home page**: log in as Yash → see only Al Barsha, with store-relevant KPIs.
6. **Reorder & expiry alert queue with acknowledge/assign** — turns "alerts" into "operations."

### C. Differentiating features (what makes interviewers lean forward)
1. **Expiry-risk & waste dashboard** — batch-level expiry tracking, projected waste AED, markdown suggestions. Retail-specific, ESG-flavored, nobody else's class project has it.
2. **Forecast vs. actual overlay with honest error metrics (MAPE)** — shows engineering maturity instead of black-box "AI."
3. **English/Arabic with true RTL** — instantly signals "built for this market."
4. **Local-first AI copilot via Ollama** (free) answering questions like "which Dubai store had the most returns this week?" with the rule-based engine as fallback — "works offline, no API bill" is a great pitch line.
5. **Promotion uplift simulator** — pick item + discount %, see projected uplift from historical elasticity (simple math, big wow).

### D. Future enterprise features (pitch deck roadmap, not built)
- POS/ERP integration (real CDC streams replacing the generator — the architecture already mirrors this shape)
- Loyalty & personalization (requires customer PII governance)
- Computer-vision queue & shelf-gap detection
- Supplier EDI + automated replenishment approval chains
- Multi-tenant SaaS deployment, SSO/SCIM
- WebSocket upgrade, horizontal SSE fan-out, read replicas

---

## 4. Personas (who logs in during the demo)

| Persona | Demo user | What their screen proves |
|---|---|---|
| Group ops executive | `atharva@lulu.ae` (super_admin) | Cross-region comparison, network-wide KPIs, admin console |
| Regional manager (Dubai) | `krishna@lulu.ae` | Data hard-scoped to 3 Dubai stores; transfer/promo approvals |
| Store manager (Al Barsha) | `yash@lulu.ae` | Single-store ops: live feed, expiry queue, task acknowledgments |

The 3-login walkthrough **is the demo script** — same product, three truthfully different views, enforced by the server.

## 5. Branding & legal posture

- Keep "Lulu-style UAE hypermarket" as the *scenario*, with a visible disclaimer ("independent student project; synthetic data; not affiliated with Lulu Group"). No logos or trade dress.
- Recommend a neutral product name (e.g., **"Souq Ops"**, **"AisleIQ"**, working title open) with "demo scenario: UAE hypermarket chain" — safer for a public resume/pitch and trivially re-skinnable for any retailer. **Decision needed from owner.**

## 6. Success criteria for the MVP

1. Clone → `docker compose up` → demo-ready in under 5 minutes, zero manual steps.
2. Three-persona walkthrough works with server-enforced scoping (verifiable via curl).
3. Every number on screen is explainable: units vs AED, forecast method, alert thresholds.
4. Zero paid API keys required for the full feature set.
5. UI quality such that a screenshot stands on its own in a portfolio.
