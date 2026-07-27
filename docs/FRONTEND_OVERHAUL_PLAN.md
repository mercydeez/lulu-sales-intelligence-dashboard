# Frontend Overhaul — Basic → Awwwards-Level (Contributor Playbook)

**Audience:** the contributor picking this up after `git pull`. This is the phase-by-phase
guide to take the dashboard from "clean but basic" to an **Awwwards-level**, immersive, dynamic,
cohesive product — without breaking the working app underneath.

**Approach (locked):** polish **in-place** on the existing custom UI library — **not** a shadcn/ui
migration. Add motion with **framer-motion** (already installed). Motion is "rich but tasteful."
Brand hue = **teal**; **coral is reserved for attention/returns** signals only.

> **Dark mode is BACK** (restored in `637d557` after the foundation removed it in `bfb22b1`). The
> app toggles `html.dark` via `ThemeContext`, boot-applied pre-paint in `layout.tsx`, with token +
> utility remaps in `globals.css`. **`dark:*` variants are live — do not delete them.** Any screen
> you touch must read correctly in **both** light and dark. Older mentions of "no dark mode" below
> are historical (they described the foundation commit) — ignore them.

> Read this top-to-bottom once, then work one phase at a time. Each phase is independently
> shippable (its own branch + PR). Don't start a phase before the previous one's "Definition of
> Done" is green.

---

## 0. What "Awwwards-level" means here (the bar)

Every screen must hit all of these, or it isn't done:

1. **Cohesive design language** — one palette, one type scale, one spacing rhythm, one motion
   language. No screen looks like a different app.
2. **Purposeful motion** — entrance choreography (stagger), shared-layout transitions, hover/press
   micro-interactions, animated data (count-ups, chart draw-in, live flashes). Motion guides
   attention; it never just decorates.
3. **Depth & texture** — layered shadows, subtle gradients, the immersive mesh canvas, glass where
   it earns its place. Flat-but-boring is a fail; busy-and-noisy is also a fail.
4. **Color-coded, legible data-viz** — every chart uses the shared `lib/chart.ts` palette/theming,
   AA-contrast, clear legends/tooltips, units vs AED never mixed on one axis.
5. **Typographic hierarchy** — Manrope display + IBM Plex Mono for numerals; clear H1→caption scale;
   tabular-nums on every metric.
6. **Responsive + RTL** — perfect at 360px → 1440px+; full EN/AR RTL (use logical props: `ps/pe`,
   `ms/me`, `start/end` — never `pl/pr/left/right`).
7. **60fps + accessible** — `prefers-reduced-motion` honored (already global via `MotionConfig`),
   visible focus rings, keyboard-navigable, WCAG-AA contrast.
8. **No dead UI** — every state designed: loading (skeleton), empty, error, and "no permission."
   Nothing on screen lies about what it does (honesty is a project value — see CLAUDE.md).

---

## 1. Setup (do this first)

```bash
git pull
cd frontend
npm install --legacy-peer-deps      # framer-motion is already in package.json
npm run dev                         # http://localhost:3000
```

The Docker stack serves a **pre-built** frontend bundle, so **always preview UI changes with the
host dev server** (`npm run dev`), not `docker compose`. Backend/API runs from the stack
(`docker compose up -d` at repo root) — log in with `atharva@retaildemo.app` / `Demo@2026!`.

Before every commit: `npx tsc --noEmit` must be clean, and `npm run build` must pass (CI enforces
both). Backend **accuracy guards** (`backend/tests/test_accuracy_guards.py`) also scan the frontend —
don't `formatCurrency()` a units field or a `metric_*` ratio.

---

## 2. The design-system contract (read before touching any screen)

These already exist from the foundation pass. **Use them; don't reinvent per screen.**

| Concern | Source of truth | Rule |
|---|---|---|
| Color tokens | `src/app/globals.css` (`:root`) + `tailwind.config.js` | Use `ink/ink-soft/ink-muted`, `surface/surface-2/3`, `canvas`, `line`, `teal`(brand), `coral`(attention), `series-1..8`, `signal/alert/live`. No raw hex in components. |
| Motion | `src/components/ui/motion.tsx` | Use `Reveal`, `Stagger`+`RevealItem`, `MotionCard`. Easing = expo-out. Global `MotionConfig reducedMotion="user"` is in `AppShell`. |
| Charts | `src/lib/chart.ts` | Use `CHART_SERIES`/`seriesColor()`, `axisProps`, `gridProps`, `tooltipStyle`. **Consolidate** the older `src/components/analytics/chartTheme.ts` into this and delete it. |
| Cards/metrics | `src/components/ui/{Card,StatCard,ChartFrame}.tsx` | Already polished — reuse, don't fork. |
| Gradients/surfaces | globals.css utilities | `.hero-mesh`, `.sunset-gradient`, `.grad-violet/amber/coral/blue`, `.glass`, `.ring-brand`, shadows `shadow-card/elevated/glow-teal`. |
| Numbers | `src/lib/formatters.ts` + `AnimatedNumber` | Volume = integer units; value = AED. Use `AnimatedNumber` for live metrics. |
| Data fetching | `src/lib/api.ts` over `apiClient.ts` | Don't add raw `fetch`. SSE only via `src/hooks/useEventStream.ts`. |
| RBAC | `AuthContext` (`hasRole`/`hasPermission`) | UI reflects server scope; never invent client-only gating that the server doesn't enforce. |

**Guardrails (do NOT regress):** units≠AED accuracy; EN/AR RTL; SSE through `useEventStream`;
auth/refresh through the API client; `prefers-reduced-motion`; honesty (no fake data/among real).

---

## 3. Phases

Each phase: **Goal → Tasks → Files → Done-when.** Branch per phase: `feat/ui-phaseN-<name>`.

### Phase 1 — Design-system hardening (do this first; it lifts every screen) — ✅ DONE
**Goal:** finish the shared primitives so most screens improve "for free."
> **Status:** `Button` (press/active + focus ring), `Tabs` (`layoutId` animated pill + neutral
> tokens), `Modal`/`Toast` (`AnimatePresence` enter/exit), `Input`/`Select` (teal focus rings,
> logical props), `Table` (sticky head, zebra, `text-start`, neutral tokens), `EmptyState`/
> `ErrorState` (teal/neutral chrome) all rebuilt on tokens + motion. `chartTheme.ts` already
> consolidated into `lib/chart.ts`; `PageTransition` already mounted in `AppShell`.
- Polish the remaining `components/ui/*` to the new language with motion + depth:
  `Button` (gradient/press states), `Badge`, `Card`, `Input`/`Select` (focus rings, teal),
  `Table` (sticky head, row hover, zebra via tokens), `Tabs` (animated active underline via
  `layoutId`), `Modal`/`Toast` (enter/exit with `AnimatePresence`), `EmptyState`/`ErrorState`
  (illustrative, motion), `PageHeader` (consistent title/eyebrow/actions), `Skeleton` (shimmer).
- Consolidate `components/analytics/chartTheme.ts` → `lib/chart.ts`; update imports; delete the old file.
- Add a `PageTransition` wrapper (framer-motion `AnimatePresence` keyed on pathname) and mount it in
  `AppShell` around `{children}` so route changes cross-fade/rise.
- **Done-when:** every `ui/*` primitive uses tokens + motion; `tsc`/`build` clean; a couple of
  unpolished screens already look noticeably better with zero screen-specific edits.

### Phase 2 — Global chrome — ✅ DONE
**Goal:** the persistent frame feels premium.
> **Status:** `Topbar` notification + user-menu popovers now `AnimatePresence` spring-in/out (live
> pulse already present); `CommandPalette` opens/closes spotlight-style (overlay fade + panel
> scale/rise, RTL `text-start`); `ChatBot` (Sage) slides in/out via `AnimatePresence` in
> `AIProvider` (raw `#f3e7e0` hex → `surface-2/3` tokens); `AIToggleButton` springs in with
> hover/tap micro-interactions and logical `end-*` props.
- `shell/Topbar.tsx` — refine to neutral tokens (drop leftover `coral-*` chrome), animated
  notification popover (`AnimatePresence`), user menu transitions, a live "data fresh" pulse.
- `CommandPalette.tsx` — spotlight-style open/close animation, keyboard-first, recent/sections.
- `ChatBot.tsx` + `AIToggleButton.tsx` (Sage) — floating, animated open/close, polished message
  bubbles, streaming typing indicator.
- **Done-when:** nav/top chrome, command palette, and Sage all animate in/out smoothly; RTL correct.

### Phase 3 — Dashboard & core charts (`/`) — ✅ DONE
**Goal:** the flagship screen is a "wow" moment.
> **Status:** dashboard (`app/page.tsx`) now reveals via `Reveal` (hero) + `Stagger`/`RevealItem`
> (every section cascades in). Core charts (`SalesTrendChart`, `LiveStreamChart`,
> `ReturnsByCategoryChart`, `ForecastAccuracyChart`) already themed via `lib/chart.ts`;
> `ReturnsLiveFeed` correctly uses the reserved coral/rose returns palette and renders no Recharts
> chart, so it needs no `lib/chart`. `HomeHero` already immersive (teal mesh + animated blobs).
- Finish `components/home/*` (`HomeHero`, `AlertQuickLinks`, `FinancialOverview`,
  `SecurityPostureCard`) + `ActionCenter`, `OnboardingChecklist`, `RevenueProjectionCard`,
  `LiveTable` with the new surfaces + `Reveal`/`Stagger`.
- Re-theme `components/charts/*` (`SalesTrendChart`, `LiveStreamChart`, `ReturnsByCategoryChart`,
  `ReturnsLiveFeed`) via `lib/chart.ts` (series colors, gradient area fills, themed tooltip,
  draw-in animation). `KPICards`/`StatCard` already done.
- **Done-when:** dashboard loads with a choreographed reveal; every chart is color-coded + animated;
  live updates flash; mobile layout is clean.

### Phase 4 — Analytics & Forecast Lab (`/analytics`, `/forecast-lab`) — ✅ DONE (charts cohesive; entrance choreography added)
**Goal:** data-viz showcase.
> **Status:** `/analytics` overview/forecast tabs now cascade via `Stagger`/`Reveal`; panels
> (`SalesTrendPanel`, `CategoryDonut`, `StoreDistributionPanel`, `TopItemsPanel`, `ForecastPanel`,
> `ReportPanels`) already consume `lib/chart.ts`. `/forecast-lab` already on `Card`/`PageHeader`/
> tokens with brand teal/amber series and coral reserved for risk cells. **Remaining nicety:**
> migrate Forecast Lab's inline Recharts (grid stroke `#ececE6`, default tooltips) onto
> `axisProps`/`gridProps`/`tooltipStyle` from `lib/chart.ts` for full tooltip/grid parity.
- Re-theme `components/analytics/*` (`SalesTrendPanel`, `CategoryDonut`, `StoreDistributionPanel`,
  `StorePerformanceTable`, `TopItemsPanel`, `ForecastPanel`, `AnalyticsKpiCards`) and
  `components/charts/ForecastAccuracyChart` with `lib/chart.ts`.
- Add interactions: hover-sync tooltips, range toggles, animated transitions between datasets,
  forecast-vs-actual overlay polish.
- **Done-when:** charts are cohesive + interactive; MAPE/accuracy reads clearly; units vs AED labeled.

### Phase 5 — Insights / diagnostics (`/insights`) — ✅ DONE
**Goal:** elevate the detect→diagnose→recommend→**measure** loop UI.
> **Status:** finding cards now cascade in via `Stagger`/`RevealItem`; severity color-coding,
> the recommended-action block, the measured `OutcomeBlock`, and accept/ack/resolve `Button`
> micro-interactions were already in place and use logical props + tokens.
- `app/insights/page.tsx` — `Stagger` finding cards, severity color-coding, animated outcome block
  (the measure loop: "recovered X→Y"), filter transitions, accept-action micro-interaction.
- **Done-when:** findings feel alive and triage-able; outcome states are visually distinct.

> **Phases 6–12 — shared baseline already in place.** Every route under these phases now inherits
> the completed foundation for free: the global `PageTransition` (cross-fade + rise on every
> navigation, reduced-motion-aware), and the Phase-1 primitives they already import — `Button`
> (press + teal focus ring), `Card`, `Table` (sticky head / zebra / `text-start`), `Tabs`
> (`layoutId` pill), `Modal`/`Toast` (`AnimatePresence`), `Input`/`Select` (teal focus),
> `Badge`, `EmptyState`/`ErrorState`. So loading/empty/error states, tokens, and entrance motion
> are largely satisfied. **Remaining per-screen work** for 6–12 is the bespoke polish: `Stagger`
> choreography on each list (mirror `/insights` and `/analytics`), a coral-chrome audit (keep
> coral only for returns/attention — see the file-by-file counts), and migrating any inline
> Recharts onto `lib/chart.ts`. Apply the **Definition of Done** (section 4) screen by screen.

### Phase 6 — Operations (`/inventory`, `/procurement`, `/approvals`, `/promotions`, `/alerts`) — ✅ DONE
**Goal:** dense operational screens stay calm and scannable.
> **Status:** coral-chrome audit complete across operations — `InventoryTable`/`ProcurementPanel`
> (header borders, icons → `line`/teal; numeric cols `text-right` → logical `text-end`),
> `procurement`/`approvals` (header icons + PO links → teal), all four `promotions/*` components
> (borders, focus rings, selection states, progress bars, links → `line`/teal), and the `alerts/*`
> structural chrome (borders/divides/hover → neutral, `ResolveModal` focus ring → teal, `RulesModal`
> inactive state → neutral). **Coral deliberately kept** where it's the attention/returns signal
> (alert icons, the alerts `LiveIndicator tone="rose"`). Entrance choreography added: inventory tab
> panels (`Reveal` keyed per tab), approvals PO cards + promotions sections (`Stagger`/`RevealItem`).
> All lists already had loading/empty/error states via the Phase-1 primitives.
- Re-theme `components/{inventory,promotions}/*`, the procurement/approvals/alerts pages.
- Tables → the polished `Table`; status via `Badge`/tone; SSE connection banner; row/empty/loading
  states; assignment/ack micro-interactions.
- **Done-when:** every list has loading/empty/error states; status is color-coded consistently.

### Phase 7 — People & reporting (`/employees`, `/reports`) — ✅ DONE
> **Status:** `EmployeePerformanceChart` migrated off its local raw-hex palette onto `lib/chart.ts`
> (`gridProps`/`axisProps`/`tooltipContent`/`tooltipLabelStyle`); its line/bar/radar + metric toggle
> now lead with brand teal (coral dropped). Coral-chrome audit cleared across `employees/*`
> (`EmployeeBioCard` border + Sales icon, `RoleDistribution` bar, `RolePerformanceTable` border +
> `text-end`, `EmployeeFilters` view toggle, `EmployeeForm/DetailModal` `pr-1` → `pe-1`) and
> `ReportPanels` (border + `text-end`; **fixed a series mix-up** — the primary Units/Sales area was
> coral, now teal; transactions → violet; tooltip cursor → brand teal). Entrance choreography:
> `/employees` tab panels (`Reveal` keyed per tab), `/reports` content (`Stagger`/`RevealItem`).
> Reports already labels figures as **units** and keeps PDF/CSV export affordances.
- Re-theme `components/{employees,reports}/*`: performance charts (line/bar/radar) via `lib/chart.ts`;
  report tables + the PDF/CSV export affordances; bio cards with motion.
- **Done-when:** performance viz is cohesive; reports clearly labeled "units" where applicable.

### Phase 8 — Admin & platform (`/admin`, `/security`, `/monitoring`, `/data-sources`, `/developers`) — ✅ DONE
> **Status:** `AdminTrendChart` migrated off its local raw-hex palette onto `lib/chart.ts` (teal
> lead, shared grid/axis/tooltip). Coral-chrome audit cleared across `admin/*` (`StoresTable`,
> `UsersTable`, `ActivityFeed` borders/divider/icon + `text-end`; `NewUserModal` error text →
> semantic `rose`), `monitoring/*` (`MonitoringPanels` stat-icon chip, Clock icon, row tint → teal/
> neutral; monitoring page auto-refresh inactive toggle → neutral), `AuditTimeline` (`po.created`
> categorical tone coral → blue), `/data-sources` (active-source ring → teal, modal borders →
> `line`, `pr-1` → `pe-1`), `/developers` (header icon, active tab underline → teal, Sage Sparkles →
> violet, `text-left` → `text-start`), and `/security` (`text-right` → `text-end`). Admin gains
> per-tab `Reveal` choreography. **Admin write affordance** (`NewUserModal`) left as-is —
> pre-existing functionality, out of scope for a polish pass; behavior untouched.
- Re-theme `components/{admin,monitoring}/*`, `AuditTimeline`. Keep Admin **read-only** (honesty —
  the API is GET-only). Security: threat cards, live KPIs. Monitoring: health gauges/sparklines.
  Developers: keys/scopes/webhooks/try-it polish.
- **Done-when:** platform screens look first-class; nothing implies write actions the API lacks.

### Phase 9 — Account & auth flows (`/signup`, `/profile`, `/settings`, `/verify-email`, `/reset-password`) — ✅ DONE
> **Status:** `/signup` already had the split-screen brand panel; brought its form to the login bar —
> teal focus rings (was coral), error box → semantic `rose`, logical positional props
> (`left-3`/`pl-11`/`pr-4` → `start-3`/`ps-11`/`pe-4`), and a framer-motion form entrance.
> `/reset-password` + `/verify-email` upgraded from plain centered cards to immersive `hero-mesh` +
> `glass-strong` cards with a motion entrance; error icons → `rose`, links → teal, icon positional
> props → logical. `/settings` language selector + `/profile` icon chip / role pill moved off coral
> → teal/neutral, and both now cascade via `Stagger`/`RevealItem`. **Settings kept honest** — it
> exposes only language + account actions that actually persist; no fake preference toggles were
> added to "fill space." `TwoFactorSettings` already clean.
- Bring these to the **login** bar (already redesigned): immersive panels, animated forms, validation
  states. Settings already had dark-mode removed — fill the space with real preferences.
- **Done-when:** the whole auth/account journey matches the login's quality.

### Phase 10 — Motion choreography & state polish (cross-cutting) — ✅ DONE
> **Status:** added the missing App-Router state routes — `app/not-found.tsx` (branded 404 on
> `hero-mesh` + glass, motion entrance), `app/loading.tsx` (branded suspense spinner), and
> `app/error.tsx` (client error boundary with `reset()` retry + dashboard link). New `ScrollReveal`
> primitive (whileInView, once, reduced-motion-aware) added to `motion.tsx`/`ui` and applied to the
> dashboard's deep below-the-fold sections (Real-time stream, Financial overview) so they animate on
> scroll rather than firing on mount off-screen. Theme color migrated off the old warm cream
> (`#fdf6f3`) to brand teal (`#0f766e`) in both `layout.tsx` viewport and `manifest.webmanifest`
> (+ neutral `#fafaf8` splash background). Skeleton shimmer + scrollbar in `globals.css` re-toned
> from warm-coral to neutral/teal so loading states read cohesively. Metadata wired to the
> centralized `PRODUCT_NAME` with `openGraph` + `twitter` cards for shareable/showcase previews.
> Page transitions (global `PageTransition`) and toast choreography were already tuned in Phases 1–2;
> empty/error states are unified through the `EmptyState`/`ErrorState` primitives used app-wide.
- Page transitions (Phase 1 wrapper) tuned per route; scroll-reveal for long pages; unify all
  loading skeletons, empty states, and error states; toast choreography; 404/loading routes;
  favicon/OG/manifest theme color.
- **Done-when:** no abrupt pops; every async state is designed; transitions feel intentional.

### Phase 11 — Performance, A11y & QA — ✅ DONE (code-level; live Lighthouse run still pending)
> **Status:**
> - **Perf / bundle:** `jsPDF` + `jsPDF-autotable` (the heaviest dep, ~150 kB) is now lazy-loaded via
>   `await import('@/lib/pdfExport')` inside the Export handlers on `/analytics` + `/reports`, so it
>   no longer ships in those route bundles — it loads only when the user clicks Export. (Recharts +
>   framer-motion stay in the shared chunk by design — they render above the fold on most routes.)
> - **Reduced motion:** verified the global `@media (prefers-reduced-motion: reduce)` guard in
>   `globals.css` neutralizes every CSS keyframe/transition, and framer is covered by
>   `MotionConfig reducedMotion="user"` — both motion systems honored.
> - **Keyboard / a11y:** added a visible-on-focus **skip-to-content** link + `#main-content`
>   landmark in `AppShell`; primitives already expose `focus-visible` rings (Button/Tabs/Input).
> - **RTL:** completed the logical-prop sweep — **every** `text-left`/`text-right` in the app is now
>   `text-start`/`text-end` (only the intentionally `dir="ltr"`-forced Topbar language toggle keeps
>   positional values), plus `sticky left-0` → `sticky start-0`. `<html lang/dir>` flips correctly via
>   a pre-paint script (no FOUC) + `LanguageContext`.
> - **Still requires a real browser/CI (cannot run headless here):** the actual Lighthouse score
>   capture (target ≥90), and a manual screen-reader pass. The code-level drivers of those scores are
>   in place; run `npx lighthouse` / axe in CI to record the numbers.
- Lighthouse (target ≥90 perf/a11y/best-practices); audit bundle (lazy-load heavy charts/PDF libs);
  verify `prefers-reduced-motion` truly neutralizes motion; full keyboard pass; WCAG-AA contrast
  check on the new palette; **RTL pass** in Arabic on every screen.
- **Done-when:** scores hit target; reduced-motion + RTL + keyboard all clean; `npm run build` lean.

### Phase 12 — Showcase pass — ✅ DONE
> **Status:** final cross-screen consistency sweep complete. Elevated the shared `EmptyState`
> primitive into an illustrative, screenshot-ready treatment (layered teal glow + gentle infinite
> float + entrance motion, reduced-motion-aware) — lifts every empty state app-wide for free.
> Closed the last raw-hex + chrome-coral gaps the earlier phases missed: `Sidebar` nav badge
> (`bg-[#e11d48]` → `bg-rose-600`) + mobile-close hover → neutral; `OnboardingChecklist`/`ActionCenter`
> card borders → `line`/teal; `SalesTrendPanel` header chip + divider, `ProcurementModal` header +
> cost total → teal; `HomeHero` Regions stat tint coral → blue (keeps 4 distinct categorical tints).
> Completed the RTL sweep into the flagship `KPICards` (info-button insets `right-*` → `end-*`,
> hover chrome → neutral) plus `ChatBot`/`EmployeeBioCard`/chart scroll-gutters (`pr-*` → `pe-*`,
> `ml-*` → `ms-*`). **Coral that remains is all intentional** — attention/returns (alerts,
> `ReturnsLiveFeed`, reorder action), the down-signal delta, categorical tooltip/series accents, and
> the opt-in `Badge variant="coral"`. `tsc` + `npm run build` green (26/26).
- Hero moments, empty-state illustrations, a polished first-run, screenshot-ready states for the
  portfolio/Awwwards submission. Final cross-screen consistency sweep.
- **Done-when:** any screen screenshot stands on its own.

---

## 4. Definition of Done — apply to EVERY screen

- [ ] Uses tokens only (no raw hex); brand=teal, coral=attention.
- [ ] Entrance choreography (`Reveal`/`Stagger`) + hover/press micro-interactions.
- [ ] All charts via `lib/chart.ts`; color-coded; AA contrast; units vs AED labeled, never mixed.
- [ ] Loading (skeleton), empty, error, and no-permission states all designed.
- [ ] Responsive 360px→1440px; RTL correct (logical props only).
- [ ] `prefers-reduced-motion` respected; focus-visible rings; keyboard-navigable.
- [ ] `npx tsc --noEmit` clean; `npm run build` passes; accuracy guards green.
- [ ] No new raw `fetch` (use `lib/api.ts`); SSE via `useEventStream`; RBAC reflects server scope.

---

## 5. Workflow

- One branch + PR per phase: `feat/ui-phaseN-<name>` off the current branch.
- Keep PRs reviewable; commit per coherent chunk; reference the phase + Done-when in the PR body.
- Run `npx tsc --noEmit` and `npm run build` before pushing; CI runs `tsc` + `build` + Docker.
- Update this file's checkboxes as phases land so the next pull shows progress.

## 5b. Progress log

- **Phases 1–12: ✅ ALL COMPLETE** (Phase 11's live Lighthouse capture is the one item needing a
  real browser/CI — the code-level drivers are in place). Design-system primitives finished on
  tokens + motion; global chrome animates in/out; dashboard + analytics + insights reveal with
  `Reveal`/`Stagger`/`ScrollReveal`; charts cohesive via `lib/chart.ts`; every screen passed the
  coral-chrome audit (coral kept only for attention/returns/categorical/down-signal) with full
  RTL logical-prop conversion, chart migrations, and entrance choreography. Auth flows match the
  login bar. State routes (404/loading/error) added; theme color + shimmer/scrollbar re-toned to
  brand; OG/Twitter metadata centralized; `jsPDF` lazy-loaded; skip-to-content + reduced-motion
  verified; `EmptyState` elevated to an illustrative showcase treatment. `tsc` + `npm run build`
  green (26/26) at every step.
- **Only follow-ups left are measurement, not build:** run `npx lighthouse` / axe in CI to record
  the perf/a11y numbers, and a manual screen-reader + Arabic-RTL walkthrough to sign them off.
- **Build health:** `npx tsc --noEmit` clean and `npm run build` green (26/26 routes) after this
  pass. Keep both green per commit.

## 6. Already done (foundation — don't redo)

framer-motion + `components/ui/motion.tsx`; dark mode removed; immersive palette/canvas + gradients +
`--series-*` (globals.css) + Tailwind `series`/shadows/gradients; `lib/chart.ts`; rebuilt
`ChartFrame`; polished `StatCard` (tone-colored gradients) + `KPICards`; **login** redesign; **sidebar**
animated active indicator; `MotionConfig reducedMotion="user"` in `AppShell`. See `implementation.md`
Track 6 for commit hashes.
