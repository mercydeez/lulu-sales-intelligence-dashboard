'use client';

import { ReactNode, useMemo, useState } from 'react';
import { MotionConfig } from 'framer-motion';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useExperience } from '@/contexts/ExperienceContext';
import { Topbar } from './Topbar';
import { Sidebar } from './Sidebar';
import { DomainRail } from './DomainRail';
import { ContextRail } from './ContextRail';
import { MobileNav } from './MobileNav';
import { useNavBadges } from './useNavBadges';
import VerifyEmailBanner from './VerifyEmailBanner';
import CommandPalette from '@/components/CommandPalette';
import { PageTransition } from '@/components/ui';
import { navItems, NAV_ICONS, type NavItem } from '@/config/nav';
import { buildDomainNav, activeDomainKey, type FlatNavItem } from '@/lib/nav/adapter';

/**
 * Build the flat, role-authorized nav list. Source of authorization:
 *  - the server experience manifest (`config.nav`) when present, or
 *  - the built-in nav, filtered by the same RBAC the old sidebar used.
 * Grouping into domains happens in the adapter — never here.
 */
function useAuthorizedFlatNav(): FlatNavItem[] {
  const { hasRole, hasPermission } = useAuth();
  const { config } = useExperience();
  return useMemo(() => {
    if (config?.nav) {
      return config.nav.map((m) => ({
        href: m.href,
        label: m.label,
        tKey: m.tKey,
        icon: NAV_ICONS[m.icon] ?? NAV_ICONS.LayoutDashboard,
      }));
    }
    const canAccess = (item: NavItem) => {
      if (item.roles && !hasRole(item.roles)) return false;
      if (item.permission && !hasPermission(item.permission)) return false;
      return true;
    };
    return navItems.filter(canAccess).map((item) => ({
      href: item.href, label: item.label, tKey: item.tKey, icon: item.icon,
    }));
  }, [config?.nav, hasRole, hasPermission]);
}

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const { loading: experienceLoading } = useExperience();
  const pathname = usePathname() ?? '/';
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const badges = useNavBadges();

  const flatNav = useAuthorizedFlatNav();
  const groups = useMemo(() => buildDomainNav(flatNav), [flatNav]);
  const activeKey = useMemo(() => activeDomainKey(pathname, groups), [pathname, groups]);
  const activeGroup = groups.find((g) => g.key === activeKey) ?? null;

  if (!isAuthenticated) return <>{children}</>;

  // Safety fallback: if the adapter produced no domains (unexpected), keep the
  // proven single sidebar so navigation never disappears.
  const useDomainShell = groups.length > 0;

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:start-3 focus:z-[200] focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink focus:shadow-elevated focus:ring-2 focus:ring-teal-500"
        >
          Skip to content
        </a>
        <CommandPalette />

        {useDomainShell ? (
          <>
            {/* Desktop: domain rail + context rail */}
            <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:start-0 lg:w-[76px] bg-surface border-e border-line z-30">
              {experienceLoading ? <RailSkeleton kind="domain" /> : (
                <DomainRail groups={groups} activeKey={activeKey} />
              )}
            </aside>
            <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:start-[76px] lg:w-56 bg-surface border-e border-line z-20">
              {experienceLoading ? <RailSkeleton kind="context" /> : (
                <ContextRail group={activeGroup} pathname={pathname} badges={badges} />
              )}
            </aside>

            {mobileNavOpen && (
              <MobileNav groups={groups} pathname={pathname} badges={badges}
                onClose={() => setMobileNavOpen(false)} />
            )}

            <div className="lg:ps-[300px]">
              <Topbar onMenuClick={() => setMobileNavOpen(true)} />
              <VerifyEmailBanner />
              <div id="main-content"><PageTransition>{children}</PageTransition></div>
            </div>
          </>
        ) : (
          // Fallback shell (unchanged behavior)
          <>
            <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
            <div className="lg:ps-64">
              <Topbar onMenuClick={() => setMobileNavOpen(true)} />
              <VerifyEmailBanner />
              <div id="main-content"><PageTransition>{children}</PageTransition></div>
            </div>
          </>
        )}
      </div>
    </MotionConfig>
  );
}

function RailSkeleton({ kind }: { kind: 'domain' | 'context' }) {
  if (kind === 'domain') {
    return (
      <div className="flex flex-col items-center py-3 gap-2">
        <span className="w-11 h-11 rounded-2xl bg-surface-2 animate-pulse mb-2" />
        {Array.from({ length: 5 }).map((_, i) => (
          <span key={i} className="w-10 h-10 rounded-xl bg-surface-2 animate-pulse" />
        ))}
      </div>
    );
  }
  return (
    <div className="px-3 py-5 space-y-2">
      <div className="h-4 w-24 rounded bg-surface-2 animate-pulse mb-3" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2.5">
          <span className="w-5 h-5 rounded-md bg-surface-2 animate-pulse" />
          <span className="h-3.5 flex-1 max-w-[7rem] rounded bg-surface-2 animate-pulse" />
        </div>
      ))}
    </div>
  );
}
