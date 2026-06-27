'use client';

import { ReactNode, useState } from 'react';
import { MotionConfig } from 'framer-motion';
import { useAuth } from '@/contexts/AuthContext';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import VerifyEmailBanner from './VerifyEmailBanner';
import CommandPalette from '@/components/CommandPalette';
import { PageTransition } from '@/components/ui';

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  if (!isAuthenticated) return <>{children}</>;

  return (
    // reducedMotion="user" makes every framer-motion animation in the app honor
    // the OS prefers-reduced-motion setting automatically.
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen">
        {/* Keyboard skip link — first focusable element, visible only on focus. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:start-3 focus:z-[200] focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink focus:shadow-elevated focus:ring-2 focus:ring-teal-500"
        >
          Skip to content
        </a>
        <CommandPalette />
        <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
        <div className="lg:ps-64">
          <Topbar onMenuClick={() => setMobileNavOpen(true)} />
          <VerifyEmailBanner />
          <div id="main-content">
            <PageTransition>{children}</PageTransition>
          </div>
        </div>
      </div>
    </MotionConfig>
  );
}
