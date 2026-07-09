/**
 * Navigation types — shared across the nav modules (registry, adapter,
 * permissions, breadcrumbs, favorites). No logic, no React.
 */
import type { ReactNode } from 'react';

export type DomainKey =
  | 'home' | 'workflows' | 'operations' | 'intelligence' | 'platform' | 'admin';

export interface DomainDef {
  key: DomainKey;
  /** i18n key; `label` is the English fallback. */
  tKey: string;
  label: string;
  /** lucide icon name, resolved in the rail component. */
  icon: string;
  order: number;
}

export interface RoutePlacement {
  domain: DomainKey;
  /** optional labeled section within the domain's context rail. */
  section?: string;
  order: number;
}

/** A single authorized nav destination, normalized from either nav source. */
export interface FlatNavItem {
  href: string;
  label: string;
  tKey?: string;
  icon: ReactNode;
}

export interface DomainSection {
  label: string;
  pages: FlatNavItem[];
}

export interface DomainGroup extends DomainDef {
  /** flat, ordered — used when the domain has no labeled sections. */
  pages: FlatNavItem[];
  /** present when the domain groups pages under labels (e.g. Admin). */
  sections: DomainSection[];
}

export interface Breadcrumb {
  label: string;
  tKey?: string;
  href: string;
}
