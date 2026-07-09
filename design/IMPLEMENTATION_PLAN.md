# Implementation Plan — Retail IQ Experience Redesign

**Source of truth:** the other files in `design/`. This plan translates them into an engineering
sequence. **No code has been written; this awaits approval.**

## 0. The one finding that shapes everything

This is a **reframe of a complete, already-config-driven app — not a greenfield build.**

- **All 43 routes already exist** (every route in the IA route-map table is present).
- **All backend APIs the flows reference already exist** (verified against the running app).
- The **Role Experience config engine is already live** (`role_experience.py` v2 →
  `/api/experience` → `ExperienceContext`) and already emits `nav`, `homepage/zones`, `kpis`,
  `quick_actions`, `assistant_mode`, `ai_context`, `capabilities`, `decision_scope`. The design's
  central thesis ("experience is configuration, not duplicated pages") is **already implemented**.

Therefore the redesign is **not** "rebuild pages." It is five concentrated moves:

| # | Move | Where the work is |
|---|---|---|
| M1 | Flat sidebar → **layered domain shell** (domain rail + context rail + utility bar) | `components/shell/*` |
| M2 | Flat per-role `nav` → **domain-grouped nav manifest** (the config becomes the IA) | `role_experience.py` schema + `ExperienceContext` types |
| M3 | Introduce the **design-system tokens + state grammar** (alias existing → named tokens) | `globals.css`, `tailwind.config`, `ui/` |
| M4 | One **shared workflow object** unifying decisions/findings/approvals/drafts/alerts | new `components/workflow/*` |
| M5 | Five **page templates** + consistent states, adopted page-by-page (strangler) | new `components/templates/*` |

Everything else (backend, routes, data, auth, RLS, AI grounding) is **untouched** — consistent
with PRD §10 non-goals and the "do not rewrite the app at once" rule in DESIGN_SYSTEM §2.

---

## 1. Component Dependency Graph

Dependencies flow **downward** (upper layers import lower). Two cross-cutting providers feed the
whole tree: **ExperienceContext** (server-driven config) and **Auth/Language contexts**.

```
                          ┌──────────────────────── CROSS-CUTTING PROVIDERS ───────────────────────┐
                          │ ExperienceContext (nav/homepage/kpis/assistant/capabilities/scope)     │
                          │ AuthContext · LanguageContext(RTL) · ThemeContext(light-only)           │
                          │ lib/api (typed facade, 22 helpers) → lib/apiClient (auth/refresh)       │
                          └───────────────────────────────────────────────────────────────────────┘
                                                          ▲ (read by shell + templates + zones)
 L6  ROUTE PAGES (43)  app/**/page.tsx  ── each wrapped by exactly one template ──────────────────────┐
        │  Home: /today /briefing /copilot   Workflows: /decisions /insights /alerts /approvals ...    │
        │  Operations: /inventory /procurement(+po/[id]) /promotions /employees                        │
        │  Intelligence: /analytics /forecast-lab /reports /value /uae-insights                        │
        │  Platform: /data-sources /imports /developers /monitoring /status                            │
        │  Admin: /admin(+/tenants) /settings/* /pricing /outcome-pricing /security /audit /trust      │
        └───────────────┬──────────────────────────────────────────────────────────────────────────┘
                        │ composes
 L5  SHELL              ▼
        AppShell ── DomainRail(6 domains) · ContextRail(domain pages/sections) · UtilityBar
        UtilityBar ── CommandPalette · NotificationTray · ScopeChip · LanguageSwitcher · AccountMenu · SageLauncher
                        │ driven by ExperienceContext.nav (grouped manifest)
 L4  TEMPLATES + ZONES  ▼
        HomeTemplate · WorkflowTemplate · OperationsTemplate · IntelligenceTemplate · PlatformAdminTemplate
        ZoneRenderer (Today) ── ZONE_REGISTRY{ verdict, kpis, decisions, approvals, stock, quick_actions,
                                               ai_context, feed }
                        │ compose
 L3  DOMAIN BLOCKS      ▼
        WORKFLOW/  WorkflowQueueItem ──▶ DecisionCard · FindingCard · ApprovalCard · DraftCard · AlertItem · OutcomeBlock
        AI/        AiSummaryBand · AiAnswerBlock · ChatPanel(from ChatBot) · CopilotFeedWidget
                        │ compose
 L2  COMPOSITE UI       ▼
        PageHeader · SectionHeader · HeroVerdict · MetricStrip · KpiCard · EntityTable · FilterBar ·
        DetailDrawer · Timeline/AuditTrail · Stepper · EnterpriseFormSection · SecretRevealDialog ·
        ConnectionTestResult · InvoiceMatchPanel
        STATE/     EmptyState · ErrorState · NoPermissionState · LoadingSkeleton · StatusBanner · ConnectionBanner
                        │ compose
 L1  PRIMITIVES         ▼
        Button · Card · Badge · StatusPill · Input · Select · Table · Tabs · Modal/Dialog · Drawer ·
        Skeleton · Toast · AnimatedNumber · ChartFrame · motion
                        │ read
 L0  FOUNDATION         ▼
        Design tokens (color/space/radius/elevation/motion) · Tailwind config · fonts (Manrope/Plex Mono/Arabic)
```

**Critical shared nodes (build these once, reuse everywhere):**
- `WorkflowQueueItem` — the single scaffold behind decisions, findings, approvals, drafts, alerts
  (PRD §7.5, PRINCIPLES §5). Highest-leverage new component.
- `AiAnswerBlock` — the canonical answer anatomy (verdict → evidence → confidence → scope → next
  step) reused by briefing, copilot, chat, and inline summary bands (AI_EXPERIENCE §4).
- `EntityTable` + state slots — every admin/dev/ops/billing table.
- `DetailDrawer` — review-without-losing-queue across all workflow + operations surfaces.

**Cycle risk to avoid:** the shell must depend on `ExperienceContext` but **not** on any page;
zones must not import pages. Templates import blocks, never other templates.

---

## 2. Implementation Roadmap

Ordering reconciles PRD §13 (Home→Workflows→Operations→Platform→Admin→Intelligence) with
DESIGN_SYSTEM §13 (foundation first). Foundation is Phase 0 because every later phase needs it.

| Phase | Goal | Scope | Exit criteria |
|---|---|---|---|
| **P0 — Foundation** | Tokens, shell, states, config schema | M2 config schema (grouped nav, back-compat); M3 tokens aliased; new shell (DomainRail/ContextRail/UtilityBar) rendering from config with fallback to today's Sidebar; state components (Empty/Error/NoPermission/Loading/Degraded) | Shell renders all 6 domains from config for the 3 live roles; every route still loads; `tsc` + build green; zero visual regressions on unmigrated pages |
| **P1 — Home** | The daily contract (PRINCIPLES §2) | `/today` zone renderer polished to HomeTemplate; `/briefing`; `/copilot`; global Chat Panel unified on `AiAnswerBlock`; HeroVerdict + MetricStrip components | Today/Briefing/Copilot use one AI grammar; role variants B01–B03 + fallback B04; states B06/B07 |
| **P2 — Workflows** | One workflow grammar (M4) | Build `WorkflowQueueItem` + Decision/Finding/Approval/Draft/Alert cards + `OutcomeBlock` + `DetailDrawer`; migrate `/decisions /insights /alerts /approvals /action-drafts` onto it | All five surfaces share severity/scope/impact/confidence/evidence/action/outcome; drawer preserves queue position (C03) |
| **P3 — Operations** | Prove business usefulness | OperationsTemplate; `/inventory /procurement(+po/[id]) /promotions /employees`; Timeline, InvoiceMatchPanel, FilterBar; **preserve the shipped reorder→PO→item-highlight→approve flow** | Reorder→receive continuity (USER_FLOWS §8) intact; invoice matching lives inside procurement (§9) |
| **P4 — Platform** | Enterprise trust (ingest/dev/monitor) | PlatformAdminTemplate; `/data-sources /imports /developers /monitoring /status`; Stepper, SecretRevealDialog, ConnectionTestResult, EntityTable everywhere | Import wizard + data-source test + dev key/webhook lifecycle on shared components |
| **P5 — Admin** | Governance clarity | `/admin(+/tenants) /settings/* /pricing /outcome-pricing /security /audit /trust`; consolidate Billing+Pricing+Outcome into one "Billing and Plans"; move Profile/Preferences to utility layer | IA §4 placements resolved; Trust one move away (PRINCIPLES §8) |
| **P6 — Intelligence** | Simplify last, using the established system | IntelligenceTemplate; `/analytics /forecast-lab /reports /value /uae-insights`; disciplined ChartFrame usage | ≤4 chart frames/page; annotation-led; units/AED never mixed |
| **P7 — Hardening** | AA + responsive + RTL + motion | Cross-cutting accessibility pass, density modes, reduced-motion, Arabic/RTL, keyboard traversal | WCAG AA; keyboard-operable shell/tables/drawers/chat; RTL clean |

**Screen-inventory release order** (SCREEN_INVENTORY §10) rides inside these phases:
B01–B09 → C01–C09 → D01–D08 → F01–F09 → G04–G13 → E01–E07 → H01–H05.

**Parallelizable:** P0 tokens ∥ P0 state components; within P2–P6, domains are independent once
P0+shared blocks exist (multiple people can migrate one domain each).

---

## 3. Folder Restructuring Plan

Principle: **additive, not a move-everything churn.** Existing domain folders stay; we add four
new folders and promote shared concepts out of pages.

```
frontend/src/
  app/                         # UNCHANGED routes (43). Pages get thinner: wrap in a template.
    (compat) /  ──▶ redirect to /today   (already behaves this way; formalize)

  components/
    shell/                     # EVOLVE
      AppShell.tsx             # keep; recompose to DomainRail+ContextRail+UtilityBar
      DomainRail.tsx           # NEW — 6 domains only, role-filtered, collapsed/expanded/mobile
      ContextRail.tsx          # NEW — domain pages + labeled sections + badge counts
      UtilityBar.tsx           # NEW — from Topbar; hosts palette/notif/scope/lang/account/Sage
      Sidebar.tsx              # RETIRE after P0 (kept as fallback during migration)
      Topbar.tsx               # FOLD into UtilityBar

    ui/                        # KEEP + fill gaps (shadcn-style grammar, wrapping existing)
      (add) Drawer.tsx  StatusPill.tsx  NoPermissionState.tsx  StatusBanner.tsx
      (align) Button/Card/Badge/Input/Select/Table/Tabs/Modal/Skeleton/Toast/ChartFrame/…

    workflow/                  # NEW — the shared work-object grammar (M4)
      WorkflowQueueItem.tsx    # scaffold: severity·scope·impact·confidence·evidence·action
      DecisionCard.tsx  FindingCard.tsx  ApprovalCard.tsx  DraftCard.tsx  AlertItem.tsx
      OutcomeBlock.tsx

    ai/                        # NEW — one AI interaction grammar (consolidates today's spread)
      AiAnswerBlock.tsx  AiSummaryBand.tsx  ChatPanel.tsx (from ChatBot.tsx)  CopilotFeedWidget.tsx

    templates/                 # NEW — the five page templates (DESIGN_SYSTEM §6)
      HomeTemplate.tsx  WorkflowTemplate.tsx  OperationsTemplate.tsx
      IntelligenceTemplate.tsx  PlatformAdminTemplate.tsx

    home/                      # KEEP — Today zone renderer + zones (expand registry)
    admin/ alerts/ analytics/ charts/ copilot/ employees/ inventory/
    monitoring/ promotions/ reports/ settings/          # KEEP domain internals

  lib/
    nav/                       # NEW — domain manifest types + icon registry
      domains.ts               # the 6 domains, icons, order (mirrors backend)
      icons.ts                 # string→icon map (moved out of Sidebar)
    api.ts apiClient.ts brand.ts chart.ts cn.ts …       # KEEP

  contexts/
    ExperienceContext.tsx      # EXTEND types for grouped nav (already v2-shaped)
    AuthContext.tsx LanguageContext.tsx ThemeContext.tsx # KEEP (Theme stays light-only)

backend/app/services/
    role_experience.py         # EVOLVE — nav manifest becomes domain-grouped (single IA source)
```

**Retirements (deferred, not deleted during migration):** `Sidebar.tsx`, `Topbar.tsx`,
`ThemeToggle.tsx` (dark mode is a PRD non-goal), `AIToggleButton`/`ChatBot` (fold into `ai/`).

---

## 4. Component Hierarchy (composition tree)

```
<Providers> (Language → Auth → Experience → Toast → AI)
└─ ClientLayout
   ├─ (public routes) → bare page
   └─ AppShell
      ├─ DomainRail            ← ExperienceContext.nav (domains)
      ├─ ContextRail           ← ExperienceContext.nav[activeDomain].pages/sections
      ├─ UtilityBar
      │  ├─ CommandPalette (⌘K) · NotificationTray · ScopeChip
      │  ├─ LanguageSwitcher · AccountMenu (profile/preferences/logout)
      │  └─ SageLauncher → ChatPanel(drawer)   [assistant_mode: panel|copilot|hidden]
      └─ <main> PageTransition
         └─ ONE template per route:
            ├─ HomeTemplate
            │  ├─ HeroVerdict            (AiAnswerBlock-based)
            │  ├─ MetricStrip → KpiCard[]
            │  └─ ZoneRenderer → [verdict|kpis|decisions|approvals|stock|quick_actions|feed]
            │        └─ WorkflowQueueItem[] · CopilotFeedWidget[] · AiSummaryBand
            ├─ WorkflowTemplate
            │  ├─ PageHeader · FilterBar(tabs/filters)
            │  ├─ Queue → WorkflowQueueItem → {Decision|Finding|Approval|Draft|Alert}Card → OutcomeBlock
            │  └─ DetailDrawer (review without losing queue)
            ├─ OperationsTemplate
            │  ├─ PageHeader · status strip · FilterBar
            │  ├─ EntityTable (+ empty/loading slots)
            │  └─ DetailDrawer / Timeline / InvoiceMatchPanel   (e.g. procurement/po/[id])
            ├─ IntelligenceTemplate
            │  ├─ PageHeader · FilterBar · MetricStrip
            │  └─ ChartFrame[] (≤4) · summary band
            └─ PlatformAdminTemplate
               ├─ PageHeader · StatusBanner (trust/system)
               ├─ EntityTable / EnterpriseFormSection / Stepper
               └─ SecretRevealDialog · ConnectionTestResult · AuditTimeline
      Global states (any template slot): LoadingSkeleton · EmptyState · ErrorState · NoPermissionState
```

Every page resolves to: **Shell → Template → (shared blocks → primitives → tokens)**. No page
invents its own card family (DESIGN_SYSTEM §2; PRINCIPLES §10).

---

## 5. API Mapping (domain → surface → existing endpoints)

All endpoints below **already exist**; the redesign wires screens to them, adds no new ones.
Scope is enforced server-side (PRD §2.2) — the UI reads what `/api/experience` + role scoping return.

| Domain | Surface(s) | Endpoints (existing) |
|---|---|---|
| **Shell** | nav/homepage/persona/scope | `GET /api/experience` |
| **Home** | Today | `/api/experience`, `/api/briefing`, `/api/decisions/triage`, `/api/kpis`, `/api/inventory/summary`, `/api/decisions/summary` |
| Home | Executive Briefing | `/api/briefing`, `/api/briefing/print` |
| Home | Sage Copilot / Chat | `/api/ai/copilot/feed`, `/api/ai/chat`, `/api/ai/chat/stream`, `/api/ai/voice/*` |
| **Workflows** | Decisions / Outcomes | `/api/decisions`, `/api/decisions/triage`, `/api/decisions/summary`, `/api/findings/{id}/accept-action`, `/api/findings/{id}/resolve` |
| Workflows | Insights (findings) | `/api/findings`, `/api/findings/{id}/*`, `/api/action-drafts/from-finding/{id}` |
| Workflows | Alerts | `/api/alerts/*`, `/api/inventory/summary` |
| Workflows | Approvals | `/api/procurement/approvals`, `/api/decisions/triage` |
| Workflows | Action Drafts | `/api/action-drafts`, `/api/action-drafts/{id}/(approve\|reject)` |
| **Operations** | Inventory | `/api/inventory/*`, `/api/inventory/reorder-suggestions`, `/api/uae-intelligence/transfers` |
| Operations | Procurement + PO detail | `/api/procurement/purchase-orders(+/{id}(+/status\|/receive\|/invoices))`, `/generate`, `/suppliers`, `/approval-rule`, `/events`, `/invoices/{id}/match` |
| Operations | Promotions | `/api/promotions/*` |
| Operations | Workforce | `/api/employees/*` |
| **Intelligence** | Analytics | `/api/analytics/*`, `/api/kpis`, `/api/kpis/revenue-projection` |
| Intelligence | Forecast Lab | `/api/analytics/forecast*`, `/api/forecast/*` |
| Intelligence | Reports | `/api/reports/*` |
| Intelligence | Value / ROI | `/api/roi/summary`, `/api/roi/report` |
| Intelligence | UAE Insights | `/api/uae-intelligence/*` |
| **Platform** | Data Sources | `/api/data-sources`, `/api/data-sources(/{id})/test`, `/{id}/activate` |
| Platform | Imports | `/api/imports/(types\|sample/{type}\|analyze\|validate\|commit)`, `/api/imports` |
| Platform | Developer Portal | `/api/api-keys`, `/api/webhooks(+/{id}/deliveries\|/test)`, `/api/public/v1/*` |
| Platform | Monitoring / Status | `/api/monitoring/(stats\|health/detailed\|public-status\|live\|ready)` |
| **Admin** | Admin / Tenant Console | `/api/tenants/*`, `/api/tenants/{id}/(status\|notes\|events)`, `/api/tenants/metrics` |
| Admin | Company | `/api/tenants/billing-profile` |
| Admin | Billing and Plans | `/api/billing/(plans\|subscription\|invoices\|invoices/{id}(+/print))`, `/api/tenants/usage(+/period)` |
| Admin | Outcome Pricing | `/api/outcome-pricing/*` |
| Admin | Team | `/api/team(+/seats\|/{id}/role\|/{id}/status)`, `/api/auth/invite` |
| Admin | Security | `/api/security/(summary\|kpi\|events\|events/export)` |
| Admin | Audit | `/api/security/events/export` (audit category), `/api/procurement/events` |
| Admin | Trust | static/governance content |
| **Access** | Login/MFA/Invite/Verify/Reset | `/api/auth/(login\|2fa/verify\|invite\|verify-email\|forgot-password\|reset-password\|signup\|onboarding)` |

**Mapping rules:** the client stays on the **typed facade** (`lib/api.ts`, 22 helpers) over
`apiClient`; new screens add typed helpers there, never raw fetches in pages. SSE stays via the
existing `useEventStream` hook (PRD §2.2: SSE only — no WebSocket/presence implication).

---

## 6. Migration Strategy

**Strangler-fig, config-first, always-shippable.** The app keeps working at every commit; no
big-bang. Six rules:

1. **Config schema evolves backward-compatibly (M2 first).** `role_experience.py` gains a
   domain-grouped `nav` (domains → sections → pages). `ExperienceContext` reads the grouped shape
   **with a fallback** to today's flat `nav`. Old flat configs keep rendering the current sidebar
   until a role is migrated. One role at a time (start with the 3 live: store/regional/executive).

2. **Shell swaps behind config presence, with a fallback.** New `AppShell` renders
   DomainRail+ContextRail+UtilityBar **when** the config provides grouped nav; otherwise it renders
   today's `Sidebar`. This lets the shell ship in P0 with zero regression, and each role "lights up"
   the layered shell when its config is grouped. `Sidebar.tsx` is deleted only after all roles move.

3. **Tokens are aliased, not renamed hard.** Add the design's named tokens
   (`--surface-elevated`, `--surface-tint`, `--brand-*`, `--ai-*`, semantic `--success/--warning/
   --danger/--info/--ai`) in `globals.css` **mapped to existing values**, and add Tailwind theme
   keys. Existing utilities keep working; new components consume named tokens. No mass find-replace.

4. **Shared components land before the pages that need them.** P0 ships the state grammar; P2 ships
   `WorkflowQueueItem` + cards **before** migrating the five workflow pages. A page is migrated only
   when its template + blocks exist — so a migration is a thin rewrite (compose), not a rebuild.

5. **Per-page migration is atomic and reversible.** Each page PR: (a) wrap in its template, (b)
   replace bespoke cards with shared workflow/AI blocks, (c) add the five states. Routes and URLs
   never change (IA §1: "preserve existing route compatibility"). `/` continues to redirect to
   `/today`. A page that isn't migrated yet looks exactly as it does today.

6. **Guardrails on every PR:** `tsc --noEmit` + `next build` green; the affected route renders for
   its role in the live stack; units/AED separation preserved; AA contrast on new components; RTL
   check on shell + any new block. Backend/tests are not touched except the config schema (which has
   its own unit tests in `test_role_experience.py`).

**Sequencing of the strangler:**
```
P0  tokens + state grammar + new shell (fallback) + config schema (both shapes) ── ship, no regressions
P1  migrate Home configs → grouped nav lights up domain shell for those roles; Home pages → HomeTemplate
P2  workflow blocks → migrate 5 Workflow pages
P3  Operations pages (keep the shipped reorder→PO flow verbatim)
P4  Platform pages
P5  Admin pages (+ consolidate Billing/Pricing/Outcome; move Profile/Prefs to utility)
P6  Intelligence pages
P7  delete Sidebar/Topbar/ThemeToggle; accessibility+RTL+responsive hardening pass
```

**Risk register:**
| Risk | Mitigation |
|---|---|
| Shell rewrite breaks nav for a role | Fallback to `Sidebar` until that role's config is grouped; feature-detect, don't assume |
| Workflow-object refactor regresses the shipped reorder→PO→approve flow | Migrate Operations (P3) only after P2 blocks are proven; keep PO detail behavior byte-for-byte; re-run the live walkthrough |
| Token aliasing causes subtle color drift | Map named tokens to *existing* hex first; visual-diff key screens before/after |
| "shadcn migration" tempts a rewrite | DESIGN_SYSTEM §2 forbids it — adopt patterns, wrap existing primitives, never rip-replace |
| Config drift between backend nav and frontend `lib/nav/domains.ts` | Backend `/api/experience` is the single source; `domains.ts` is icon/label presentation only |
| Scope treated as cosmetic hiding | Never — role scope stays backend-enforced (PRD §2.2); nav hiding is UX on top of real authorization |

---

## Appendix A — Design → current-frontend gap (component level)

| Design component | Today | Action |
|---|---|---|
| App Shell (3-part) | AppShell = Sidebar+Topbar (1 rail) | **Recompose** into DomainRail+ContextRail+UtilityBar |
| Domain Rail / Context Rail | flat `Sidebar` (config-or-builtin) | **New** (split rail) |
| Top Utility Bar | `Topbar` | **Fold** into UtilityBar |
| Command Palette | `CommandPalette.tsx` ✓ | Reuse; add result groups (Navigate/Review/Operate/Configure/Ask) |
| Scope Chip / Sage Launcher / Notification Tray | partial (Topbar) | Formalize as UtilityBar parts |
| Hero Verdict / Metric Strip / KPI Card | `StatCard`, briefing/today inline | **Extract** to reusable blocks |
| Workflow Queue Item + Decision/Finding/Approval/Draft/Alert + Outcome | bespoke per page (`/decisions`, `/insights`, …) | **Unify** into `workflow/*` (M4) |
| AI Answer Block / Summary Band / Chat Panel / Copilot Feed Widget | `ChatBot`, copilot components, briefing | **Consolidate** into `ai/*` |
| Entity Table / Detail Drawer / Timeline / Invoice Match / Stepper / Secret Reveal | `Table`, `AuditTimeline`, some inline | **Standardize** (some new: Drawer, Stepper, SecretReveal) |
| State system (Empty/Error/NoPermission/Loading/Degraded/StatusBanner) | `EmptyState`,`ErrorState`,`ConnectionBanner`,`Skeleton` | **Complete** (add NoPermission, StatusBanner, degraded) |
| Tokens (canvas/surface-elevated/tint/brand/ai/semantic) | only `--canvas`,`--chart-grid` named; rest under legacy names | **Alias + extend** |
| Fonts (Manrope / Plex Mono / Arabic) | Manrope + Plex Mono already wired | **Add** Arabic companion for RTL |

## Appendix B — Explicit non-goals honored (no work planned)
Backend permissions/tenancy; new write operations; autonomous AI execution; separate mobile
product; dark mode. Future-labeled reserves (My Work inbox, supplier portal, SSO/SCIM console,
category-manager workspace) are **space-only**, never presented as current capability
(PRINCIPLES §14 labels).
```

*Awaiting approval before any code is written.*
