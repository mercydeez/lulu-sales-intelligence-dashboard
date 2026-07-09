# Architecture

How Retail IQ is put together, and the rules that keep it coherent as the
experience redesign (`design/`) rolls out phase by phase.

## 1. System shape

```
Browser ──HTTPS──▶ Next.js 14 (App Router, TS, Tailwind)  ─┐
   ▲   ◀──SSE────  /stream/* (sse-starlette)               │  typed fetch (JWT)
   │                                                        ▼
   └───────────────────────  FastAPI (async SQLAlchemy 2 + asyncpg)
                                      │        │        │
                              PostgreSQL 15  Redis 7   BullMQ worker (Node)
                              (RLS, tenant)  (cache,   (detect→diagnose→
                                              pub/sub,  recommend→measure)
                                              SSE bus)
```

Frontend and backend are separate deploys; the browser talks to FastAPI over a
typed fetch facade (JWT bearer/cookie) and receives live updates over SSE only
(no WebSockets/presence — PRD §2.2).

## 2. The governing principle — the backend is frozen for IA

The redesign draws a hard line between **authorization** and **presentation**:

```
FastAPI ──▶ Experience Config ──▶ Frontend Adapter ──▶ Enterprise UI
(auth,       (what a role may       (how those pages     (rails, templates,
 RBAC,        see: availability)     group into the 6     components)
 scoping)                            domains: the IA)
```

| Concern | Owner | Where |
|---|---|---|
| Authentication, RBAC, tenant scoping, RLS | **Backend** | `backend/app/routes/auth.py`, RLS migrations |
| Experience config (persona, nav manifest, homepage zones, KPIs, capabilities) | **Backend** | `backend/app/services/role_experience.py` → `GET /api/experience` |
| Feature availability (which pages a role sees) | **Backend** | the nav manifest inside the experience config |
| Information architecture (domain grouping, hierarchy, ordering) | **Frontend** | `frontend/src/lib/nav/` |
| Navigation shell, presentation, states | **Frontend** | `frontend/src/components/shell`, `ui`, templates |

**Rule:** `role_experience.py` is not modified for IA reasons. The client transforms
the flat, authorized nav into the six-domain hierarchy. This lets the UI evolve
without touching the authorization surface.

## 3. The six domains (IA)

`Home · Workflows · Operations · Intelligence · Platform · Admin` (design/INFORMATION_ARCHITECTURE.md).
A role only sees a domain if the backend authorized ≥1 page in it — availability
is the backend's call, grouping is the frontend's.

## 4. Frontend layers (dependencies flow downward)

```
Route pages (app/**/page.tsx)         ── each wrapped by one page template
        ▼
Shell (components/shell)              ── AppShell → DomainRail · ContextRail · Topbar(utility)
        ▼   reads useDomainNav()
Templates + Zones                     ── Home/Workflow/Operations/Intelligence/PlatformAdmin (P1+)
        ▼
Domain blocks                         ── workflow/* (P2) · ai/* (P1) · feature components
        ▼
Composite UI + State                  ── PageHeader, HeroVerdict, EntityTable, StatusBanner, …
        ▼
Primitives (components/ui)            ── Button, Card, Badge, Table, Skeleton, ChartFrame, motion
        ▼
Foundation                            ── design tokens (globals.css), Tailwind, fonts
```

Cross-cutting providers feed every layer: `AuthContext`, `ExperienceContext`
(server config), `LanguageContext` (RTL), `ToastProvider`, `AIProvider`.
Full graph: **`COMPONENT_GRAPH.md`**.

## 5. The navigation layer (`lib/nav/`)

Split by concern so pages stay thin and the IA is testable:

| Module | Responsibility |
|---|---|
| `types.ts` | shared nav types (`DomainKey`, `DomainGroup`, `FlatNavItem`, `Breadcrumb`) |
| `registry.ts` | the IA data — `DOMAINS`, `ROUTE_MAP`, `domainForPath`, `placementForHref` |
| `adapter.ts` | `buildDomainNav()` groups authorized flat nav → domains; `activeDomainKey()` |
| `permissions.ts` | `canAccessNavItem()` — client RBAC filter for the built-in fallback nav |
| `breadcrumbs.ts` | `breadcrumbsForPath()` — Domain → Page trail |
| `favorites.ts` | client-only pinned routes (localStorage) + `useFavorites()` |
| `useDomainNav.ts` | the hook the shell renders from (composes the above) |
| `index.ts` | barrel — import from `@/lib/nav` |

`domains.ts` remains as a deprecated re-export shim during migration.
**Authorization is never decided here** — an item only appears if the backend
already authorized it (server manifest, or the RBAC-filtered built-in nav).

## 6. Data & realtime

- **REST:** pages call the typed facade `lib/api.ts` (in-memory TTL cache) over
  `lib/apiClient.ts` (auth, refresh-on-401). New feature calls add typed helpers;
  pages avoid raw `fetch`.
- **SSE:** live updates via the ref-counted `hooks/useEventStream.ts` (one
  connection per endpoint). SSE is the only realtime mechanism.
- **AI (Sage):** grounded, RBAC-scoped; briefing/decisions/findings/copilot/chat
  are one product layer (design/AI_EXPERIENCE.md), consolidating onto shared AI
  blocks in later phases.

## 7. Feature-first modules (`features/`)

Feature-specific data hooks and components live under `features/<feature>/`
(`hooks/`, `components/`, `api.ts`). Adopted **incrementally as phases touch a
feature** — not migrated wholesale. Convention: `frontend/src/features/README.md`.

## 8. Contracts every change must preserve

- **API contracts** — consume existing endpoints; add typed helpers, don't change shapes.
- **RBAC** — role scope stays backend-enforced; nav hiding is UX on top of real authz.
- **SSE** — keep the ref-counted stream hook; no WebSocket/presence implications.
- **Routing** — URLs are stable (IA migration preserves routes); `/` → `/today`.
- **Units vs AED** — volume in units, value in AED, never mixed (repo-wide invariant).

## 9. Redesign delivery

Phased, strangler-style, always shippable: **P0 Foundation → P1 Home → P2
Workflows → P3 Operations → P4 Platform → P5 Admin → P6 Intelligence → P7
Accessibility/RTL/Perf**. One phase at a time; each compiles, passes `tsc`,
preserves the §8 contracts, and ships behind the existing shell fallback.
Plan + status: `design/IMPLEMENTATION_PLAN.md`; per-phase reports: `design/progress/`.

## 10. Directory map

```
backend/app/            FastAPI: routes/ services/ models/ middleware
  services/role_experience.py   ← the experience config engine (frozen for IA)
frontend/src/
  app/**/page.tsx        routes (43) — thin, wrapped by templates
  components/
    shell/               AppShell, DomainRail, ContextRail, MobileNav, Topbar, useNavBadges
    ui/                  primitives + state components (Empty/Error/NoPermission/StatusBanner)
    workflow/  ai/  templates/   (added as P1–P2 land)
    <domain>/            existing feature-internal components
  lib/nav/               the navigation layer (§5)
  lib/                   api, apiClient, chart, brand, cn, formatters
  contexts/              Auth, Experience, Language, Theme
  features/              feature-first hooks/components (§7)
  locales/               per-domain i18n (en/ar)
design/                  redesign source of truth + IMPLEMENTATION_PLAN + progress/
```
