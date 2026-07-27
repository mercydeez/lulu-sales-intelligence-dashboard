/**
 * Navigation adapter — transforms the backend's flat, role-authorized nav into
 * the six-domain hierarchy entirely on the client.
 *
 * Input:  a flat list of pages the backend authorized for this role (from the
 *         `/api/experience` nav manifest, or the built-in nav filtered by RBAC).
 * Output: domain groups (+ optional labeled sections) ready for the domain +
 *         context rails.
 *
 * Pure logic — no React, no data fetching. Icons are carried opaquely as
 * `ReactNode` so this stays JSX-free and unit-testable. Authorization is NEVER
 * decided here: an item only appears if it was already in the authorized input.
 */
import { DOMAINS, ROUTE_MAP, placementForHref } from './registry';
import type { DomainKey, DomainGroup, DomainSection, FlatNavItem } from './types';

// Re-export the types adapter consumers relied on, so `./adapter` imports keep
// working while call sites migrate to importing types from `@/lib/nav`.
export type { FlatNavItem, DomainSection, DomainGroup } from './types';

/**
 * Group authorized flat nav items into domains. Domains with no authorized pages
 * are dropped, so a store manager sees fewer domains than an admin — exactly the
 * backend's availability decision, presented as IA.
 */
export function buildDomainNav(items: FlatNavItem[]): DomainGroup[] {
  const byDomain = new Map<DomainKey, FlatNavItem[]>();
  const seen = new Set<string>();

  for (const item of items) {
    if (seen.has(item.href)) continue;   // de-dupe (e.g. `/` and `/today` both Home)
    const place = placementForHref(item.href);
    if (!place) continue;                // unmapped href → not shown in rails (safety)
    seen.add(item.href);
    const list = byDomain.get(place.domain) ?? [];
    list.push(item);
    byDomain.set(place.domain, list);
  }

  const groups: DomainGroup[] = [];
  for (const def of [...DOMAINS].sort((a, b) => a.order - b.order)) {
    const pages = byDomain.get(def.key);
    if (!pages || pages.length === 0) continue;
    pages.sort((a, b) => (placementForHref(a.href)?.order ?? 99) - (placementForHref(b.href)?.order ?? 99));

    // Build labeled sections only when the domain's routes declare them.
    const sectionOrder: string[] = [];
    const sectionMap = new Map<string, FlatNavItem[]>();
    let anySection = false;
    for (const p of pages) {
      const label = placementForHref(p.href)?.section;
      if (label) {
        anySection = true;
        if (!sectionMap.has(label)) { sectionMap.set(label, []); sectionOrder.push(label); }
        sectionMap.get(label)!.push(p);
      } else {
        const label2 = '';
        if (!sectionMap.has(label2)) { sectionMap.set(label2, []); sectionOrder.push(label2); }
        sectionMap.get(label2)!.push(p);
      }
    }
    const sections: DomainSection[] = anySection
      ? sectionOrder.filter((l) => l).map((l) => ({ label: l, pages: sectionMap.get(l)! }))
      : [];

    groups.push({ ...def, pages, sections });
  }
  return groups;
}

/** The domain group that owns the current path, for rail highlighting. */
export function activeDomainKey(pathname: string, groups: DomainGroup[]): DomainKey | null {
  // exact/prefix via ROUTE_MAP first (handles detail routes)
  const direct = ROUTE_MAP[pathname]?.domain;
  if (direct && groups.some((g) => g.key === direct)) return direct;
  let best: { href: string; key: DomainKey } | null = null;
  for (const g of groups) {
    for (const p of g.pages) {
      if (p.href === '/') continue;
      if (pathname === p.href || pathname.startsWith(p.href + '/')) {
        if (!best || p.href.length > best.href.length) best = { href: p.href, key: g.key };
      }
    }
  }
  return best?.key ?? groups[0]?.key ?? null;
}
