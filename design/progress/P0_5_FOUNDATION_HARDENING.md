# P0.5 — Foundation hardening (progress report)

Branch: `feature/design-system-v3`. Requested before P1: architecture docs, nav
module split, and beginning the feature-folder / hook pattern — applied
incrementally, **without rewriting working functionality**.

## Outcome
- ✅ `ARCHITECTURE.md` + `COMPONENT_GRAPH.md` created (repo root).
- ✅ `lib/nav/` split into concern-focused modules (registry, permissions, breadcrumbs, favorites, types) + a composing hook; shell logic moved out of `AppShell`.
- ✅ Feature-folder convention established with a real seed hook (`features/home/hooks/useBriefing.ts`) for P1.
- ✅ `tsc --noEmit` clean · `next build` green (46/46 routes, incl. `/today`, `/role-workbench`).
- ✅ Behavior preserved: same shell, same routes, same RBAC, same SSE, same API contracts.

## What changed and why

### 1. Navigation split (`frontend/src/lib/nav/`)
The nav layer was two files (`domains.ts`, `adapter.ts`); it is now split by concern
so pages stay thin and the IA is testable:

| Module | Responsibility | Status |
|---|---|---|
| `types.ts` | shared nav types | already committed (72aaa33) |
| `registry.ts` | IA data — `DOMAINS`, `ROUTE_MAP`, lookups | **new** (data moved out of `domains.ts`) |
| `adapter.ts` | `buildDomainNav` / `activeDomainKey` | edited — now imports types + registry |
| `permissions.ts` | `canAccessNavItem` — client RBAC filter | **new** (extracted from `AppShell`) |
| `breadcrumbs.ts` | `breadcrumbsForPath` Domain→Page trail | **new** (pure; for P1 headers) |
| `favorites.ts` | pinned routes (localStorage) + `useFavorites` | **new** (forward-looking) |
| `useDomainNav.ts` | the hook the shell renders from | **new** (moved logic out of `AppShell`) |
| `index.ts` | barrel — import from `@/lib/nav` | **new** |
| `domains.ts` | deprecated re-export shim | kept for back-compat |

`AppShell` dropped its inline `useAuthorizedFlatNav` and now calls `useDomainNav()`.
Rail components import types from the `@/lib/nav` barrel.

### 2. Architecture docs (root)
- `ARCHITECTURE.md` — system shape, the backend-freeze principle
  (`FastAPI → Experience Config → Frontend Adapter → UI`), the frontend layers, the
  nav layer, data/SSE/AI, the feature-folder convention, and the contracts every
  change must preserve.
- `COMPONENT_GRAPH.md` — the **current** component dependency graph (providers, shell
  subtree, nav layer, primitives/state, and where P1–P7 nodes land).

### 3. Feature-folder pattern (begun, not forced)
- `features/README.md` — the convention (`features/<feature>/{hooks,components,api}`;
  hooks own data and return `{ data, loading, error, reload }`).
- `features/home/hooks/useBriefing.ts` — a real, typed seed hook wrapping `/api/briefing`.
  **Not wired yet** — P1 consumes it when it rebuilds Home, honoring "migrate as areas
  are touched." No existing page was rewritten for structure alone.

## Files
**Added:** `ARCHITECTURE.md`, `COMPONENT_GRAPH.md`,
`frontend/src/lib/nav/{registry,permissions,breadcrumbs,favorites,useDomainNav,index}.ts`,
`frontend/src/features/README.md`, `frontend/src/features/home/hooks/useBriefing.ts`,
`design/progress/P0_5_FOUNDATION_HARDENING.md`.
**Modified:** `frontend/src/lib/nav/{adapter,domains}.ts`,
`frontend/src/components/shell/{AppShell,DomainRail,ContextRail,MobileNav}.tsx`,
`design/IMPLEMENTATION_PLAN.md`.
**Deprecated:** `frontend/src/lib/nav/domains.ts` (now a re-export shim; removed once no
imports reference it).

## Not touched (respecting scope)
- Backend frozen — `role_experience.py` unchanged by this work.
- The separate, pre-existing `role-workbench` WIP (its page + `config/nav.tsx` +
  `role_experience.py` edit + one i18n key) is left uncommitted and unentangled; its
  `/role-workbench` route mapping is preserved in `registry.ts`.
- No page rewrites, no component-family changes — those come with their phases.

## Guardrails met
`tsc` ✅ · `next build` ✅ (46/46) · routes/RBAC/SSE/API contracts preserved · no large rewrite.

**Next:** P1 — Executive Briefing / Home.
