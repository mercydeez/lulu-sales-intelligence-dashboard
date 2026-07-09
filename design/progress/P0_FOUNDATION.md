# Phase P0 — Foundation · Progress Report

**Branch:** `feature/design-system-v3`
**Status:** code-complete · `tsc --noEmit` clean · `next build` green (45/45 pages)
**Architecture:** backend **frozen** — IA/domain grouping is done by a client-side nav adapter.

## Goal (from IMPLEMENTATION_PLAN.md)
Introduce the foundation the rest of the redesign rides on, with **zero page rewrites**:
tokens, the layered domain shell, the frontend nav adapter, and the missing state components —
while every route keeps loading and behavior (API/RBAC/SSE/routing) is unchanged.

## What shipped

### 1. Frontend navigation adapter (the architectural core)
The six-domain Information Architecture now lives entirely on the client. The backend still decides
**which** pages a role may see; the adapter decides **how** they are grouped.

```
/api/experience (authorization)  →  lib/nav adapter (IA)  →  domain + context rails
```

- `lib/nav/domains.ts` — the six domains + the route→domain/section map (design/INFORMATION_ARCHITECTURE §8), pure data, plus `domainForPath()` (longest-prefix match for detail routes).
- `lib/nav/adapter.ts` — `buildDomainNav()` groups the authorized flat nav into domains (dropping empty domains) + `activeDomainKey()`. Pure, JSX-free, unit-testable. **Never makes an authorization decision** — an item appears only if it was already authorized upstream.

### 2. Layered domain shell (replaces the single flat sidebar)
- `components/shell/DomainRail.tsx` — primary rail, six domains only, role-filtered, icon-first, animated active indicator.
- `components/shell/ContextRail.tsx` — secondary rail, the active domain's pages grouped into labeled sections (e.g. Admin → Organization / Billing & plans / Trust & governance), with live badges.
- `components/shell/MobileNav.tsx` — the two rails collapse into one grouped drawer on small screens.
- `components/shell/useNavBadges.ts` — the four live badge polls (alerts/approvals/decisions/security) extracted verbatim from the old sidebar; **same endpoints, same behavior**.
- `components/shell/AppShell.tsx` — recomposed to DomainRail + ContextRail + (existing) Topbar, driven by the adapter, **with a safety fallback to the old `Sidebar`** if the adapter ever yields no domains. Loading skeletons for both rails.

The **Topbar (utility bar) was left untouched** — it already provides language, scope chip, notifications+SSE, and the account menu; rewriting it would add risk with no P0 gain.

### 3. Design-system-v3 tokens (additive)
- `app/globals.css` — a new `:root` block with the named tokens from design/DESIGN_SYSTEM §3 / VISUAL_LANGUAGE §2 (`--canvas`, `--surface-elevated/-tint`, `--brand-*`, semantic `--success/--warning/--danger/--info/--ai-*`, `--focus-ring`, `--overlay-scrim`, `--live-pulse`). New variable names → **no collision** with existing `--c-*`/`--accent-*` utilities; components consume them as they migrate.

### 4. State grammar (completes the set)
- `components/ui/NoPermissionState.tsx` — respects the role boundary without leaking hidden values.
- `components/ui/StatusBanner.tsx` — info/success/warning/degraded/error, icon-paired (never color-alone).
- (Empty/Error/Loading/ConnectionBanner already existed.)

## Files modified / added / deprecated

**Added (11):**
- `frontend/src/lib/nav/domains.ts`
- `frontend/src/lib/nav/adapter.ts`
- `frontend/src/components/shell/DomainRail.tsx`
- `frontend/src/components/shell/ContextRail.tsx`
- `frontend/src/components/shell/MobileNav.tsx`
- `frontend/src/components/shell/useNavBadges.ts`
- `frontend/src/components/ui/NoPermissionState.tsx`
- `frontend/src/components/ui/StatusBanner.tsx`
- `design/IMPLEMENTATION_PLAN.md` *(prior turn)*
- `design/progress/P0_FOUNDATION.md` *(this file)*
- `design/*` spec docs *(committed as the branch base)*

**Modified (4):**
- `frontend/src/components/shell/AppShell.tsx` — recomposed to the layered shell + fallback.
- `frontend/src/app/globals.css` — additive token block.
- `frontend/src/locales/nav.ts` — `domain.*` + `nav.preferences` keys (EN + AR).
- `frontend/src/components/ui/index.ts` — export the two new state components.

**Components added:** DomainRail · ContextRail · MobileNav · NoPermissionState · StatusBanner (+ `useNavBadges` hook, nav adapter).

**Deprecated (retained, not deleted — removed at P7):**
- `components/shell/Sidebar.tsx` — now only the safety fallback; superseded by the two rails.
- (`Topbar.tsx` stays; it becomes the "utility bar" conceptually, unchanged in P0.)

## Contracts preserved (verification)
- **API contracts:** no endpoint added or changed; badge hook uses the exact prior endpoints; backend `role_experience.py` untouched.
- **RBAC:** authorization still comes from `/api/experience` (or the built-in nav's `roles`/`permission` filter); the adapter only groups authorized items — it can never reveal an unauthorized page.
- **SSE:** untouched (Topbar's `/stream/alerts` handler unchanged).
- **Routing:** every route still resolves; `/` still redirects to `/today`; no URL changed.
- **TypeScript:** `tsc --noEmit` exit 0.
- **Build:** `next build` succeeds, 45/45 static pages, `/today` present.

## Not done in P0 (by design — later phases)
Page templates, workflow-object unification, AI-component consolidation, Tailwind color-wiring of the
new tokens, and the Sidebar/Topbar retirement. P0 is foundation only.

## Reviewer checklist
- [ ] Log in as **store manager / regional manager / executive** → domain rail shows only that role's domains; context rail lists the right pages; badges appear.
- [ ] Deep route (e.g. `/procurement/po/3`) keeps **Operations** active.
- [ ] Every existing page still renders unchanged inside the new shell.
- [ ] Mobile drawer groups by domain.
- [ ] RTL (Arabic) — rails mirror correctly (logical `start/end` used throughout).

**Awaiting review before P1 (Home).**
