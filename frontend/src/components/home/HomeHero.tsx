'use client';

import { useAuth } from '@/contexts/AuthContext';
import { PRODUCT_NAME, PRODUCT_TAGLINE } from '@/lib/brand';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { Store, MapPin, Package, Users, Activity, ArrowRight } from 'lucide-react';

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

export default function HomeHero() {
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
      <div className="relative overflow-hidden rounded-[28px] hero-mesh p-6 md:p-8 text-white shadow-elevated">
        <div className="blob w-72 h-72 bg-amber-300/40 -top-16 right-10 animate-blob" />
        <div className="blob w-60 h-60 bg-teal-300/30 -bottom-16 left-1/4 animate-blob" style={{ animationDelay: '4s' }} />
        <div className="pointer-events-none absolute inset-y-0 end-0 hidden w-1/2 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.22),transparent_55%)] lg:block" />

        <div className="relative z-10 grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(18rem,0.8fr)] lg:items-end">
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/12 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-white/88 ring-1 ring-white/20 backdrop-blur-sm">
                <Activity className="h-3.5 w-3.5" />
                {PRODUCT_NAME}
              </span>
              <span className="rounded-full bg-surface/20 px-3 py-1 text-xs font-semibold ring-1 ring-white/30 backdrop-blur-sm">
                {roleLabel}
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/82 ring-1 ring-white/15">
                {scopeLabel}
              </span>
            </div>

            <div className="max-w-3xl">
              <p className="text-sm font-medium uppercase tracking-[0.14em] text-white/68">
                {PRODUCT_TAGLINE}
              </p>
              <h1 className="mt-2 text-3xl font-bold tracking-tight md:text-5xl">
                Meridian Hypermarket UAE
              </h1>
            </div>

            <p className="max-w-2xl text-sm leading-6 text-white/84 md:text-base">
              Welcome back, <span className="font-semibold">{user?.first_name}</span>!{' '}
              {getWelcomeMessage(user?.role, user?.accessible_regions, scopedStores)}
            </p>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-white/10 px-4 py-3 backdrop-blur-sm ring-1 ring-white/15">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/66">Store coverage</p>
                <div className="mt-2 flex items-center gap-2">
                  <Store className="h-4 w-4 text-white/82" />
                  <span className="text-lg font-semibold tabular-nums">
                    {storeCount} {storeCount === 1 ? 'Store' : 'Stores'}
                  </span>
                </div>
              </div>

              <div className="rounded-2xl bg-white/10 px-4 py-3 backdrop-blur-sm ring-1 ring-white/15">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/66">Mode</p>
                <div className="mt-2 flex items-center gap-2">
                  <span className="relative flex h-3 w-3">
                    <span className="absolute inline-flex h-3 w-3 rounded-full bg-white/70 animate-ping" />
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-white" />
                  </span>
                  <span className="text-lg font-semibold">Live stream</span>
                </div>
              </div>

              <div className="rounded-2xl bg-white/10 px-4 py-3 backdrop-blur-sm ring-1 ring-white/15">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/66">Next action</p>
                <div className="mt-2 flex items-center gap-2 text-lg font-semibold">
                  Monitor signals
                  <ArrowRight className="h-4 w-4 text-white/74" />
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] bg-black/10 p-4 backdrop-blur-md ring-1 ring-white/15 lg:p-5">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <div className="rounded-2xl bg-white/10 p-4 ring-1 ring-white/12">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/66">Current access</p>
                <p className="mt-2 text-lg font-semibold">{roleLabel}</p>
                <p className="mt-1 text-sm text-white/72">{scopeLabel}</p>
              </div>

              <div className="rounded-2xl bg-white/10 p-4 ring-1 ring-white/12">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/66">Workspace status</p>
                <div className="mt-2 flex items-center gap-2 text-sm font-medium text-white/84">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-300/75 animate-ping" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-300" />
                  </span>
                  Connected to streaming sales feed
                </div>
                <p className="mt-3 text-sm leading-6 text-white/72">
                  Use the dashboard below to triage alerts, watch live volume, and move from signal to decision quickly.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {user?.role === 'super_admin' && (
        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            { icon: MapPin, label: 'Regions', value: '3', tint: 'bg-blue-100 text-blue-600' },
            { icon: Store, label: 'Total Stores', value: '10', tint: 'bg-violet-100 text-violet-600' },
            { icon: Package, label: 'Products', value: '50', tint: 'bg-teal-100 text-teal-600' },
            { icon: Users, label: 'Users', value: '3', tint: 'bg-amber-100 text-amber-600' },
          ].map(({ icon: Icon, label, value, tint }) => (
            <div key={label} className="glass card-pop rounded-2xl p-4 flex items-center gap-3">
              <div className={`p-2.5 rounded-xl ${tint}`}>
                <Icon className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs text-ink-muted">{label}</p>
                <p className="text-lg font-bold text-ink">{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {user?.role === 'regional_manager' && (
        <div className="mt-4 rounded-2xl p-4 glass">
          <p className="mb-2 text-xs text-ink-muted">Your Region: {user.accessible_regions?.join(', ').toUpperCase()}</p>
          <div className="flex flex-wrap gap-2">
            {user.accessible_stores?.map(storeId => (
              <span key={storeId} className="rounded-full border border-violet-200 bg-violet-100 px-3 py-1 text-xs font-medium text-violet-600">
                Store #{storeId}
              </span>
            ))}
          </div>
        </div>
      )}

      {user?.role === 'store_manager' && (
        <div className="mt-4 rounded-2xl p-4 glass">
          <p className="mb-2 text-xs text-ink-muted">Your Store</p>
          <p className="text-lg font-semibold text-teal-600">Meridian Hypermarket Al Barsha, Dubai</p>
        </div>
      )}
    </header>
  );
}
