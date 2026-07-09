/**
 * @deprecated Import from `@/lib/nav` (or `./registry` / `./types`) instead.
 *
 * The IA data moved to `registry.ts` and the types to `types.ts` as part of the
 * nav module split. This shim keeps existing `./domains` imports working during
 * the incremental migration; it will be removed once no imports reference it.
 */
export * from './registry';
export type {
  DomainKey, DomainDef, RoutePlacement, FlatNavItem, DomainSection, DomainGroup, Breadcrumb,
} from './types';
