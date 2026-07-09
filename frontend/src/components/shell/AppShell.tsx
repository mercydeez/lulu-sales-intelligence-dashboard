'use client';

import { ReactNode, useState } from 'react';
import { MotionConfig } from 'framer-motion';
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
import { useDomainNav } from '@/lib/nav';

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const { loading: experienceLoading } = useExperience();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const badges = useNavBadges();

  // All nav-building logic lives in the hook; the shell just renders it.
  const { pathname, groups, activeKey, activeGroup } = useDomainNav();

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
