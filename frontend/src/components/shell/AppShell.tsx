'use client';

import { ReactNode, useState } from 'react';
import { MotionConfig } from 'framer-motion';
import { useAuth } from '@/contexts/AuthContext';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import VerifyEmailBanner from './VerifyEmailBanner';
import CommandPalette from '@/components/CommandPalette';

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  if (!isAuthenticated) return <>{children}</>;

  return (
    // reducedMotion="user" makes every framer-motion animation in the app honor
    // the OS prefers-reduced-motion setting automatically.
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen">
        <CommandPalette />
        <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
        <div className="lg:ps-64">
          <Topbar onMenuClick={() => setMobileNavOpen(true)} />
          <VerifyEmailBanner />
          {children}
        </div>
      </div>
    </MotionConfig>
  );
}
