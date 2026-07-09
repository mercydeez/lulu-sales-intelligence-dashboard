# Component Graph

The frontend component dependency graph — **current state** after P0 + the
foundation refactor, plus where P1–P7 nodes land. Companion to `ARCHITECTURE.md`.
Dependencies flow **downward**: an upper node may import a lower node, never the
reverse. `[P1]…[P7]` marks nodes a later phase adds.

## 1. Cross-cutting providers (feed the whole tree)

```
LanguageProvider(RTL) → AuthProvider → ExperienceProvider → ToastProvider → AIProvider
        │                    │                │
   t(), dir            user, RBAC,      /api/experience:
                       authFetch        nav · homepage/zones · kpis ·
                                        assistant_mode · capabilities · scope
lib/api (typed facade, TTL cache) → lib/apiClient (JWT, refresh-on-401)
hooks/useEventStream (ref-counted SSE)
```

## 2. Shell subtree (built in P0, refactored here)

```
ClientLayout
└─ AppShell                                 reads useDomainNav() + useNavBadges()
   ├─ DomainRail        ← groups, activeKey            (6 domains, icon rail)
   ├─ ContextRail       ← activeGroup, badges          (pages + sections + badges)
   ├─ MobileNav         ← groups, badges               (drawer; lg:hidden)
   ├─ Topbar (utility)  language · scope chip · notifications(SSE) · account · Sage
   ├─ CommandPalette (⌘K)
   └─ <main> PageTransition → route page
   (fallback) Sidebar   ← rendered only if the adapter yields 0 domains
```

`AppShell` no longer contains nav-building logic — it consumes `useDomainNav()`.

## 3. Navigation layer (`lib/nav/`, split by concern)

```
                 ┌──────────────┐
                 │   types.ts   │  (DomainKey, DomainGroup, FlatNavItem, Breadcrumb)
                 └──────┬───────┘
      ┌─────────────────┼───────────────────────────┐
      ▼                 ▼                            ▼
 registry.ts       permissions.ts               (consumed by all)
 (DOMAINS,         (canAccessNavItem)
  ROUTE_MAP,            │
  lookups)             │
      │  ▲             │
      │  └── domains.ts (deprecated re-export shim)
      ▼                │
  adapter.ts           │        breadcrumbs.ts ─▶ registry
  (buildDomainNav,     │        favorites.ts (localStorage + useFavorites)
   activeDomainKey)    │
      │                │
      └──────┬─────────┘
             ▼
       useDomainNav.ts   ── reads config/nav + Auth + Experience; returns
                            { pathname, flatNav, groups, activeKey, activeGroup }
             ▼
          index.ts (barrel: `@/lib/nav`)  ◀── shell imports from here
```

Data-flow at runtime:
```
/api/experience.nav  ─┐
config/nav.navItems  ─┤─▶ useDomainNav ─(permissions filter, icon resolve)─▶ FlatNavItem[]
                       └─▶ buildDomainNav(registry.ROUTE_MAP) ─▶ DomainGroup[] ─▶ rails
```

## 4. UI primitives + state (`components/ui/`)

```
Button · Card · Badge · Input · Select · Table · Tabs · Modal · Skeleton ·
Toast · AnimatedNumber · ChartFrame · PageHeader · motion            (existing)
EmptyState · ErrorState · ConnectionBanner                            (existing)
NoPermissionState · StatusBanner                                      (added P0)
[P1] HeroVerdict · MetricStrip   [P2] StatusPill · Drawer · EntityTable
```

## 5. Domain blocks (added by later phases)

```
[P2] components/workflow/
     WorkflowQueueItem ──▶ DecisionCard · FindingCard · ApprovalCard · DraftCard · AlertItem · OutcomeBlock
[P1] components/ai/
     AiAnswerBlock · AiSummaryBand · ChatPanel(from ChatBot) · CopilotFeedWidget
```

Both compose only `components/ui` — never pages, never each other's siblings.

## 6. Templates + zones (added by later phases)

```
[P1..P6] components/templates/
   HomeTemplate · WorkflowTemplate · OperationsTemplate · IntelligenceTemplate · PlatformAdminTemplate
ZoneRenderer (Today) → ZONE_REGISTRY{ verdict · kpis · decisions · approvals · stock ·
                                      quick_actions · ai_context · feed }
   → HeroVerdict · MetricStrip · WorkflowQueueItem · CopilotFeedWidget · AiSummaryBand
```

## 7. Feature modules (`features/`, adopted incrementally)

```
features/home/hooks/useBriefing.ts        (seed; P1 wires /today + /briefing to it)
features/<feature>/{hooks,components,api}  (added as each phase touches a feature)
```
Hooks own data → return `{ data, loading, error, reload }`. Pages/zones call hooks,
not `fetch`.

## 8. Route pages (`app/**/page.tsx`, 43)

Each page is (or becomes) a thin wrapper: **Shell → one Template → blocks →
primitives → tokens**. No page defines its own card family or shell.

## 9. Rules encoded in this graph

- Shell depends on `ExperienceContext` + `lib/nav`, **never on a page**.
- `lib/nav` is pure/logic + one hook; **it never decides authorization**.
- Templates import blocks; blocks import primitives; **no upward or sideways imports**.
- The highest-leverage shared nodes to build once: `WorkflowQueueItem` (P2),
  `AiAnswerBlock` (P1), `EntityTable` (P2), `DetailDrawer` (P2).
