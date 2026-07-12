'use client';

import { type ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { PRODUCT_NAME } from '@/lib/brand';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { Activity, Store } from 'lucide-react';

function getStoreIds(user: ReturnType<typeof useAuth>['user']): number[] {
  return user?.permissions?.accessible_stores?.length
    ? user.permissions.accessible_stores
    : (user?.accessible_stores || []);
}

function getWelcomeMessage(role?: UserRole, regions?: string[], stores?: number[]): string {
  switch (role) {
    case 'super_admin':
      return 'Full access to all stores and analytics across UAE';
    case 'regional_manager':
      return `Managing ${regions?.join(', ')} region`;
    case 'store_manager':
      return `Managing ${stores?.length || 0} store(s)`;
    case 'analyst':
      return 'View-only access to assigned stores';
    default:
      return '';
  }
}

export default function HomeHero({ controls }: { controls?: ReactNode }) {
  const { user } = useAuth();
  const scopedStores = getStoreIds(user);
  const storeCount = user?.role === 'super_admin' ? 10 : scopedStores.length;
  const roleLabel = ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role;
  const scopeLabel = user?.role === 'super_admin'
    ? 'All UAE stores'
    : user?.role === 'regional_manager'
      ? `${user?.accessible_regions?.join(', ') || 'Assigned'} region`
      : `${storeCount} ${storeCount === 1 ? 'store' : 'stores'} in scope`;

  return (
    <header className="max-w-7xl mx-auto mb-8">
      <div className="hero-mesh rounded-2xl px-6 py-7 text-white shadow-elevated md:px-8">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 font-semibold ring-1 ring-white/20">
                <Activity className="h-3.5 w-3.5" />
                Live operations
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1 font-medium text-white/85 ring-1 ring-white/15">
                {roleLabel}
              </span>
            </div>
            <p className="text-sm font-medium text-white/70">{PRODUCT_NAME}</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight md:text-4xl">
              Good to see you, {user?.first_name || 'there'}.
            </h1>
            <p className="mt-3 text-sm leading-6 text-white/80 md:text-base">
              {getWelcomeMessage(user?.role, user?.accessible_regions, scopedStores)}
            </p>
          </div>

          <div className="flex flex-col gap-3 md:items-end">
            <div className="flex items-center gap-3 rounded-xl border border-white/15 bg-black/10 px-4 py-3 text-sm">
              <Store className="h-4 w-4 text-white/75" />
              <div>
                <p className="font-semibold">{scopeLabel}</p>
                <p className="text-xs text-white/65">Streaming sales data is active</p>
              </div>
            </div>
            {controls}
          </div>
        </div>
      </div>
    </header>
  );
}
