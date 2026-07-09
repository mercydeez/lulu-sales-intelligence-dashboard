/**
 * Breadcrumbs — derive a Domain → Page trail from a pathname, using the registry.
 * Pure; no React. Consumed by page headers as areas migrate to the new templates.
 */
import { DOMAINS, ROUTE_MAP, domainForPath } from './registry';
import type { Breadcrumb } from './types';

/**
 * Build the breadcrumb trail for a path, e.g.:
 *   /procurement/po/3 → [Operations, Procurement, Purchase order]
 *   /today            → [Home, Today]
 * Labels come from the registry (domain) and a small page-label lookup; unknown
 * leaf segments are title-cased so detail routes still read cleanly.
 */
export function breadcrumbsForPath(pathname: string, pageLabel?: string): Breadcrumb[] {
  const domainKey = domainForPath(pathname);
  const trail: Breadcrumb[] = [];
  if (!domainKey) return trail;

  const domain = DOMAINS.find((d) => d.key === domainKey);
  if (domain) trail.push({ label: domain.label, tKey: domain.tKey, href: firstRouteInDomain(domainKey) });

  // The matched page (longest ROUTE_MAP prefix of the path).
  const pageHref = longestRoutePrefix(pathname);
  if (pageHref && pageHref !== '/') {
    trail.push({ label: pageLabel ?? titleize(pageHref.split('/').filter(Boolean).slice(-1)[0]), href: pageHref });
  }

  // A deeper detail segment (e.g. /procurement/po/3 → "3" / a provided label).
  if (pageHref && pathname !== pageHref) {
    const leaf = pathname.slice(pageHref.length).split('/').filter(Boolean).pop();
    if (leaf) trail.push({ label: pageLabel && pathname !== pageHref ? pageLabel : titleize(leaf), href: pathname });
  }
  return trail;
}

function longestRoutePrefix(pathname: string): string | null {
  if (ROUTE_MAP[pathname]) return pathname;
  let best: string | null = null;
  for (const href of Object.keys(ROUTE_MAP)) {
    if (href === '/') continue;
    if (pathname === href || pathname.startsWith(href + '/')) {
      if (!best || href.length > best.length) best = href;
    }
  }
  return best;
}

function firstRouteInDomain(domainKey: string): string {
  const entries = Object.entries(ROUTE_MAP)
    .filter(([href, p]) => p.domain === domainKey && href !== '/')
    .sort(([, a], [, b]) => a.order - b.order);
  return entries[0]?.[0] ?? '/today';
}

function titleize(segment: string): string {
  return segment.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
