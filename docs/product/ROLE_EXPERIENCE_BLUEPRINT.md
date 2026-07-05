# Role Experience Blueprint — the AI-first UX architecture

**Status:** design blueprint (no code). The UX north star for the next version of the platform.
**Authors' hat:** CPO + CXO + retail operations consultant.
**Grounding rule:** every experience below is a *configuration* of engines that already exist in this
codebase (findings, decisions/triage, briefing, forecasts, ROI, UAE calendar, action drafts,
measure loop, procurement approvals, audit, billing). Where an experience needs data we don't have,
it is flagged honestly — never silently assumed.

**Data-readiness flags used throughout:**
- ✅ derivable from today's data (units, derived AED, findings, forecasts)
- 🔶 unlocks when the tenant imports **cost** data (margin, GMROI, shrink value)
- 🔷 needs a **new data source** (POS transactions/baskets, footfall, attendance, complaints)

---

## Deliverable map

| # | Deliverable | Section |
|---|---|---|
| 1 | Role hierarchy diagram | Part 1.3 |
| 2 | Organization chart | Part 1.4 |
| 3 | Responsibility (RACI) matrix | Part 1.6 |
| 4 | Homepage wireframe per role | Part 2 (each playbook) |
| 5 | User journey per role | Part 2 ("A day") |
| 6 | Navigation per role | Part 2 + Part 1.2 |
| 7 | AI behavior per role | Part 2 ("Sage persona") + Part 1.5 |
| 8 | Decision ownership matrix | Part 1.7 |
| 9 | Notification strategy | Part 3.1 |
| 10 | Mobile strategy | Part 3.2 |
| 11 | Collaboration workflows | Part 3.3 |
| 12 | Complete UX architecture | Part 1.1 |
| 13 | Feature access matrix (RBAC) | Part 3.4 |
| 14 | Product recommendations | Part 3.5 |

---

# PART 1 — THE EXPERIENCE ARCHITECTURE

## 1.1 One engine, twenty experiences

The platform is **not** twenty products. It is **five zone types**, powered by **seven engines**,
instantiated per role by a **role config**. This is what makes an 18-role experience buildable by a
tiny team — and what SAP/Oracle never did: they shipped modules; we ship *jobs*.

### The Five Questions (the homepage grammar)

Every homepage, for every role, answers the same five questions in the same order — only the
*scope, vocabulary and verbs* change:

| # | Question | Zone type | Powered by |
|---|---|---|---|
| Q1 | **What matters to me now?** | Verdict hero (Sage speaks, role-scoped) | briefing engine |
| Q2 | **What should I do first?** | My Work queue (top-3 triaged) | decisions/triage engine |
| Q3 | **What needs my approval?** | Approvals strip | decisions + procurement `approval_rules` |
| Q4 | **What can AI do for me?** | Sage skills panel + automation status | action drafts + autonomy config |
| Q5 | **What if I ignore today?** | Cost-of-waiting (role-scoped AED/units) | ROI engine + impact derivations |

### The Seven Engines (all exist today)

```
┌────────────────────────── EXPERIENCE LAYER (per-role configs) ──────────────────────────┐
│  Today (brief)  ·  My Work  ·  Approvals  ·  My Team  ·  Business  ·  Ask Sage          │
└──────┬──────────────┬──────────────┬─────────────┬──────────────┬────────────┬──────────┘
       │              │              │             │              │            │
┌──────▼──────┐┌──────▼──────┐┌──────▼──────┐┌─────▼───────┐┌─────▼─────┐┌─────▼─────┐┌───────────┐
│ 1 BRIEFING  ││ 2 FINDINGS  ││ 3 DECISIONS ││ 4 FORECAST  ││ 5 ROI/AED ││ 6 DRAFTS  ││ 7 MEASURE │
│ verdict,    ││ worker      ││ triage,     ││ projection, ││ dead stock││ emails,   ││ outcome   │
│ narrative   ││ rules,      ││ routing,    ││ reorder,    ││ stockout, ││ POs,      ││ loop,     │
│ composer    ││ evidence    ││ ownership   ││ baseline    ││ leak      ││ proposals ││ auto-     │
│             ││             ││ ladder      ││             ││           ││ (L1)      ││ resolve   │
└─────────────┘└─────────────┘└─────────────┘└─────────────┘└───────────┘└───────────┘└───────────┘
       Shared substrate: sales_fact_view · inventory · RBAC scope · UAE calendar · audit log
```

**The role config** (one JSON-ish record per role, server-driven) selects: scope filter (RBAC),
zone order + density, Sage persona pack, KPI set, decision-ownership row, notification tier map,
default device layout, nav manifest. **Adding a role = adding a config, not building screens.**

## 1.2 Navigation philosophy — organized around jobs

The universal skeleton (max 6 primary items; everything else lives *inside* a job):

```
Today        — the brief + five questions (home, always)
My Work      — my queue: decisions, tasks, drafts awaiting me, follow-ups
My Team      — people who report to me: their queues, delegation, coverage      (managers only)
Business     — role-scoped exploration: numbers, drill-downs, Forecast Lab      (read/analyze)
Ask Sage     — the specialist conversation (persona-tuned)                      (everywhere, ⌘K)
Settings     — me, notifications, (admins: company/billing/users)
```

Role-specific **job hubs** replace generic modules — at most two per role
(e.g. *Buying* for Procurement, *Campaigns* for Marketing, *Evidence* for Auditor). The current
20-item engineering sidebar (Dashboard/Analytics/Insights/Forecast Lab/…) becomes the **admin/
analyst "expert mode"**, hidden from operational roles.

## 1.3 Role hierarchy diagram

```
                                   ┌────────────┐
                                   │ CEO / Owner│
                                   └─────┬──────┘
        ┌───────────────┬────────────────┼──────────────────┬───────────────┐
   ┌────▼───┐      ┌────▼───┐       ┌────▼───┐         ┌────▼───┐      ┌────▼────┐
   │  COO   │      │  CFO   │       │  CIO   │         │  CMO*  │      │  CHRO*  │
   └────┬───┘      └────┬───┘       └────┬───┘         └────┬───┘      └────┬────┘
        │               │                │                  │               │
   ┌────▼─────┐    ┌────▼──────┐   ┌─────▼─────┐      ┌─────▼─────┐   ┌─────▼────┐
   │  VP Ops  │    │ Finance   │   │  System   │      │ Marketing │   │    HR    │
   └────┬─────┘    │ Team (AP/ │   │  Admin    │      │  Manager  │   │  Manager │
        │          │ AR)       │   └───────────┘      └───────────┘   └──────────┘
        │          └───────────┘        │ (dotted)
        │                          ┌────▼──────┐
        │                          │  Auditor  │  (independent; dotted line to CEO/CFO)
        │                          └───────────┘
  ┌─────┴──────────┬──────────────────┬───────────────────┬────────────────────┐
┌─▼──────────┐ ┌───▼─────────┐  ┌─────▼────────┐  ┌───────▼────────┐  ┌────────▼───────┐
│ Regional   │ │ Category    │  │ Procurement  │  │ Inventory      │  │ Customer Svc   │
│ Manager ×N │ │ Manager ×N  │  │ Manager      │  │ Manager        │  │ Manager        │
└─┬──────────┘ └─────────────┘  └──────┬───────┘  └───────┬────────┘  └────────────────┘
  │                                    │                  │
┌─▼──────────┐                  ┌──────▼───────┐   ┌──────▼────────┐   ┌────────────────┐
│ Store      │──── staff ─────► │ Supplier     │   │ Warehouse     │   │ Loss Prevention│
│ Manager ×N │  Sales Executive │ (external)*  │   │ Manager       │   │ Manager*       │
└────────────┘                  └──────────────┘   └───────────────┘   └────────────────┘
* = proposed additions beyond the requested list
```

## 1.4 Organization chart → platform mapping (existing RBAC → target)

The current enum (`super_admin`, `admin`, `regional_manager`, `store_manager`, + permission bundles
like `can_manage_inventory`, `can_export`, `is_admin`) already carries the *scoping machinery*
(tenant + region→store expansion). Target roles are **permission bundles + a persona pack** on top
of that machinery — not a new auth system.

| Target role | Exists today as | Scope | Status |
|---|---|---|---|
| CEO/Owner | `super_admin` (tenant) | all stores | rename/persona only |
| COO | `admin` | all stores | persona pack |
| CFO | `admin` + `can_export` | all stores, finance surfaces | proposed bundle |
| CIO | `super_admin` (platform surfaces) | admin/security/audit | proposed split from super_admin |
| VP Operations | `admin` | all stores | proposed bundle |
| Regional Manager | `regional_manager` ✅ | region→stores | exists |
| Store Manager | `store_manager` ✅ | one store | exists |
| Category Manager | new | all stores, category slice | **new scope axis: category** |
| Procurement Manager | `can_manage_inventory` operator | all stores | persona pack |
| Inventory Manager | `can_manage_inventory` operator | all stores | persona pack |
| Marketing Manager | `can_manage_promotions` | all stores | persona pack |
| Sales Executive | employee record (exists) | one store, read + tasks | proposed light role |
| Finance Team | new (billing read/write) | invoices/VAT | proposed bundle |
| HR Manager | new (employees module) | employees | proposed bundle |
| Customer Service Mgr | new | returns slice | proposed bundle |
| Warehouse Manager | new | transfers/PO receiving | proposed bundle |
| Auditor | new **read-only** | audit log + evidence | proposed bundle (PDPL seller) |
| System Administrator | `super_admin` (ops surfaces) | tenant console, keys, usage | exists (split) |
| Loss Prevention* | new | 🔷 needs POS grain | roadmap role |
| Supplier portal* | API-key tenant-external | own POs/invoices | roadmap (public API exists) |

**Design decision:** one new *scope axis* is required — **category** (Category Manager). Store and
region scoping exist; category scoping is a WHERE clause on the same fact view + findings filter.

## 1.5 The Sage persona system — one AI, twenty specialists

Sage must never feel like ChatGPT-with-your-data. Persona = **five tunable dials**, defined per
role in the persona pack (a system-prompt fragment + UI copy set + scope filter):

1. **Scope** — what Sage can see (inherits RBAC; the store manager's Sage genuinely cannot discuss other stores — enforced today by the NL→SQL guard).
2. **Vocabulary** — AED-led (execs/finance) vs units-led (stores/warehouse) vs evidence-led (auditor).
3. **Verbs** — *recommend/decide* (execs) vs *do/confirm* (operators) vs *show/prove* (governance).
4. **Cadence** — when it speaks first (07:00 brief, shift-start, month-end, real-time).
5. **Autonomy** — what it may draft vs do alone (from the decision ladder, 1.7).

**Persona integrity rules (all roles):** Sage always shows its evidence; never fabricates AED
(units≠AED discipline); always names the owner when something isn't yours ("that's Amira's call —
want me to send it to her?"); always closes the loop ("you approved this Tuesday — it worked").

## 1.6 Responsibility matrix (RACI) — the ten core retail processes

R = Responsible, A = Accountable, C = Consulted, I = Informed, 🤖 = Sage automates/prepares

| Process | Sage | Store | Regional | Category | Procure | Inventory | Wrhs | Mktg | CFO | COO | CEO |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Replenish (small PO) | 🤖R | A | I | — | I | C | I | — | — | — | — |
| Replenish (large PO) | 🤖 | C | I | C | **R** | C | I | — | I(>100k) | **A** | — |
| Branch transfer | 🤖R | C | **A** | — | — | C | R(execute) | — | — | I | — |
| Price change | 🤖C | I | I | **R** | C | — | — | C | **A**(>5%) | I | I |
| Promotion launch | 🤖C | I | C | R | — | C(stock) | — | **R** | I | **A** | I |
| Markdown / clearance | 🤖R | I | C | R | — | C | — | C | **A** | I | — |
| Supplier review/change | 🤖C | — | — | C | **R** | — | C | — | I | **A** | I(strategic) |
| Store performance rescue | 🤖C | R | **A** | C | — | — | — | C | — | I | I(chronic) |
| Month-end close & VAT | 🤖R | — | — | — | — | — | — | — | **A** | I | I |
| Data import / onboarding | 🤖C | — | — | — | — | R | — | — | — | I | — |

## 1.7 Decision ownership matrix — the AED ladder

The single most important governance artifact. Extends the existing procurement `approval_rules`
into a platform-wide ladder. **Sage's autonomy is a rung on the same ladder, not a special case.**

| Decision type | Sage auto (L2, opt-in) | Sage drafts (L1, today) | Approver | Escalates to | Informed |
|---|---|---|---|---|---|
| PO ≤ AED 2,000 | ✅ place + log | ✅ | — (post-audit) | Procurement (weekly digest) | Store |
| PO 2k–10k | — | ✅ | Store Manager | Regional | Procurement |
| PO 10k–50k | — | ✅ | Procurement Mgr | COO | CFO (digest) |
| PO 50k–250k | — | ✅ | COO | CFO co-sign | CEO (digest) |
| PO > 250k | — | ✅ | CEO + CFO | board/owner | — |
| Transfer (any) | ≤ 200 units auto-suggest→confirm | ✅ | Regional Mgr | COO | Both stores, Warehouse |
| Price change ≤ 5% | — | ✅ | Category Mgr | CFO | Marketing, Stores |
| Price change > 5% | — | ✅ | Category + CFO | CEO | COO |
| Promotion ≤ 25k budget | — | ✅ | Marketing Mgr | COO | Category, Stores |
| Promotion > 25k | — | ✅ | COO | CEO | CFO |
| Markdown batch | expiring ≤ AED 1k auto-flag | ✅ | Category Mgr | CFO (>10k) | Inventory |
| Supplier suspend/switch | — | ✅ email | Procurement | COO | CFO, Category |
| Staffing shift swap | 🔷 | 🔷 | Store Manager | Regional | HR |
| Refund policy exception | — | ✅ | CS Manager | COO | Finance |
| Invoice issue / mark-paid | — | ✅ | Finance Team | CFO | — |
| User invite / role change | — | ✅ | SysAdmin | CIO | Auditor (log) |
| Data deletion request | — | ✅ | CIO/SysAdmin | CEO | Auditor (log) |

**Delegation defaults (automatic, from the triage engine — shipped):** chain-wide → executive;
single-store performance → regional; large replenishment → store; small/recurring → Sage lane.
**Vacation/coverage rule:** every approver has a deputy; unactioned decisions escalate one rung
after a role-specific SLA (exec 24h, ops 8h, store 4h).

---

# PART 2 — ROLE PLAYBOOKS

Template per role: Mission · A day (journey) · Homepage wireframe · Sage persona · Decisions ·
Navigation · Top-10 KPIs (ranked, flagged) · AI features · Notifications · Device.

---

## R1 · CEO / Owner — *"Is the business healthy, and what's my one call today?"*

**Mission.** Confidence and direction in five minutes. Not analysis — judgment. The CEO opens the
app to know the business is under control and to make the one decision only they can make.

**A day.** 07:00 phone: Sage brief with coffee (90 seconds). 07:05: one tap on the single
decision above their threshold, or "all routed" reassurance. Midday: nothing (silence is the
product). 18:00: optional evening pulse if something moved >X%. Sunday: weekly strategy digest —
wins measured, misses explained, next week's seasonal calendar. Reports to: owner/board. Direct
reports: COO, CFO, CIO, CMO, CHRO.

**Homepage — "Today".**
```
┌──────────────────────────────────────────────────────┐
│ 🟢 SAGE VERDICT (hero, typed)                        │
│ "Good morning, Khalid. A strong week — AED 2.31M,   │
│  +6.4%. Everything is routed except one call:        │
│  the Seafood supplier contract (AED 380k/yr)."       │
│ [Decide it now →]        [All else: 14 routed ✓]     │
├──────────────┬──────────────┬────────────────────────┤
│ Revenue WoW  │ At stake     │ Next 14d forecast      │
│ AED + trend  │ AED /wk      │ AED (Ramadan-aware)    │
├──────────────┴──────────────┴────────────────────────┤
│ 🏆 PROVEN THIS WEEK: 3 decisions worked (AED 92k     │
│ recovered — measured, not estimated)                  │
├───────────────────────────────────────────────────────┤
│ 📅 RADAR: DSF in 40 days · new store health: 2 amber │
├───────────────────────────────────────────────────────┤
│ Ask Sage: "Why is Abu Dhabi ahead of Dubai?"          │
└───────────────────────────────────────────────────────┘
```

**Sage persona — "Strategic Advisor".** Calm, board-room brevity, AED-led, zero jargon.
Opens: *"I'm watching the whole business. One thing needs you today."* Watches: chain-wide deltas,
decision-ladder top rung, measured outcomes, seasonal horizon. Never: floods with operational
detail, never shows a chart before a sentence.

**Decisions.** Approves: >AED 250k commitments, strategic supplier/brand changes, price
architecture, expansion. Delegates (auto): everything on lower rungs — visible as "routed ✓".
Sage handles: the entire reading of the business; the weekly board-pack draft.

**Navigation.** Today · Decisions · Business (drill-down) · People (leadership scorecards) ·
Ask Sage. *(No inventory, no imports, no dev tools.)*

**Top-10 KPIs.** 1 Revenue WoW/MoM ✅ · 2 Gross margin 🔶 · 3 AED at stake (leak) ✅ ·
4 Measured savings (outcome loop) ✅ · 5 Forecast next 14/30d ✅ · 6 Store health spread (best–worst) ✅ ·
7 Decision latency (queue age) ✅ · 8 Inventory cash tied 🔶 · 9 Seasonal readiness index ✅ ·
10 Same-store sales growth ✅.

**AI features.** Daily verdict; weekly board-pack (one-pager, printable — reuses report engine);
"explain any number" drill-down narration; scenario questions ("what if Ramadan demand is +30%?" —
forecast engine); competitor/market brief 🔷 (needs external feed).

**Notifications.** T1 morning brief (07:00, push+email). T0 interrupts *only*: >AED 250k decision,
security incident, chain revenue −15% day-over-day. T3 Sunday strategy digest. Everything else: never.

**Device.** Phone-first (brief + one-tap decisions), desktop for monthly depth, voice brief in the
car (roadmap).

---

## R2 · COO — *"Run the heartbeat; catch what's slipping."*

**Mission.** Every exception owned, every owner moving, nothing older than its SLA. The COO's
product is *flow* — decisions in, outcomes out.

**A day.** 06:45: triage brief — 3 calls for them, N routed (the shipped Decision Center *is* their
homepage). 08:30: regional stand-up armed with per-region queues. 11:00: approves two 50k–250k POs.
14:00: reviews a "worsened" outcome — reassigns with a stronger playbook. 17:00: SLA sweep — one
regional manager sitting on 4 decisions; nudges via Sage. Reports to CEO. Reports in: VP Ops,
Regional Managers, Procurement, Inventory, CS, Warehouse.

**Homepage — "Operations Today".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "I read 23 exceptions overnight. 3 need you;   │
│ 20 are routed. Dubai is your slow lane today."       │
├──────────────────────────────────────────────────────┤
│ DECIDE NOW — YOUR 3 CALLS (full decision cards)      │
├──────────────────────────────────────────────────────┤
│ FLOW BOARD (the COO's control tower)                 │
│ Region   Queue  Oldest  SLA   Outcomes(7d)           │
│ Dubai      7    26h    ⚠︎     4✓ 1✗                 │
│ Abu Dhabi  3     6h    ✓      3✓                    │
│ North Em.  5    11h    ✓      2✓ 1…                 │
├──────────────────────────────────────────────────────┤
│ MEASURE LOOP: 12 accepted → 8 worked · 2 pending ·   │
│ 2 worsened [review]                                  │
├──────────────────────────────────────────────────────┤
│ AUTOMATION: Sage placed 9 small POs this week (log)  │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Operations Director".** Direct, SLA-literate, names names. Opens: *"Three need
you. Dubai's queue is aging — want me to nudge Amira?"* Watches: queue age, routing balance,
outcome ratios, automation log. Never: strategic musing; never hides a worsened outcome.

**Decisions.** Approves: 50k–250k POs, >25k promos, supplier suspensions, cross-region reallocations.
Delegates: per the ladder — and *sees the ladder working* (routing stats). Sage handles: routing
itself, SLA nudges, small-PO placement (L2), re-measurement.

**Navigation.** Today · Decisions (full triage) · My Team (regional queues + coverage) ·
Business · Playbooks (SOPs per finding type) · Ask Sage.

**Top-10 KPIs.** 1 Open criticals ✅ · 2 Decision latency by owner ✅ · 3 Outcome success rate ✅ ·
4 Stockout-days (chain) ✅ · 5 Transfer completion time ✅ · 6 Store health by region ✅ ·
7 AED at stake by lane ✅ · 8 Automation share of decisions ✅ · 9 Returns rate trend ✅ ·
10 Labor coverage vs plan 🔷.

**AI features.** Triage (shipped); SLA escalation nudges; playbook suggestions per finding type;
"worsened" root-cause packets; weekly ops review deck; delegation-balance advisor ("Dubai gets 2×
the exceptions of Abu Dhabi — staffing or demand?").

**Notifications.** T1 triage brief 06:45. T0: critical finding unrouted >1h, outcome "worsened",
SLA breach on top rung. T2 in-app queue badges. T3 Friday ops digest.

**Device.** Desktop-primary (flow board), phone for approvals + nudges.

---

## R3 · CFO — *"Where is cash leaking, and can I trust these numbers?"*

**Mission.** Cash discipline and number trust. The CFO adopts the platform the day it produces a
figure they can reconstruct — which is why every metric carries its derivation (shipped: ROI
report methodology column).

**A day.** 08:00: cash brief — inventory cash, dead stock, leak, AR. 10:00: co-signs one 120k PO
(sees Sage's evidence, not a hallway request). Month-end week: close pack — VAT invoices (billing
engine), variance narrative, outcome-pricing statement ("we paid fees on AED 61k of *proven*
savings"). Reports to CEO. Reports in: Finance Team.

**Homepage — "Cash & Control".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "Cash in inventory rose AED 210k this week —   │
│ driven by Beverages overbuying ahead of DSF. Within  │
│ plan. Two co-signs await you."                       │
├────────────┬─────────────┬───────────────────────────┤
│ Cash tied  │ Dead stock  │ Leak (dead+stockout)      │
│ 🔶 at cost │ AED ✅      │ AED/wk ✅                 │
├────────────┴─────────────┴───────────────────────────┤
│ CO-SIGN QUEUE: 2 items (PO 120k · price change 7%)   │
├──────────────────────────────────────────────────────┤
│ AR / INVOICES: 3 overdue (aging 14/22/41d) · VAT ok  │
├──────────────────────────────────────────────────────┤
│ OUTCOME PRICING: savings confirmed AED 61k → fee     │
│ statement ready [review & approve]                   │
├──────────────────────────────────────────────────────┤
│ [Download CFO report — every number's derivation]    │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Financial Analyst".** Precise, conservative, derivation-first. Opens: *"Here's
the cash position; every figure links to its math."* Watches: cash-in-inventory, leak, AR aging,
fee statements, co-sign queue. Never: estimates without a flagged basis; never mixes units and AED.

**Decisions.** Approves: co-signs >100k, price >5%, markdown budgets >10k, fee statements,
write-offs. Delegates: invoice ops → Finance Team. Sage handles: close-pack assembly, variance
narratives, VAT arithmetic, dunning drafts.

**Navigation.** Today · Co-signs · Cash (value/ROI) · Invoices & VAT · Statements (outcome
pricing) · Ask Sage.

**Top-10 KPIs.** 1 Cash tied in inventory 🔶 · 2 Dead stock AED ✅ · 3 Leak AED/wk ✅ ·
4 GMROI 🔶 · 5 AR aging ✅(billing) · 6 Realized savings vs fees ✅ · 7 Markdown spend vs budget 🔶 ·
8 Revenue vs forecast variance ✅ · 9 Days of supply ✅ · 10 Shrink value 🔷.

**AI features.** Month-end close pack; variance narrative ("revenue −3% vs forecast: 60% Seafood,
30% Deira footfall 🔷 proxy, 10% price"); dunning email drafts; what-if on markdown budgets;
board-ready finance one-pager.

**Notifications.** T1 daily cash brief 08:00 (email). T0: co-sign request, AR >30d, fee statement
disputed. T3 month-end pack.

**Device.** Desktop-primary; phone for co-signs only.

---

## R4 · CIO — *"Is the platform safe, compliant, and healthy?"*

**Mission.** Sleep at night: tenant isolation holding, audit trail complete, integrations flowing,
access reviewed. The CIO is also the internal *seller* of the platform's trust story (PDPL).

**A day.** 09:00: platform pulse — uptime, error rate, import health. Weekly: access review (who
gained rights, Sage-drafted diff), security-events scan, DR check (last verified backup). Quarterly:
evidence export for the auditor; data-rights requests review. Reports to CEO. Reports in: SysAdmin.

**Homepage — "Platform Trust".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "All green. 41 imports succeeded, 1 failed at  │
│ Al Nahda (fix suggested). Last verified restore:     │
│ 4 days ago. 2 access changes to review."             │
├───────────┬───────────┬───────────┬──────────────────┤
│ Uptime    │ Error rate│ Backup ✓  │ Isolation checks │
├───────────┴───────────┴───────────┴──────────────────┤
│ ACCESS REVIEW: 2 role changes this week [diff]       │
│ SECURITY EVENTS: 0 critical · 3 info [scan]          │
├──────────────────────────────────────────────────────┤
│ DATA FLOWS: imports 41✓ 1✗ · API usage 62% of plan  │
├──────────────────────────────────────────────────────┤
│ COMPLIANCE: audit export ready · 1 data-rights req   │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Platform Steward".** Sober, checklist-minded, evidence-linked. Opens: *"All
green"* or leads with the exception. Watches: health, auth anomalies, import failures, backup
freshness, access drift. Never: speculates about causes it can't log-trace.

**Decisions.** Approves: role/permission changes, API key issuance, data deletion execution,
integration go-lives. Sage handles: access-diff summaries, security-event triage, evidence packs.

**Navigation.** Today · Access & Security · Data Flows (imports/API/webhooks) · Compliance
(audit/data rights/trust) · Monitoring · Ask Sage.

**Top-10 KPIs.** 1 Uptime ✅ · 2 Failed imports ✅ · 3 Backup verified age ✅ · 4 Security events ✅ ·
5 Access changes/wk ✅ · 6 API usage vs quota ✅ · 7 Webhook failure rate ✅ · 8 Data-rights SLA ✅ ·
9 RLS check status ✅ · 10 Open vulnerabilities 🔷(scanner feed).

**Notifications.** T0: security critical, backup failure, isolation-check failure. T2 badges.
T3 weekly platform digest. **Never** business KPIs — respect the lane.

**Device.** Desktop.

---

## R5 · VP Operations — *"Turn fixes into programs."*

**Mission.** Where the COO runs the heartbeat, the VP Ops runs *programs*: SOP rollouts, seasonal
readiness, chronic-store rescue. Their unit of work is the initiative, not the exception.

**A day.** Reviews program board (each program = a bundle of decisions + a measured KPI). Prepares
DSF readiness: checklist coverage per store, stock depth vs forecast, staffing plan 🔷. Runs the
"chronic laggards" program — three stores in rescue with weekly measured milestones. Reports to
COO. Works across regionals (matrix).

**Homepage — "Programs".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "DSF readiness 71% — Beverages depth is the    │
│ gap (6 stores). Rescue program: Karama +4.2% wk2 ✓." │
├──────────────────────────────────────────────────────┤
│ PROGRAM BOARD                                        │
│ DSF Readiness    ▓▓▓▓▓▓▓░░░ 71%  gap: stock depth   │
│ Store Rescue ×3  wk2: 2 improving · 1 flat           │
│ SOP: Fresh-count ▓▓▓▓▓▓▓▓░░ 82% stores compliant    │
├──────────────────────────────────────────────────────┤
│ BENCHMARKS: store health quartiles · movers ↑↓       │
├──────────────────────────────────────────────────────┤
│ DECISIONS FEEDING PROGRAMS: 5 queued to owners       │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Program Director".** Milestone-driven, comparative. Opens with program deltas.
Watches: readiness %, program KPIs vs baseline (measure loop applied to *initiatives* — the same
engine, new object). Never: single-exception noise.

**Decisions.** Approves: SOP changes, program launches, rescue-plan resourcing. Sage handles:
readiness checklists, benchmark packs, milestone measurement.

**Navigation.** Today · Programs · Benchmarks · My Team · Ask Sage.
**Top-10 KPIs.** 1 Program milestone attainment ✅ · 2 Seasonal readiness % ✅ · 3 Health-score
movers ✅ · 4 SOP compliance 🔷(checklist data) · 5 Rescue-store trajectory ✅ · 6 Transfer cycle
time ✅ · 7 Forecast accuracy by region ✅ · 8 Stockout-days by program scope ✅ · 9 Outcome success
in programs ✅ · 10 Cost per program 🔶.
**Notifications.** T1 program brief Mon/Thu. T0: program KPI breaks floor. T3 monthly program review.
**Device.** Desktop + tablet (store walks).

---

## R6 · Regional Manager — *"Make my stores hit plan."* (exists: `regional_manager`)

**Mission.** 8–30 stores, one number each, no surprises. The regional lives between HQ pressure
and store reality; the platform must make them the *best-informed person in every store visit*.

**A day.** 07:15 tablet: region brief — league table, 2 approvals (transfers), 1 rescue check-in.
09:00–16:00 store visits: **Visit Mode** — auto-packet per store (health, top exceptions, last
visit's promises, talking points). 16:30: approves a transfer, reassigns one task. Reports to
COO/VP Ops. Reports in: Store Managers.

**Homepage — "My Region".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "Dubai region +2.1%. Karama is your visit      │
│ today — its Fresh section drove the dip; packet      │
│ ready. Two transfers await your approval."           │
├──────────────────────────────────────────────────────┤
│ LEAGUE TABLE (my stores)                             │
│ Store        Health  WoW    Exceptions  Tasks        │
│ Deira CC      82 ↑  +3.1%      1          2         │
│ Al Barsha     77 →  +0.4%      2          1         │
│ Karama        61 ↓  −4.9%      4 ⚠︎       3         │
├──────────────────────────────────────────────────────┤
│ APPROVALS: 2 transfers (Sage-suggested, qty shown)   │
├──────────────────────────────────────────────────────┤
│ TODAY'S VISIT: Karama — [open visit packet]          │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Regional Coach".** Comparative, visit-oriented, remembers promises. Opens:
*"Karama needs you today — here's why and here's the packet."* Watches: league table, task
completion, transfer flow, visit follow-ups. Never: chain-wide abstractions.

**Decisions.** Approves: transfers, 2k–10k escalations, store task reassignment, local promo
requests upward. Delegates: shelf-level execution → stores. Sage handles: visit packets, follow-up
tracking, transfer suggestions.

**Navigation.** Today · My Stores (league) · Approvals · Visits · Ask Sage.
**Top-10 KPIs.** 1 Region revenue vs plan ✅ · 2 Store health league ✅ · 3 Stockout-days by store ✅ ·
4 Task completion rate ✅ · 5 Transfer cycle time ✅ · 6 Exceptions per store ✅ · 7 Visit follow-up
closure ✅ · 8 Returns by store ✅ · 9 Labor coverage 🔷 · 10 Region forecast next 7d ✅.
**Notifications.** T1 07:15 region brief. T0: store critical, transfer stuck >24h. T2 badges.
**Device.** **Tablet-first** (visits) + phone.

---

## R7 · Store Manager — *"Open ready, close proud."* (exists: `store_manager`)

**Mission.** Today's shelf, today's team, today's number. Everything else is noise. This is the
highest-frequency user and the persona most underserved by every incumbent platform.

**A day.** 07:40 phone, walking in: *"Your store opens in 20 minutes."* Open-ready checklist (3
items). 08:00–12:00: two tasks from region (photo-confirm), one reorder confirm (Sage pre-filled).
14:00: expiring-stock flag → markdown request one-tap. 21:30: close: today's number vs forecast +
"tomorrow's watch-out". Reports to Regional. Reports in: Sales Executives / floor staff.

**Homepage — "My Store Today" (phone-first).**
```
┌────────────────────────────┐
│ SAGE: "Opens in 20 min.    │
│ 3 things before doors:"    │
│ ① Juice delivery → shelf   │
│ ② Confirm PO ~300 Dates    │
│ ③ Fresh count (2 min)      │
├────────────────────────────┤
│ TODAY: AED 41,2k / plan    │
│ 46,0k · footfall peak 6pm  │
├────────────────────────────┤
│ TASKS FROM AMIRA (2)       │
│ EXPIRING (5 SKUs) [act]    │
├────────────────────────────┤
│ 🎙 "Sage, out of stock on   │
│ Al Rawabi 1L?" (voice)     │
└────────────────────────────┘
```

**Sage persona — "Store Coach".** Energetic, concrete, shelf-level, bilingual (AR/EN parity is
non-negotiable here). Opens with the clock. Watches: today only — deliveries, stock, tasks, the
number. Never: last quarter, other stores, strategy.

**Decisions.** Approves: PO 2k–10k confirms, task completion, markdown *requests*, shift swaps 🔷.
Sage handles: reorder pre-fill, expiry flags, close-of-day summary, photo-task verification 🔷.

**Navigation (4 tabs).** Today · Tasks · My Store (stock/number) · Ask Sage.
**Top-10 KPIs.** 1 Today vs plan ✅ · 2 Open-ready completion ✅ · 3 Stockouts now ✅ · 4 Expiring
units 🔶(dates) · 5 Tasks due ✅ · 6 Returns today ✅ · 7 Top-seller availability ✅ · 8 Staff
coverage 🔷 · 9 Yesterday's close vs forecast ✅ · 10 Week trajectory ✅.
**AI features.** Voice stock queries; reorder pre-fill; markdown one-tap; shift handover note
auto-draft; "why is today slow?" (weather/calendar 🔷/✅ mix).
**Notifications.** T1 open brief 07:40 + close summary 21:30. T0: delivery failure, stockout of a
top-10 seller. Real-time *only* during open hours.
**Device.** **Phone (PWA), voice-capable.** Watch: task pings (roadmap).

---

## R8 · Category Manager — *"My categories win their aisles."* (new scope axis)

**Mission.** Own P&L of 3–8 categories across all stores: assortment, price, promo slate, supplier
quality within the category.

**A day.** Brief: category league (my categories WoW, vs chain). Reviews one slump finding (the
category_slump rule is *their* queue), approves one price change ≤5%, submits one promo proposal
with Sage's uplift forecast attached. Monthly: assortment review — kill list (dead SKUs by AED) +
gap list 🔷(market data). Reports to COO/CMO. Peers: Procurement, Marketing.

**Homepage — "My Categories".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "Beverages −8% WoW — 70% of the dip is 2 SKUs  │
│ out of stock in 4 stores (not demand). Fix is a      │
│ transfer, already queued to Rashid."                 │
├──────────────────────────────────────────────────────┤
│ CATEGORY LEAGUE: mine vs chain, WoW, share           │
├──────────────────────────────────────────────────────┤
│ MY QUEUE: 1 slump finding · 1 price approval ·       │
│ 1 promo proposal draft                               │
├──────────────────────────────────────────────────────┤
│ PROMO RESULTS: Ramadan dates promo +18% uplift vs    │
│ baseline (measured) · cannibalized juices −3%        │
├──────────────────────────────────────────────────────┤
│ DEAD SKUs (mine): 14 · AED 32k [kill-list draft]     │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Merchant Copilot".** Trader's tongue: share, uplift, cannibalization, rate of
sale. Opens with the *cause* behind the category number (decomposition). Never: store-ops noise.

**Decisions.** Approves: price ≤5% (mine), promo proposals (submit), kill list, planogram intents 🔷.
Sage handles: slump decomposition, uplift measurement, kill-list drafting, price-anomaly flags.

**Navigation.** Today · My Categories · Pricing · Promos · Suppliers (category view) · Ask Sage.
**Top-10 KPIs.** 1 Category revenue WoW ✅ · 2 Share of chain ✅ · 3 Promo uplift (measured) ✅ ·
4 Margin by category 🔶 · 5 Rate of sale top/bottom ✅ · 6 Dead SKU AED ✅ · 7 Availability % ✅ ·
8 Return rate (category) ✅ · 9 Price-change outcome ✅ · 10 New-SKU velocity ✅.
**Notifications.** T1 category brief. T0: my category slump critical. T3 weekly trading recap.
**Device.** Desktop + phone recap.

---

## R9 · Procurement Manager — *"Right stock, right terms, right supplier."*

**Mission.** Keep the chain fed at the best terms; catch bad suppliers before stores feel it.

**A day.** 08:30: *"Three suppliers require attention today."* Approves the 10k–50k PO queue
(Sage-drafted with evidence), reviews an OTIF breach 🔷/✅(PO dates exist), sends a Sage-drafted
supplier email (action drafts — shipped). Watches the auto-PO log (small orders Sage placed).
Reports to COO. Peers: Category, Inventory, Warehouse.

**Homepage — "Buying Desk".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "3 suppliers need attention: Al Kabeer 2 late  │
│ POs; GreenFarm return-rate 2.3× mean; one contract   │
│ renews in 21 days. PO queue: 6 (AED 84k)."           │
├──────────────────────────────────────────────────────┤
│ PO APPROVAL QUEUE (evidence-carded, one-tap)         │
├──────────────────────────────────────────────────────┤
│ SUPPLIER WATCHLIST: late / quality / renewal         │
├──────────────────────────────────────────────────────┤
│ AUTO-PO LOG: 9 placed this wk ≤2k · 0 exceptions     │
├──────────────────────────────────────────────────────┤
│ LEAD-TIME BOARD: breaches by supplier [drill]        │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Supply Chain Expert".** Terms-savvy, supplier-memory. Opens with the supplier
watchlist. Watches: PO aging, OTIF, quality (returns by supplier 🔶 mapping), renewals. Never:
approves anything itself above the auto rung.

**Decisions.** Approves: PO 10k–50k, supplier emails, reorder-parameter changes. Escalates:
supplier switch → COO. Sage handles: PO drafting (all), small-PO placement (L2), renewal reminders,
negotiation briefs (price history 🔶).

**Navigation.** Today · PO Queue · Suppliers · Auto-PO Log · Terms & Renewals · Ask Sage.
**Top-10 KPIs.** 1 PO queue value/age ✅ · 2 OTIF by supplier ✅(PO dates) · 3 Stockout-days caused ✅ ·
4 Auto-PO share ✅ · 5 Return rate by supplier 🔶(mapping) · 6 Lead-time variance ✅ · 7 Cost trend 🔶 ·
8 Renewals due ✅ · 9 Emergency-order rate ✅ · 10 Fill rate 🔷(ASN data).
**Notifications.** T1 buying brief 08:30. T0: supplier failure blocking top sellers. T2 queue badges.
**Device.** Desktop + phone approvals.

---

## R10 · Inventory Manager — *"Nothing rots, nothing runs out."*

**Mission.** The stock ledger's conscience: days-of-supply balance, dead stock burn-down,
transfer flow, data quality of the inventory itself.

**A day.** DOS distribution scan (too-high tail = cash; too-low = risk). Runs the weekly dead-stock
burn-down (markdown proposals → Category). Confirms 4 transfer suggestions (UAE-intelligence engine
— shipped). Audits one import's data-quality report. Reports to COO. Peers: Procurement, Warehouse.

**Homepage — "Stock Health".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "Dead stock down AED 9k this week (burn-down   │
│ on track). 4 transfers suggested — Deira ↔ Nahda.   │
│ DOS tail: 12 SKUs >90 days."                         │
├──────────────────────────────────────────────────────┤
│ DOS DISTRIBUTION (histogram + tails)                 │
├──────────────────────────────────────────────────────┤
│ DEAD-STOCK BURN-DOWN: AED 118k → target 60k [trend]  │
├──────────────────────────────────────────────────────┤
│ TRANSFERS: 4 suggested [confirm] · 2 in transit      │
├──────────────────────────────────────────────────────┤
│ DATA QUALITY: last import 98.7% clean · 41 skipped   │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Stock Controller".** Balance-sheet-of-units mindset; burn-down language.
Watches: DOS tails, dead stock, transfer suggestions, import quality. Never: pricing calls (routes
to Category).

**Decisions.** Approves: transfer confirmations, reorder-point changes, count schedules. Sage
handles: transfer suggestions, dead-stock lists, DOS alerts, import QC reports.

**Navigation.** Today · Stock Health · Transfers · Dead Stock · Imports (QC) · Ask Sage.
**Top-10 KPIs.** 1 Dead stock AED ✅ · 2 DOS avg + tails ✅ · 3 Stockout-days ✅ · 4 Transfer cycle ✅ ·
5 Inventory accuracy 🔷(counts) · 6 Import quality ✅ · 7 Expiry-risk units 🔶 · 8 Below-reorder count ✅ ·
9 Overstock AED ✅ · 10 Turn rate 🔶.
**Notifications.** T1 stock brief. T0: chain-level stockout of top-10 SKU. T3 weekly burn-down.
**Device.** Desktop.

---

## R11 · Marketing Manager — *"Campaigns that provably move the number."*

**Mission.** Spend where uplift is measured, not assumed. The measure loop applied to promos is
their unfair advantage over every retailer still guessing.

**A day.** Reviews live promo scoreboard (uplift vs forecast baseline — engine exists). Approves
one promo draft Sage generated from a `promote` finding. Plans DSF slate against the UAE calendar.
Post-mortem: last promo +18% uplift, −3% cannibalization → keep. Reports to CMO/CEO.

**Homepage — "Campaigns".**
```
┌──────────────────────────────────────────────────────┐
│ SAGE: "Dates promo: +18% uplift vs baseline, day 4.  │
│ Juice promo is flat — consider stopping (AED 3k/day  │
│ spend). DSF starts in 40 days: slate 40% drafted."   │
├──────────────────────────────────────────────────────┤
│ LIVE SCOREBOARD: uplift · spend · cannibalization    │
├──────────────────────────────────────────────────────┤
│ SEASONAL PLANNER: Ramadan → Eid → DSF timeline       │
├──────────────────────────────────────────────────────┤
│ SAGE PROPOSALS: 2 promo drafts from findings [review]│
├──────────────────────────────────────────────────────┤
│ POST-MORTEMS: 3 measured [library]                   │
└──────────────────────────────────────────────────────┘
```

**Sage persona — "Campaign Analyst".** Uplift-literal, kill-your-darlings honest. Opens with the
scoreboard. Never: vanity metrics; never claims uplift without a baseline.

**Decisions.** Approves: promo ≤25k launch/stop, creative briefs. Escalates >25k → COO. Sage
handles: proposal drafts, baseline forecasts, uplift measurement, stop-loss flags, post-mortems.

**Navigation.** Today · Live Campaigns · Planner (calendar) · Proposals · Library · Ask Sage.
**Top-10 KPIs.** 1 Uplift vs baseline ✅ · 2 Spend vs plan ✅ · 3 Cannibalization ✅ · 4 Promo margin 🔶 ·
5 Stop-loss saves ✅ · 6 Seasonal readiness ✅ · 7 Sell-through of promo stock ✅ · 8 Repeat-promo
fatigue ✅ · 9 Basket attach 🔷 · 10 Footfall lift 🔷.
**Notifications.** T1 scoreboard brief. T0: live promo stop-loss trigger. T3 slate review weekly.
**Device.** Desktop + phone scoreboard.

---

## R12 · Sales Executive (floor lead) — *"Sell what today wants."*

**Mission.** Floor-level selling intelligence: what's hot today, what to push, what's out.
**A day.** Shift-start phone brief: *"Here are today's products most likely to sell."* Top-5 likely
sellers (per-item forecast), attach suggestions, out-of-stock awareness so they never walk a
customer to an empty shelf. Logs a shelf-gap with one photo 🔷. Reports to Store Manager.
**Homepage (phone card-stack).** ① Today's likely top-5 (forecast) ② Push list (overstock near
expiry — sell-first) ③ Out-of-stock list (don't promise) ④ My shift note.
**Sage persona — "Sales Coach".** Peppy, list-based, 30-second reads. Never: dashboards.
**Decisions.** None to approve — *executes*; can flag (gap, damage, price query) which becomes a
finding-lite for the Store Manager.
**Navigation (3 tabs).** Shift · Products · Ask Sage.
**Top KPIs (5, ranked).** Today's store number ✅ · likely sellers hit-rate ✅ · push-list
sell-through ✅ · flags raised→fixed ✅ · attach rate 🔷.
**Notifications.** Shift-start brief only. **Device.** Phone-only. Voice-friendly.

---

## R13 · Finance Team (AP/AR) — *"Invoices right, on time, VAT-clean."*

**Mission.** The billing engine's daily operators: issue, chase, reconcile, e-invoice.
**A day.** Queue: 4 invoices to issue (Sage-drafted from subscriptions), 3 overdue (dunning drafts
ready), 1 e-invoice clearing status, VAT check auto-passed. Month-end: export pack for CFO.
Reports to CFO.
**Homepage.** ① Work queue (issue/chase/reconcile) ② Aging ladder ③ e-invoice statuses ④ VAT
sanity strip ⑤ month-end progress.
**Sage persona — "Ledger Assistant".** Meticulous, template-driven. Opens with the queue count.
Never: touches money without a human click.
**Decisions.** Executes issue/mark-paid (per ladder); escalates disputes → CFO.
**Navigation.** Today · Invoices · Aging · E-invoicing · Exports · Ask Sage.
**Top KPIs.** Invoices on-time % ✅ · AR aging buckets ✅ · dunning response rate ✅ · e-invoice
acceptance ✅ · VAT exceptions ✅ (10 total incl. close-cycle time, credit notes, write-offs 🔶,
dispute rate, statement accuracy).
**Notifications.** T2 queue badges; T1 daily queue summary. **Device.** Desktop.

---

## R14 · HR Manager — *"The right people on the floor at the right hours."*

**Mission.** Staffing that follows demand; retention of the people who move the number.
(Employees module exists; scheduling/attendance is 🔷 — this playbook is the target.)
**A day.** Coverage board vs demand forecast (traffic proxy = units/hour ✅). Two swap approvals
🔷. Attrition-risk flags 🔷. New-hire onboarding checklist. Reports to CHRO/CEO.
**Homepage.** ① Coverage vs forecast heat-strip (per store) ② swap/leave queue 🔷 ③ attrition
watch 🔷 ④ hiring pipeline 🔷 ⑤ performance highlights (employee module ✅).
**Sage persona — "Workforce Advisor".** People-first, demand-aware. *"Friday 6–9pm at Deira is
under-covered vs forecast — two options."* Never: performance gossip; only measured signals.
**Decisions.** Approves: schedules, hires, policy exceptions. Sage: schedule drafts vs forecast,
coverage alerts, onboarding checklists.
**Navigation.** Today · Coverage · People · Requests · Ask Sage.
**Top KPIs.** Coverage vs demand 🔷/✅proxy · sales per labor-hour 🔷 · attrition 🔷 · overtime 🔷 ·
open positions 🔷 · onboarding time ✅ · training completion 🔷 · swap SLA 🔷 · absence rate 🔷 ·
staff cost % 🔶.
**Notifications.** T1 coverage brief; T0 same-day coverage break. **Device.** Desktop + phone approvals.

---

## R15 · Customer Service Manager — *"Every return is a signal."*

**Mission.** Returns and complaints as an intelligence stream, not a cost center. Today's platform
already detects return spikes and high return-rate categories — this role *owns that queue*.
**A day.** Return-spike finding triage (their lane). Refund-exception approval. Weekly: "voice of
returns" pack to Category ("GreenFarm juice: 40% of returns cite leakage 🔷 reasons").
**Homepage.** ① Returns pulse (today/wk, by store & category ✅) ② my findings queue ✅ ③ refund
exceptions ④ repeat-return SKUs ✅ ⑤ complaint themes 🔷.
**Sage persona — "CX Specialist".** Empathetic-but-forensic. *"Returns up 22% — concentrated in
one batch; here's the supplier email draft."* Never: blames customers.
**Decisions.** Approves: refund exceptions, goodwill credits ≤ cap. Escalates batch recalls →
Procurement/COO. Sage: spike detection ✅, supplier-quality drafts ✅, return-reason clustering 🔷.
**Navigation.** Today · Returns · Exceptions · Signals→Category · Ask Sage.
**Top KPIs.** Return rate ✅ · spike findings resolved ✅ · refund cost ✅(derived) · repeat-return
SKUs ✅ · time-to-resolution ✅ · exception rate ✅ · NPS 🔷 · complaint themes 🔷 · recovery rate 🔷 ·
supplier-caused share 🔶.
**Notifications.** T1 returns brief; T0 spike critical. **Device.** Desktop.

---

## R16 · Warehouse Manager — *"Everything that moves, confirmed."*

**Mission.** Inbound POs received clean, transfers picked and shipped, discrepancies logged.
**A day.** Dock view: today's inbound (PO ETAs ✅), transfer pick-list (suggestions confirmed by
Regional — their execution queue), 2 discrepancy logs (received ≠ ordered). Scanner-first.
Reports to COO/Inventory.
**Homepage (tablet/scanner).** ① Today's inbound (PO, supplier, ETA, dock 🔷) ② pick list
(transfers) ③ discrepancy queue ④ space pressure 🔷.
**Sage persona — "Flow Controller".** Terse, scan-and-confirm. *"7 inbound today. Al Kabeer is
late again — flagged to Procurement."* Never: paragraphs.
**Decisions.** Confirms receipts/shipments; flags discrepancies (auto-notifies Procurement).
Sage: ETA watching, pick-list optimization 🔷, discrepancy pattern flags.
**Navigation.** Today · Inbound · Transfers · Discrepancies · Ask Sage.
**Top KPIs.** Receipts on-time ✅ · transfer pick SLA ✅ · discrepancy rate ✅ · dock utilization 🔷 ·
damaged-in 🔷 · put-away time 🔷 · inbound accuracy ✅ · open POs aging ✅ · space 🔷 · safety events 🔷.
**Notifications.** Real-time during shift only. **Device.** **Tablet + scanner**, rugged phone.

---

## R17 · Auditor — *"Show me the trail."* (read-only; the PDPL trust seller)

**Mission.** Independent evidence: who decided what, on what basis, with what outcome. This role
is a *sales asset* — walk a client's auditor through it and the deal closes.
**A day.** Samples 10 decisions: each shows evidence → approver → timestamp → outcome (the
decision cards ARE the audit trail). Exports a PDPL evidence pack (audit log CSV — shipped).
Verifies a data-deletion request's execution. Reviews access-change log.
**Homepage.** ① Evidence search (by user/date/type) ② decision-trail sampler ③ exports (packs) ④
data-rights register ⑤ access-change feed. **All read-only, watermarked.**
**Sage persona — "Evidence Assistant".** Neutral, citation-only. *"Here are the 14 events matching
your query, with hashes."* Never: opinions; never summarizes away detail.
**Decisions.** None. Flags anomalies → CIO/CEO.
**Navigation.** Evidence · Decisions Trail · Data Rights · Access Log · Exports.
**Top KPIs.** Log completeness ✅ · decision-evidence coverage ✅ · data-rights SLA ✅ · access
anomalies ✅ · export integrity ✅ (5 core; auditors need depth not breadth).
**Notifications.** None push; weekly integrity digest. **Device.** Desktop.

---

## R18 · System Administrator — *"Tenant healthy, users right, keys safe."*

**Mission.** Day-2 operations of the tenant: users/seats, keys, webhooks, usage vs plan, lifecycle.
(The operator console, dev portal, metering — all shipped.)
**A day.** Two invites (role bundles pre-pick the persona), one API key rotation, webhook failure
retry, usage check (62% of plan), demo-tenant reset check.
**Homepage.** ① User/seat panel ② keys & webhooks health ③ usage vs plan meters ④ tenant
lifecycle status ⑤ incident strip (from monitoring).
**Sage persona — "Platform Operator".** Runbook-flavored. *"Webhook #3 failing since 09:12 —
retry or disable?"* Never: touches business data.
**Decisions.** Executes user/key/webhook ops; escalates plan changes → CFO, security → CIO.
**Navigation.** Today · Users & Seats · API & Webhooks · Usage & Plan · Tenant · Ask Sage.
**Top KPIs.** Seat utilization ✅ · key age ✅ · webhook success ✅ · usage vs quota ✅ · invite
acceptance ✅ · MFA coverage ✅ · stale accounts ✅ · incident count ✅ (8).
**Notifications.** T0 platform incidents; T2 badges. **Device.** Desktop.

---

## R19 · Loss Prevention Manager* — *"Find the leaks people cause."* (roadmap role)

**Honest gate:** real LP needs transaction/basket grain 🔷 (voids, discounts-per-cashier, refund
patterns). Until the POS connector lands, this role's surface is limited to: return-rate anomalies
by store ✅, refund-exception audit ✅, inventory-vs-sales variance hints 🔶. Design the persona
now ("Shrink Detective" — pattern-led, presumption of innocence, evidence packs to HR/COO), ship
the role **with the POS integration** (blueprint E2). Anything earlier would be theater.

## R20 · Supplier (external portal)* — *"My orders, my scorecard, my invoices."* (roadmap)

The public API + webhooks + e-invoicing engines make a thin supplier portal cheap: my POs (ack,
ETA update), my OTIF scorecard (transparency improves behavior), my invoices/clearing status.
Sage persona: **"Trade Partner Assistant"** — polite, contractual, bilingual. Strategic value:
every supplier touchpoint becomes your data moat. Ship after 3 paying tenants ask.

---

# PART 3 — CROSS-CUTTING STRATEGIES

## 3.1 Notification strategy — attention is the scarcest resource

**The contract: a role's phone buzzes only for its own ladder rung.** Four tiers:

| Tier | Channel | Rule |
|---|---|---|
| **T0 Interrupt** | push/SMS | Role-scoped criticals only; hard cap ~3/day; every T0 carries a one-tap action |
| **T1 Brief** | push+email at role's cadence | The Sage narrative (07:00 exec · 06:45 COO · 07:40 store · shift-start floor · 08:00 CFO) |
| **T2 Queue** | in-app badges | Never leaves the app; SLA clock visible |
| **T3 Digest** | email weekly/monthly | Measured outcomes ("what worked"), never raw alerts |

**Anti-noise rules:** dedupe by finding key (exists); escalation replaces repetition (unactioned →
one rung up, not re-ping); quiet hours per role (store: closed hours; execs: 22:00–06:30);
every notification is deep-link actionable; a monthly "notification honesty" stat per user
("you acted on 62% — Sage will trim the rest").

## 3.2 Mobile & device strategy

| Role | Primary | Secondary | Voice | Notes |
|---|---|---|---|---|
| CEO/CFO/COO | Phone (brief+approve) | Desktop (depth) | car brief (road) | one-tap decisions |
| VP Ops / Regional | **Tablet** (visits) | Phone | — | Visit Mode offline-capable |
| Store Manager | **Phone PWA** | — | ✅ stock queries | AR/EN, thumb-reach, offline queue |
| Sales Executive | Phone-only | — | ✅ | card stack, 30-second reads |
| Warehouse | Tablet + scanner | rugged phone | — | scan-confirm flows |
| Category/Marketing/Procurement/Inventory | Desktop | Phone (approve/scoreboard) | — | queues + boards |
| Finance/Auditor/CIO/SysAdmin | Desktop | — | — | dense tables OK |
| Watch (roadmap) | Store/Regional task pings + T0 only | | | |

**Rule: nothing ships for a phone-first role until it passes the "walking test"** — usable
one-handed, walking, in 10 seconds, in Arabic.

## 3.3 Collaboration workflows (the major retail processes)

**W1 — Stockout → replenishment (the canonical loop, mostly shipped):**
```
Sage detects low cover (forecast) → drafts PO with evidence
  → ≤2k: places it (L2), logs to Procurement digest
  → 2k–10k: Store Manager confirms (phone, one tap)
  → 10k–50k: Procurement approves → Warehouse receives → discrepancy check
  → Sage measures: stockout avoided? days-of-cover restored? → outcome on the decision card
```

**W2 — Store performance rescue:**
```
Sage: revenue_drop finding (evidence) → routes to Regional (triage — shipped)
  → Regional opens Visit Packet → diagnoses with Store Manager → picks playbook
  → tasks created for store (photo-confirm) → COO sees flow board
  → Sage re-measures weekly → improved: auto-resolve + win in CEO brief
  → worsened ×2: escalates to COO with decomposition; chronic: VP Ops rescue program
```

**W3 — Promotion lifecycle:**
```
Category/Sage proposes (uplift forecast + baseline attached) → Marketing shapes creative
  → ≤25k Marketing approves / >25k COO → stores get execution tasks (shelf, signage)
  → live scoreboard (uplift vs baseline) → stop-loss trigger if flat → post-mortem to library
  → measured uplift feeds the next proposal's confidence
```

**W4 — Supplier quality incident:**
```
CS Manager: return-spike finding → clusters to one batch → Sage drafts supplier email
  → Procurement sends + logs → supplier response tracked → repeat: watchlist ↑, terms review
  → Category consulted on de-list → COO approves switch → Sage measures return-rate recovery
```

**W5 — Price change:**
```
Sage: price-anomaly/margin flag → Category drafts change (impact forecast attached)
  → ≤5% Category + CFO informed / >5% CFO co-sign → stores execute (shelf-label task 🔷)
  → Sage measures: volume response, revenue net effect → outcome to Category's library
```

**W6 — Branch transfer (shipped path, formalized):**
```
Sage suggests (overstock↔stockout, qty capped) → Inventory sanity-checks → Regional approves
  → Warehouse picks/ships → receiving store confirms (photo/scan) → Sage confirms both stock
  levels moved + sale resumed → cycle-time to COO flow board
```

**W7 — Month-end close:**
```
Sage assembles: revenue actuals vs forecast, VAT invoice set, AR aging, outcome-pricing statement
  → Finance Team reconciles queue → CFO reviews variance narrative → approves statement
  → board pack fragment flows into CEO's monthly brief → Auditor sees the immutable trail
```

**W8 — Data onboarding (pilot day one):**
```
SysAdmin invites roles (persona auto-assigned) → Inventory/ops upload CSV/Excel → QC report
  → fixes → commit → Sage: "I can see your stores now — here's your first AED number" (/value)
  → 48h later: first findings → first routed decisions → first measured outcome ≤ 2 weeks
```

## 3.4 Feature access matrix (RBAC)

✅ full · 👁 read · ◽ none. (Grouped columns; the config system holds the per-role truth.)

| Surface | Exec (CEO/COO/CFO) | VP/Regional | Store/Floor | Merch (Cat/Mktg) | Supply (Proc/Inv/Whs) | Finance | HR | CS | CIO/SysAdmin | Auditor |
|---|---|---|---|---|---|---|---|---|---|---|
| Today (brief) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 👁 |
| Decisions (triage) | ✅ | ✅ scoped | confirm-only | ✅ scoped | ✅ scoped | ◽ | ◽ | ✅ scoped | ◽ | 👁 |
| My Team | ✅ | ✅ | ✅ (floor) | ◽ | ✅ | ◽ | ✅ | ✅ | ◽ | ◽ |
| Business (analytics) | ✅ | ✅ scoped | 👁 own store | ✅ scoped | ✅ | 👁 | 👁 | 👁 | ◽ | 👁 |
| Value / ROI | ✅ | 👁 | ◽ | 👁 | ✅ | ✅ | ◽ | ◽ | ◽ | 👁 |
| Buying (PO/suppliers) | 👁 (+approve rung) | 👁 | confirm rung | 👁 category | ✅ | 👁 | ◽ | ◽ | ◽ | 👁 |
| Campaigns | 👁 | 👁 | tasks only | ✅ | 👁 stock | ◽ | ◽ | ◽ | ◽ | 👁 |
| Invoices/VAT/Billing | CFO ✅ | ◽ | ◽ | ◽ | ◽ | ✅ | ◽ | ◽ | plan 👁 | 👁 |
| Imports / Data | ◽ | ◽ | ◽ | ◽ | ✅ (Inv) | ◽ | ◽ | ◽ | ✅ | 👁 |
| People (employees) | 👁 | ✅ own | ✅ own | ◽ | ◽ | ◽ | ✅ | ◽ | ◽ | 👁 |
| Audit / Evidence | 👁 | ◽ | ◽ | ◽ | ◽ | 👁 | ◽ | ◽ | ✅ | ✅ |
| Admin (users/keys/tenant) | ◽ | ◽ | ◽ | ◽ | ◽ | ◽ | ◽ | ◽ | ✅ | 👁 access log |
| Forecast Lab (expert) | 👁 | ◽ | ◽ | ✅ | ✅ | ◽ | ◽ | ◽ | ✅ | ◽ |
| Ask Sage | ✅ persona | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ citations-only |

## 3.5 Product recommendations — making it feel custom-built for every role

1. **Ship the role config engine, not 20 apps.** Server-driven homepage layout (zone list per
   role) + persona pack + nav manifest. One rendering engine; the Briefing and Decision Center
   already prove the two hardest zone types.
2. **Persona packs as content, not code.** Each = system-prompt fragment, greeting templates,
   vocabulary rules, notification defaults. Product/ops can tune personas without deploys.
3. **Role-first onboarding.** The invite carries the role → first login opens *their* Today with
   *their* Sage introducing itself in role language ("I'm your Store Coach…"). The
   OnboardingChecklist becomes role-specific (store manager: install PWA, confirm first task).
4. **"My Work" is the universal spine.** One task/decision object across all roles (assign, due,
   confirm, measure). Every workflow in 3.3 is states of the same object — build it once (this is
   audit item E7-8, promoted to platform primitive).
5. **The AED ladder is a settings page.** Tenant admins tune thresholds per rung (the existing
   `approval_rules` generalized). Sage's autonomy is visibly *on the same page* — trust through
   placement.
6. **Persona switcher for the demo.** "View as Store Manager / CFO / Auditor" in the demo tenant —
   the single most persuasive sales artifact this blueprint enables.
7. **KPI registry with readiness flags.** Central registry (name, derivation, ✅/🔶/🔷, owner
   role). Homepages *pull* from it; the "needs cost data" upsell becomes systematic, not ad hoc.
8. **Arabic parity is store-down, not exec-down.** Localize Store Manager and Sales Executive
   surfaces to 100% first (they're the largest AR-first population), then Regional, then exec.
9. **Silence as a feature.** Market it: "Your phone buzzes at most 3 times a day, and only for
   your own decisions." No incumbent can say it.
10. **Measured-outcome language everywhere.** Every role's digest leads with "what worked" —
    the outcome loop is the brand, in every persona's voice.
11. **Role KPIs on the pricing page.** Sell seats by persona value ("Store Coach seat", "Buying
    Desk seat") — maps to the plan/seat machinery that already exists.
12. **Sequence honestly.** Wave 1 (configs over existing engines): CEO, COO, Regional, Store,
    Procurement, Inventory, SysAdmin. Wave 2 (new scope axis + surfaces): Category, Marketing,
    CFO, Finance, CS, Auditor, CIO, VP Ops. Wave 3 (new data): HR, Warehouse, Sales Executive
    (tasks 🔷), Loss Prevention (POS), Supplier portal.

---

*End of blueprint. Companion docs: `docs/EXECUTION_BLUEPRINT_12M.md` (when), `implementation.md`
(what's shipped). This document is the **how it should feel**.*
