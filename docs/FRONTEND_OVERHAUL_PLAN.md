# Frontend Overhaul — Basic → Awwwards-Level (Contributor Playbook)

**Audience:** the contributor picking this up after `git pull`. This is the phase-by-phase
guide to take the dashboard from "clean but basic" to an **Awwwards-level**, immersive, dynamic,
cohesive product — without breaking the working app underneath.

**Approach (locked):** polish **in-place** on the existing custom UI library — **not** a shadcn/ui
migration. Add motion with **framer-motion** (already installed). **No dark mode** (removed).
Motion is "rich but tasteful." Brand hue = **teal**; **coral is reserved for attention/returns**
signals only.

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

### Phase 1 — Design-system hardening (do this first; it lifts every screen)
**Goal:** finish the shared primitives so most screens improve "for free."
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

### Phase 2 — Global chrome
**Goal:** the persistent frame feels premium.
- `shell/Topbar.tsx` — refine to neutral tokens (drop leftover `coral-*` chrome), animated
  notification popover (`AnimatePresence`), user menu transitions, a live "data fresh" pulse.
- `CommandPalette.tsx` — spotlight-style open/close animation, keyboard-first, recent/sections.
- `ChatBot.tsx` + `AIToggleButton.tsx` (Sage) — floating, animated open/close, polished message
  bubbles, streaming typing indicator.
- **Done-when:** nav/top chrome, command palette, and Sage all animate in/out smoothly; RTL correct.

### Phase 3 — Dashboard & core charts (`/`)
**Goal:** the flagship screen is a "wow" moment.
- Finish `components/home/*` (`HomeHero`, `AlertQuickLinks`, `FinancialOverview`,
  `SecurityPostureCard`) + `ActionCenter`, `OnboardingChecklist`, `RevenueProjectionCard`,
  `LiveTable` with the new surfaces + `Reveal`/`Stagger`.
- Re-theme `components/charts/*` (`SalesTrendChart`, `LiveStreamChart`, `ReturnsByCategoryChart`,
  `ReturnsLiveFeed`) via `lib/chart.ts` (series colors, gradient area fills, themed tooltip,
  draw-in animation). `KPICards`/`StatCard` already done.
- **Done-when:** dashboard loads with a choreographed reveal; every chart is color-coded + animated;
  live updates flash; mobile layout is clean.

### Phase 4 — Analytics & Forecast Lab (`/analytics`, `/forecast-lab`)
**Goal:** data-viz showcase.
- Re-theme `components/analytics/*` (`SalesTrendPanel`, `CategoryDonut`, `StoreDistributionPanel`,
  `StorePerformanceTable`, `TopItemsPanel`, `ForecastPanel`, `AnalyticsKpiCards`) and
  `components/charts/ForecastAccuracyChart` with `lib/chart.ts`.
- Add interactions: hover-sync tooltips, range toggles, animated transitions between datasets,
  forecast-vs-actual overlay polish.
- **Done-when:** charts are cohesive + interactive; MAPE/accuracy reads clearly; units vs AED labeled.

### Phase 5 — Insights / diagnostics (`/insights`)
**Goal:** elevate the detect→diagnose→recommend→**measure** loop UI.
- `app/insights/page.tsx` — `Stagger` finding cards, severity color-coding, animated outcome block
  (the measure loop: "recovered X→Y"), filter transitions, accept-action micro-interaction.
- **Done-when:** findings feel alive and triage-able; outcome states are visually distinct.

### Phase 6 — Operations (`/inventory`, `/procurement`, `/approvals`, `/promotions`, `/alerts`)
**Goal:** dense operational screens stay calm and scannable.
- Re-theme `components/{inventory,promotions}/*`, the procurement/approvals/alerts pages.
- Tables → the polished `Table`; status via `Badge`/tone; SSE connection banner; row/empty/loading
  states; assignment/ack micro-interactions.
- **Done-when:** every list has loading/empty/error states; status is color-coded consistently.

### Phase 7 — People & reporting (`/employees`, `/reports`)
- Re-theme `components/{employees,reports}/*`: performance charts (line/bar/radar) via `lib/chart.ts`;
  report tables + the PDF/CSV export affordances; bio cards with motion.
- **Done-when:** performance viz is cohesive; reports clearly labeled "units" where applicable.

### Phase 8 — Admin & platform (`/admin`, `/security`, `/monitoring`, `/data-sources`, `/developers`)
- Re-theme `components/{admin,monitoring}/*`, `AuditTimeline`. Keep Admin **read-only** (honesty —
  the API is GET-only). Security: threat cards, live KPIs. Monitoring: health gauges/sparklines.
  Developers: keys/scopes/webhooks/try-it polish.
- **Done-when:** platform screens look first-class; nothing implies write actions the API lacks.

### Phase 9 — Account & auth flows (`/signup`, `/profile`, `/settings`, `/verify-email`, `/reset-password`)
- Bring these to the **login** bar (already redesigned): immersive panels, animated forms, validation
  states. Settings already had dark-mode removed — fill the space with real preferences.
- **Done-when:** the whole auth/account journey matches the login's quality.

### Phase 10 — Motion choreography & state polish (cross-cutting)
- Page transitions (Phase 1 wrapper) tuned per route; scroll-reveal for long pages; unify all
  loading skeletons, empty states, and error states; toast choreography; 404/loading routes;
  favicon/OG/manifest theme color.
- **Done-when:** no abrupt pops; every async state is designed; transitions feel intentional.

### Phase 11 — Performance, A11y & QA
- Lighthouse (target ≥90 perf/a11y/best-practices); audit bundle (lazy-load heavy charts/PDF libs);
  verify `prefers-reduced-motion` truly neutralizes motion; full keyboard pass; WCAG-AA contrast
  check on the new palette; **RTL pass** in Arabic on every screen.
- **Done-when:** scores hit target; reduced-motion + RTL + keyboard all clean; `npm run build` lean.

### Phase 12 — Showcase pass
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

## 6. Already done (foundation — don't redo)

framer-motion + `components/ui/motion.tsx`; dark mode removed; immersive palette/canvas + gradients +
`--series-*` (globals.css) + Tailwind `series`/shadows/gradients; `lib/chart.ts`; rebuilt
`ChartFrame`; polished `StatCard` (tone-colored gradients) + `KPICards`; **login** redesign; **sidebar**
animated active indicator; `MotionConfig reducedMotion="user"` in `AppShell`. See `implementation.md`
Track 6 for commit hashes.
