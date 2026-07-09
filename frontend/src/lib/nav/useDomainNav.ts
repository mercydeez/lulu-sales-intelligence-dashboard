'use client';

/**
 * useDomainNav — the one hook the shell uses to render the domain rails.
 *
 * Composes the pieces: reads the authorized flat nav (server manifest, else the
 * built-in nav filtered by RBAC via `permissions`), groups it into domains via
 * the `adapter`, and resolves the active domain for the current path. Keeps the
 * shell components thin and free of nav-building logic.
 */
import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useExperience } from '@/contexts/ExperienceContext';
import { navItems, NAV_ICONS } from '@/config/nav';
import { buildDomainNav, activeDomainKey } from './adapter';
import { canAccessNavItem } from './permissions';
import type { DomainGroup, DomainKey, FlatNavItem } from './types';

export interface DomainNavState {
  pathname: string;
  flatNav: FlatNavItem[];
  groups: DomainGroup[];
  activeKey: DomainKey | null;
  activeGroup: DomainGroup | null;
}

export function useDomainNav(): DomainNavState {
  const pathname = usePathname() ?? '/';
  const { hasRole, hasPermission } = useAuth();
  const { config } = useExperience();

  const flatNav = useMemo<FlatNavItem[]>(() => {
    if (config?.nav) {
      return config.nav.map((m) => ({
        href: m.href,
        label: m.label,
        tKey: m.tKey,
        icon: NAV_ICONS[m.icon] ?? NAV_ICONS.LayoutDashboard,
      }));
    }
    return navItems
      .filter((item) => canAccessNavItem(item, { hasRole, hasPermission }))
      .map((item) => ({ href: item.href, label: item.label, tKey: item.tKey, icon: item.icon }));
  }, [config?.nav, hasRole, hasPermission]);

  const groups = useMemo(() => buildDomainNav(flatNav), [flatNav]);
  const activeKey = useMemo(() => activeDomainKey(pathname, groups), [pathname, groups]);
  const activeGroup = useMemo(
    () => groups.find((g) => g.key === activeKey) ?? null,
    [groups, activeKey],
  );

  return { pathname, flatNav, groups, activeKey, activeGroup };
}
