/**
 * Navigation registry — the frontend-owned Information Architecture data.
 *
 * ARCHITECTURE (backend-frozen): the backend `/api/experience` decides WHICH
 * pages a role may see (authorization / feature availability). This registry
 * decides HOW those pages group and order into the six product domains
 * (presentation / hierarchy). The backend never changes for IA reasons.
 *
 *   FastAPI → Experience Config (availability) → this registry (IA) → Enterprise UI
 *
 * Source of truth for the route→domain mapping: design/INFORMATION_ARCHITECTURE.md §8.
 * Pure data + lookups only — no JSX, no React. Types live in ./types.
 */
import type { DomainDef, DomainKey, RoutePlacement } from './types';

/** The six domains, in rail order. Max six (IA §9). */
export const DOMAINS: DomainDef[] = [
  { key: 'home',         tKey: 'domain.home',         label: 'Home',         icon: 'Home',       order: 1 },
  { key: 'workflows',    tKey: 'domain.workflows',    label: 'Workflows',    icon: 'Inbox',      order: 2 },
  { key: 'operations',   tKey: 'domain.operations',   label: 'Operations',   icon: 'Package',    order: 3 },
  { key: 'intelligence', tKey: 'domain.intelligence', label: 'Intelligence', icon: 'BarChart3',  order: 4 },
  { key: 'platform',     tKey: 'domain.platform',     label: 'Platform',     icon: 'Database',   order: 5 },
  { key: 'admin',        tKey: 'domain.admin',        label: 'Admin',        icon: 'Shield',     order: 6 },
];

/**
 * Route → domain placement. Every authenticated business route maps here.
 * Utility/account routes (`/profile`, `/settings`) are intentionally absent —
 * they live in the account menu, not the domain rails (IA §3.3, PRINCIPLES §13).
 */
export const ROUTE_MAP: Record<string, RoutePlacement> = {
  // Home
  '/':               { domain: 'home', order: 0 },   // transitional → redirects to /today
  '/today':          { domain: 'home', order: 1 },
  '/briefing':       { domain: 'home', order: 2 },
  '/role-workbench': { domain: 'home', order: 3 },
  '/copilot':        { domain: 'home', order: 4 },
  // Workflows
  '/decisions':      { domain: 'workflows', order: 1 },
  '/insights':       { domain: 'workflows', order: 2 },
  '/alerts':         { domain: 'workflows', order: 3 },
  '/approvals':      { domain: 'workflows', order: 4 },
  '/action-drafts':  { domain: 'workflows', order: 5 },
  // Operations
  '/inventory':      { domain: 'operations', order: 1 },
  '/procurement':    { domain: 'operations', order: 2 },
  '/promotions':     { domain: 'operations', order: 3 },
  // Flywheel — retention decisioning. Operations, beside promotions: it is
  // the retention counterpart to the promotion catalogue, and an operator
  // reasoning about one is usually reasoning about the other.
  '/flywheel':       { domain: 'operations', order: 4 },
  // Horizon 1 surfaces sit immediately after Flywheel so the proof lives next
  // to the thing it proves. Fractional orders avoid renumbering the domain.
  '/flywheel/incrementality': { domain: 'operations', order: 4.1 },
  '/flywheel/holdout':        { domain: 'operations', order: 4.2 },
  '/flywheel/governance':     { domain: 'operations', order: 4.3 },
  '/flywheel/models/shadow':  { domain: 'operations', order: 4.4 },
  '/flywheel/trade':          { domain: 'operations', order: 4.5 },
  '/flywheel/cannibalization':{ domain: 'operations', order: 4.6 },
  '/retention':      { domain: 'operations', order: 5 },
  '/employees':      { domain: 'operations', order: 6 },
  // Intelligence
  '/analytics':      { domain: 'intelligence', order: 1 },
  '/forecast-lab':   { domain: 'intelligence', order: 2 },
  '/reports':        { domain: 'intelligence', order: 3 },
  '/value':          { domain: 'intelligence', order: 4 },
  '/uae-insights':   { domain: 'intelligence', order: 5 },
  // Platform
  '/data-sources':   { domain: 'platform', order: 1 },
  '/imports':        { domain: 'platform', order: 2 },
  '/developers':     { domain: 'platform', order: 3 },
  '/monitoring':     { domain: 'platform', order: 4 },
  '/status':         { domain: 'platform', order: 5 },
  // Admin (grouped into sections)
  '/admin':            { domain: 'admin', section: 'Organization', order: 1 },
  '/admin/tenants':    { domain: 'admin', section: 'Organization', order: 2 },
  '/settings/company': { domain: 'admin', section: 'Organization', order: 3 },
  '/settings/team':    { domain: 'admin', section: 'Organization', order: 4 },
  '/settings/billing': { domain: 'admin', section: 'Billing & plans', order: 5 },
  '/pricing':          { domain: 'admin', section: 'Billing & plans', order: 6 },
  '/outcome-pricing':  { domain: 'admin', section: 'Billing & plans', order: 7 },
  '/security':         { domain: 'admin', section: 'Trust & governance', order: 8 },
  '/audit':            { domain: 'admin', section: 'Trust & governance', order: 9 },
  '/trust':            { domain: 'admin', section: 'Trust & governance', order: 10 },
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

export function domainDef(key: DomainKey): DomainDef | undefined {
  return DOMAINS.find((d) => d.key === key);
}
