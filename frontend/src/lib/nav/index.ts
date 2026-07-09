/**
 * Navigation module — public API barrel.
 *
 * The nav layer is split by concern:
 *   types.ts        — shared types (DomainKey, DomainGroup, FlatNavItem, …)
 *   registry.ts     — the IA data: DOMAINS + ROUTE_MAP + lookups
 *   adapter.ts      — group authorized flat nav → domain hierarchy
 *   permissions.ts  — client RBAC filter for the built-in fallback nav
 *   breadcrumbs.ts  — Domain → Page trail from a pathname
 *   favorites.ts    — client-only pinned routes (localStorage)
 *   useDomainNav.ts — the hook the shell renders from
 *
 * Prefer importing from `@/lib/nav` over the individual files.
 */
export * from './types';
export * from './registry';
export * from './adapter';
export * from './permissions';
export * from './breadcrumbs';
export * from './favorites';
export * from './useDomainNav';
