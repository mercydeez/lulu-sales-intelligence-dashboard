# P1 — Home (progress report)

Branch: `feature/design-system-v3`, merged into
`prototype-evolution-accuracy-bullmq`. Phase: Executive Briefing / Home (all three
Home surfaces: `/today`, `/briefing`, `/copilot`).

## Status: foundation shipped; `/briefing` adopted; `/today` + `/copilot` next

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

### ▶️ Next — remaining Home surfaces (focused step)
- **`/today`** — the `verdict` zone adopts `HeroVerdict` + `useBriefing` and the
  `kpis` zone adopts `MetricStrip`, editing the registered widgets (not the page
  shell). Kept registry-safe. Plus **B04** (experience-fallback state).
- **`/copilot`** — wrap in `HomeTemplate`; feed widgets + ask box keep working, framed
  by the shared hero/answer grammar.

Rationale for splitting the phase here: the three pages are 1,024 lines total and
two are already polished; a rushed same-session rewrite risked regression. The
shared system is the high-value, low-risk core and is best reviewed before the
page refactors land on top of it.

## Files
**Added:** `components/ui/{HeroVerdict,MetricStrip}.tsx`, `components/ai/{AiAnswerBlock,index}.ts(x)`,
`components/templates/{HomeTemplate,index}.ts(x)`, `design/progress/P1_HOME.md`.
**Modified:** `components/ui/index.ts` (exports), `design/IMPLEMENTATION_PLAN.md` (status).

## Guardrails met
`tsc` ✅ · `next build` ✅ (46/46; `/today`, `/briefing`, `/copilot` compile) · routes,
RBAC, SSE, API contracts preserved · backend frozen · no page rewritten for structure
alone.
