'use client';

import { ReactNode, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import CommandPalette from '@/components/CommandPalette';

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  if (!isAuthenticated) return <>{children}</>;

  return (
    <div className="min-h-screen">
      <CommandPalette />
      <Sidebar mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="lg:ps-64">
        <Topbar onMenuClick={() => setMobileNavOpen(true)} />
        {children}
      </div>
    </div>
  );
}
