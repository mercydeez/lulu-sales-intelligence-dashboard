/**
 * Domain taxonomy — the frontend-owned Information Architecture.
 *
 * ARCHITECTURE (backend-frozen): the backend `/api/experience` decides WHICH
 * pages a role may see (authorization / feature availability). This file decides
 * HOW those pages are grouped and ordered into the six product domains
 * (presentation / hierarchy). The backend never changes for IA reasons; all
 * grouping happens here, on the client.
 *
 *   FastAPI → Experience Config (availability) → this taxonomy (IA) → Enterprise UI
 *
 * Source of truth for the route→domain mapping: design/INFORMATION_ARCHITECTURE.md §8.
 * Pure data only — no JSX, no React (icons are resolved in the rail components).
 */

export type DomainKey =
  | 'home' | 'workflows' | 'operations' | 'intelligence' | 'platform' | 'admin';

export interface DomainDef {
  key: DomainKey;
  /** i18n key; label is the English fallback. */
  tKey: string;
  label: string;
  /** lucide icon name, resolved to a component in DomainRail. */
  icon: string;
  order: number;
}

/** The six domains, in rail order. Max six (IA §9). */
export const DOMAINS: DomainDef[] = [
  { key: 'home',         tKey: 'domain.home',         label: 'Home',         icon: 'Home',        order: 1 },
  { key: 'workflows',    tKey: 'domain.workflows',    label: 'Workflows',    icon: 'Inbox',       order: 2 },
  { key: 'operations',   tKey: 'domain.operations',   label: 'Operations',   icon: 'Package',     order: 3 },
  { key: 'intelligence', tKey: 'domain.intelligence', label: 'Intelligence', icon: 'BarChart3',   order: 4 },
  { key: 'platform',     tKey: 'domain.platform',     label: 'Platform',     icon: 'Database',    order: 5 },
  { key: 'admin',        tKey: 'domain.admin',        label: 'Admin',        icon: 'Shield',      order: 6 },
];

export interface RoutePlacement {
  domain: DomainKey;
  /** optional labeled section within the domain's context rail (IA §5.2 grouping). */
  section?: string;
  order: number;
}

/**
 * Route → domain placement. Every authenticated business route maps here.
 * Utility/account routes (`/profile`, `/settings`) are intentionally absent —
 * they live in the account menu, not the domain rails (IA §3.3, PRINCIPLES §13).
 */
export const ROUTE_MAP: Record<string, RoutePlacement> = {
  // Home
  '/':              { domain: 'home', order: 0 },   // transitional → redirects to /today
  '/today':         { domain: 'home', order: 1 },
  '/briefing':      { domain: 'home', order: 2 },
  '/copilot':       { domain: 'home', order: 3 },
  // Workflows
  '/decisions':     { domain: 'workflows', order: 1 },
  '/insights':      { domain: 'workflows', order: 2 },
  '/alerts':        { domain: 'workflows', order: 3 },
  '/approvals':     { domain: 'workflows', order: 4 },
  '/action-drafts': { domain: 'workflows', order: 5 },
  // Operations
  '/inventory':     { domain: 'operations', order: 1 },
  '/procurement':   { domain: 'operations', order: 2 },
  '/promotions':    { domain: 'operations', order: 3 },
  '/employees':     { domain: 'operations', order: 4 },
  // Intelligence
  '/analytics':     { domain: 'intelligence', order: 1 },
  '/forecast-lab':  { domain: 'intelligence', order: 2 },
  '/reports':       { domain: 'intelligence', order: 3 },
  '/value':         { domain: 'intelligence', order: 4 },
  '/uae-insights':  { domain: 'intelligence', order: 5 },
  // Platform
  '/data-sources':  { domain: 'platform', order: 1 },
  '/imports':       { domain: 'platform', order: 2 },
  '/developers':    { domain: 'platform', order: 3 },
  '/monitoring':    { domain: 'platform', order: 4 },
  '/status':        { domain: 'platform', order: 5 },
  // Admin (grouped into sections)
  '/admin':          { domain: 'admin', section: 'Organization', order: 1 },
  '/admin/tenants':  { domain: 'admin', section: 'Organization', order: 2 },
  '/settings/company': { domain: 'admin', section: 'Organization', order: 3 },
  '/settings/team':  { domain: 'admin', section: 'Organization', order: 4 },
  '/settings/billing': { domain: 'admin', section: 'Billing & plans', order: 5 },
  '/pricing':        { domain: 'admin', section: 'Billing & plans', order: 6 },
  '/outcome-pricing': { domain: 'admin', section: 'Billing & plans', order: 7 },
  '/security':       { domain: 'admin', section: 'Trust & governance', order: 8 },
  '/audit':          { domain: 'admin', section: 'Trust & governance', order: 9 },
  '/trust':          { domain: 'admin', section: 'Trust & governance', order: 10 },
};

/**
 * Resolve a pathname to its domain via longest-prefix match, so detail routes
 * (e.g. `/procurement/po/3`) still light up their parent domain.
 */
export function domainForPath(pathname: string): DomainKey | null {
  if (ROUTE_MAP[pathname]) return ROUTE_MAP[pathname].domain;
  let best: { href: string; domain: DomainKey } | null = null;
  for (const [href, place] of Object.entries(ROUTE_MAP)) {
    if (href === '/') continue; // never prefix-match root
    if (pathname === href || pathname.startsWith(href + '/')) {
      if (!best || href.length > best.href.length) best = { href, domain: place.domain };
    }
  }
  return best?.domain ?? null;
}

export function placementForHref(href: string): RoutePlacement | undefined {
  return ROUTE_MAP[href];
}
