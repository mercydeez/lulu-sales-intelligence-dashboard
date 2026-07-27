# P1 — Home (progress report)

Branch: `feature/design-system-v3`, merged into
`prototype-evolution-accuracy-bullmq`. Phase: Executive Briefing / Home (all three
Home surfaces: `/today`, `/briefing`, `/copilot`).

## Status: ✅ done — all three Home surfaces adopted

P1 delivers "one Home system." That system is a small set of **shared components**
every Home surface composes. This commit ships those components (additive,
low-risk, verified); the page rewiring onto them follows as a focused step so the
polished existing surfaces (esp. the 496-line `/briefing`) are refactored, not
regressed.

### ✅ Done — the reusable Home foundation
| Component | File | Role (design ref) |
|---|---|---|
| `HeroVerdict` | `components/ui/HeroVerdict.tsx` | focal summary module for Today/Briefing/Copilot/Status (COMPONENT_LIBRARY §4.3) |
| `MetricStrip` | `components/ui/MetricStrip.tsx` | 3–6 aligned, tabular metrics beneath the hero (§4.4, DESIGN_SYSTEM §8.3) |
| `AiAnswerBlock` | `components/ai/AiAnswerBlock.tsx` | canonical Sage answer anatomy: verdict → evidence → confidence → scope → next step (AI_EXPERIENCE §4) |
| `HomeTemplate` | `components/templates/HomeTemplate.tsx` | hero → metrics → priority modules → supporting module (DESIGN_SYSTEM §6.1) |
| `useBriefing` | `features/home/hooks/useBriefing.ts` | Home data hook (shipped P0.5); pages consume it instead of inline fetch |

Barrels: `@/components/ai`, `@/components/templates`, and `HeroVerdict`/`MetricStrip`
via `@/components/ui`.

Design compliance baked in: AI answers lead with the verdict; violet = AI
provenance (never brand); confidence/tone never color-only; tabular numerals;
white-on-mesh text handled so the hero stays legible; sentence case; RTL-safe.

### ✅ Done — `/briefing` adopted onto the foundation (reference implementation)
- **`useBriefing`** is now the page's single data source (inline fetch + local
  interfaces deleted; hook types enriched to the full API shape — Season, Forecast,
  Watch, Leak, `generated_at`, `kind`, `category`).
- **Hero → `HeroVerdict`** — narration, typewriter, mood pill and the primary CTA
  compose into the shared slots (`greeting`/`verdict`/`chips`/`aside`); `onMesh` is
  now exported for slot composers.
- **Numbers → `MetricStrip`** — revenue (trend + `AnimatedNumber`), volume (units),
  forecast, at-risk (amber) as one aligned strip; `MetricStrip` now sizes its
  large-screen columns from the item count. Units and AED stay on separate items.
- **Sage's recommendation → `AiAnswerBlock`** — the focal decision keeps its urgency
  card, but the AI suggestion inside it now uses the canonical anatomy
  (verdict → scope → next step) with violet Sage provenance.
- **Page shell → `HomeTemplate`** — hero → metrics → priority modules → footer, in
  every state. **B06** (loading skeleton) and **B07** (empty, now on `HeroVerdict`)
  standardized.

### ✅ Done — `/today` adopted
- **`VerdictZone`** now renders through `HeroVerdict` instead of hand-rolled
  `hero-mesh` markup. Data source unchanged (`useBriefing` from
  `lib/queries/briefing`) — only presentation moved onto the shared component.
  Registry-safe: still registered under `verdict`/`briefing_hero`, page shell
  (the zone-map loop reading `config.homepage?.zones ?? config.zones`) untouched.
- **`KpiZone`** now renders through `MetricStrip` instead of a hand-rolled grid;
  `formatKpi` still supplies formatted text, `MetricStrip` now owns the
  trend icon/color instead of `KpiZone` inlining one.
- **B04** (experience-fallback state) added: when the config loads but resolves
  to zero homepage zones (missing/degraded manifest), the page now renders
  `EmptyState` with a refresh action instead of a silent blank page.

### ✅ Done — `/copilot` adopted
- Page now wraps in `HomeTemplate` (same `min-h-screen`/`max-w-3xl` container it
  already used, now shared).
- Persona header rebuilt on `HeroVerdict`; the `ai_context` scope/focus pills use
  the `chips` slot and the embedded ask box + suggested prompts use the `cta`
  slot (a full-width block), so they still render inside the same hero card.
- Loading/error states now match the `/briefing` reference pattern exactly
  (`HomeTemplate` wrapping `SkeletonCard`s / `ErrorState`).
- Proactive feed (non-verdict zones) unchanged: same registry, same filter,
  same `Stagger`/`RevealItem` reveal.

All three Home surfaces (`/today`, `/briefing`, `/copilot`) now compose the same
`HeroVerdict` → `MetricStrip`/feed → `AiAnswerBlock` anatomy. P1 exit criteria met:
one AI grammar across all three; B04 added; B06/B07 already covered by `/briefing`.

## Files
**Added:** `components/ui/{HeroVerdict,MetricStrip}.tsx`, `components/ai/{AiAnswerBlock,index}.ts(x)`,
`components/templates/{HomeTemplate,index}.ts(x)`, `design/progress/P1_HOME.md`.
**Modified:** `components/ui/index.ts` (exports), `app/today/page.tsx`,
`app/copilot/page.tsx`, `design/IMPLEMENTATION_PLAN.md` (status).

## Guardrails met
`tsc --noEmit` ✅ · `next build` ✅ (51/51; `/today`, `/briefing`, `/copilot` compile) ·
routes, RBAC, SSE, API contracts preserved · backend frozen · no page rewritten for
structure alone.
