# P1 — Home (progress report)

Branch: `feature/design-system-v3`. Phase: Executive Briefing / Home (all three
Home surfaces: `/today`, `/briefing`, `/copilot`).

## Status: foundation shipped; page adoption is the next step

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

### ▶️ Next — adopt the foundation on the three surfaces (focused step)
- **`/briefing`** — refactor the hero into `HeroVerdict`, sections onto `AiAnswerBlock`,
  wrap in `HomeTemplate`, consume `useBriefing` (dedupe the fetch). The page already
  embodies this anatomy; this makes it use the shared components literally.
- **`/today`** — the zones resolve through the shared widget registry
  (`components/copilot/registry`); the `verdict` zone adopts `HeroVerdict` + `useBriefing`
  and the `kpis` zone adopts `MetricStrip`, editing the registered widgets (not the
  page shell). Kept registry-safe.
- **`/copilot`** — wrap in `HomeTemplate`; feed widgets + ask box keep working, framed
  by the shared hero/answer grammar.
- **States (B04/B06/B07):** Today experience-fallback, Briefing loading skeleton,
  Briefing empty — standardized on the shared state components.

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
