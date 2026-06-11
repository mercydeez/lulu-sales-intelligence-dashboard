# UI/UX Redesign Plan — "Operations Console", not SaaS Template

> Current state: hand-rolled dark Tailwind (slate-900 + cyan), emoji-as-iconography mixed with Lucide, ten mega page components with inline styling, no design tokens beyond an unused blue palette in `tailwind.config.js`. It works, but it reads "hackathon."
> Target: the calm, dense, trustworthy feel of professional ops software (think Bloomberg terminal discipline + Linear's restraint), tuned for **retail floor reality**: glanceable numbers, alarm states you can trust, Arabic-ready.

---

## 1. Visual direction

**Concept name: "Trading floor for groceries."** A hypermarket ops console is closer to a market-data terminal than to a marketing SaaS dashboard. Design implications:

- **Data is the decoration.** No gradient hero cards, no glassmorphism. Numbers, deltas, and sparklines carry the visual interest.
- **Calm surface, loud exceptions.** Neutral surfaces 95% of the screen; saturated color is *reserved for meaning* (alerts, deltas, live status). Today's UI uses cyan everywhere, so nothing stands out.
- **Light theme default, dark theme kept.** Retail back offices are bright; light UIs photograph better in portfolios. Dark mode remains (current users of the codebase already like it) via CSS variables.
- **Retail texture in the details:** SKU-style mono labels (`#A-1042 · Dairy`), expiry chips shaped like date tags, store names with emirate badges — not stock-photo produce.

## 2. Design tokens (Tailwind config, CSS variables)

| Token | Value | Use |
|---|---|---|
| `surface-0/1/2` | warm grays (#FAFAF8 → #EFEFEA) / dark equivalents | page, card, inset levels |
| `ink-1/2/3` | #1A1D21 / #4B5258 / #8A9097 | text hierarchy |
| `brand` | deep teal-green `#0F766E` family | primary actions, active nav — market-fresh without copying any retailer's trade dress |
| `accent-live` | electric green `#16A34A` + pulse | live/streaming indicators only |
| `signal-up / signal-down` | green / red (with shape redundancy ▲▼ for color-blind users) | deltas |
| `alert-critical/warn/info` | red / amber / blue | alert system only — never decorative |
| Typography | **Inter** (UI) + **IBM Plex Sans Arabic** (AR) + tabular-nums everywhere numbers appear | one variable font each; both free (Google Fonts, self-hosted) |
| Numerals | `font-variant-numeric: tabular-nums` globally on KPIs/tables | columns stop wiggling on live updates |
| Spacing | strict 4/8px scale; cards `p-4`, sections `gap-6` | current spacing is ad-hoc |
| Radius | 8px cards, 6px controls, 999px chips | consistent corners |
| Elevation | borders > shadows (1px `surface-2` borders; single subtle shadow tier for overlays) | denser, more "instrument" |

All tokens as CSS variables → theming and RTL stay cheap.

## 3. Component system (`src/components/ui/`)

Build ~14 primitives once, delete hundreds of inline-class repetitions:

`Button` (primary/secondary/ghost/destructive, loading state) · `Card` (header/body/footer slots) · `StatCard` (value, delta with ▲▼, sparkline slot, live-pulse variant) · `DataTable` (sticky header, tabular-nums, row states incl. "return" rows, skeleton rows, empty slot) · `Badge/Chip` (role, region, alert severity, expiry) · `LiveIndicator` (the one allowed pulsing dot) · `Modal/Drawer` (replace `NewEmployeeModal`/`NewPromotionModal` shells) · `Toast` (success/error/reconnect) · `Tabs` · `Select/DateRangePicker` · `EmptyState` (illustration + action) · `SkeletonBlock` · `PageHeader` (title, persona scope chip, actions) · `ChartFrame` (title, period selector, export, loading/empty/error states wrapped around Recharts).

Charts: keep Recharts; standardize a single palette (brand + 4 categorical hues), kill per-chart random colors; axis/grid styling defined once in `ChartFrame`.

## 4. Layout & information architecture

- **Sidebar nav** (collapsible, icons + labels) replaces the crowded top navbar; top bar reduces to: global store/region scope switcher, live status, alerts bell, user menu. (Navbar.tsx currently does nav + alerts + SSE + user menu in 20 KB.)
- **Role-shaped home pages** (the demo moment):
  - *Store manager*: today at my store — hourly sales sparkline, live feed, expiry queue, open alerts as tasks.
  - *Regional manager*: branch league table, region KPIs, transfer suggestions, promo performance.
  - *Super admin*: network map of stores by emirate, cross-region comparison, system health strip.
- **Page template**: `PageHeader` → KPI strip (4–5 `StatCard`) → main grid (2/3 chart + 1/3 live panel) → detail table. Every page follows it; users learn the layout once.
- **Density toggle** later (comfortable/compact) — tables default compact.

## 5. Signature screens

1. **Live Operations (home)** — the hero. Big "network pulse" number (AED/hr, units/hr), live transaction tape (returns render as red right-aligned negatives, like a trading blotter), market-sentiment dial fed by the generator's sentiment value (currently generated but never visualized — free wow).
2. **Inventory & Expiry Risk** — risk-sorted queue: chips for "expires in 2d", days-of-cover bars, markdown suggestion buttons, batch drawer.
3. **Forecast vs Actual** — confidence band chart with honest MAPE badge, per store/item; "why this forecast" popover (method explanation in plain words).
4. **Alerts → Tasks** — alert list with acknowledge/assign, SLA timers, resolution notes; proves "operations," not "dashboard."

## 6. Customer-facing experience

Out of MVP scope (ops platform — see PRODUCT_STRATEGY). The "customer" of this UI is staff. If a pitch needs a consumer artifact later, a single read-only "store status" page (opening hours, promotions) can be added; design tokens already support it.

## 7. States: empty, loading, error, degraded

| State | Rule |
|---|---|
| Loading | Skeletons shaped like the final content (StatCard/DataTable have built-in skeletons). Never spinners on full pages; never layout shift. |
| Empty | `EmptyState` with one action ("No promotions running — Create one"). Currently most pages render blank zeros. |
| Error | Inline retry card per panel, not page-wide failure; toast for action failures. |
| Degraded (SSE lost) | Amber "Reconnecting — data may be stale (last update 12:04:31)" banner; LiveIndicator goes amber. Currently streams fail silently or loop reconnecting. |
| Backend down | KPI endpoints must stop returning fake zeros (GAP M1) so the UI can tell the truth: "Metrics unavailable" panel. |

## 8. Motion & microinteractions

- New live-feed rows: 150 ms slide+fade, max ~4 rows/s (batch beyond that — current implementation can thrash).
- KPI value changes: number ticker (animate digits, 300 ms) + 600 ms delta flash (green/red), exactly like market terminals.
- The *only* infinite animation: LiveIndicator pulse. Everything else animates on change only.
- `prefers-reduced-motion`: all of the above off.
- Page transitions: none (ops tools should feel instant), just skeletons.

## 9. Mobile responsiveness

Priority: **store manager on the floor with a phone.**
- KPI strip → horizontal snap-scroll; tables → card lists with primary value prominent; sidebar → bottom tab bar (Home, Inventory, Alerts, More).
- Alerts/tasks fully usable on mobile (acknowledge from the aisle); analytics pages can stay desktop-optimized (state it, don't fake it).

## 10. Accessibility (WCAG 2.1 AA target)

- Contrast-checked token pairs (current slate-400-on-slate-900 body text fails AA).
- Color never sole signal: deltas get ▲▼, alert severities get icons, live rows get a left border + label.
- Full keyboard pass: visible focus rings (brand outline), modal focus traps, skip-to-content.
- `aria-live="polite"` for KPI updates; charts get hidden data-table alternatives (`<summary>` + DataTable reuse).
- Form labels and error text tied via `aria-describedby` (login page currently relies on placeholder text).

## 11. Arabic / RTL (differentiator — phase 3.5)

- `next-intl` with `en`/`ar` dictionaries; `dir="rtl"` on `<html>`; Tailwind logical properties (`ps-*/pe-*` instead of `pl-*/pr-*`) adopted during the component build so RTL is nearly free.
- Numerals stay Western digits (UAE business convention); charts stay LTR internally with translated labels (standard practice).
- Scope: nav, home, inventory, alerts — fully translated; deeper analytics may remain EN in MVP.

## 12. What makes it feel premium (summary checklist)

- One accent color used sparingly; warm neutral surfaces; 1px borders over shadows
- Tabular numerals + aligned decimal columns everywhere
- Skeletons, empty states, and degraded-data banners designed — no blank panels, no fake zeros
- Market-terminal microinteractions (ticking numbers, delta flashes) tied to *real* SSE events
- SKU/mono typographic details; emirate badges; expiry date-tag chips (retail-specific texture)
- Zero emoji in UI chrome (move transaction-type emoji to subtle icons/labels)
- A visible "SYNTHETIC DEMO DATA" badge in the footer — honesty styled as a feature

## 13. Execution order (feeds IMPLEMENTATION_ROADMAP Phase 3)

1. Tokens + Tailwind config + fonts + light/dark variables
2. Primitives (`ui/`) with Storybook-style demo page at `/dev/components` (dev-only)
3. App shell: sidebar, top bar, role-shaped routing
4. Home/Live Operations rebuild → then Inventory/Expiry → Alerts/Tasks → Analytics/Forecast
5. Mobile pass → accessibility pass → AR/RTL pass
