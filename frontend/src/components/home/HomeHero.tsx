'use client';

import { useAuth } from '@/contexts/AuthContext';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { Store, MapPin, Package, Users } from 'lucide-react';

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
  const storeCount = user?.role === 'super_admin' ? 10 : (user?.accessible_stores?.length || 0);

  return (
    <header className="max-w-7xl mx-auto mb-8">
      <div className="relative overflow-hidden rounded-3xl sunset-gradient p-6 md:p-8 text-white shadow-sunset">
        <div className="blob w-72 h-72 bg-amber-300/40 -top-16 right-10 animate-blob" />
        <div className="blob w-60 h-60 bg-teal-300/30 -bottom-16 left-1/4 animate-blob" style={{ animationDelay: '4s' }} />

        <div className="relative z-10 flex items-center justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Meridian Hypermarket UAE</h1>
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-white/20 backdrop-blur-sm ring-1 ring-white/30">
                {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
              </span>
            </div>
            <p className="text-white/85">
              Welcome back, <span className="font-semibold">{user?.first_name}</span>!{' '}
              {getWelcomeMessage(user?.role, user?.accessible_regions, user?.accessible_stores)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="rounded-2xl px-4 py-2 flex items-center gap-2 bg-white/15 backdrop-blur-sm ring-1 ring-white/25">
              <Store className="w-4 h-4" />
              <span className="text-sm font-medium">
                {storeCount} {storeCount === 1 ? 'Store' : 'Stores'}
              </span>
            </div>
            <div className="rounded-2xl px-4 py-2 flex items-center gap-2 bg-white/15 backdrop-blur-sm ring-1 ring-white/25">
              <span className="relative flex h-3 w-3">
                <span className="absolute inline-flex h-3 w-3 rounded-full bg-white/80 animate-ping" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-white" />
              </span>
              <span className="text-sm font-semibold">LIVE</span>
            </div>
          </div>
        </div>
      </div>

      {user?.role === 'super_admin' && (
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { icon: MapPin, label: 'Regions', value: '3', tint: 'bg-coral-100 text-coral-600' },
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
        <div className="mt-4 p-4 glass rounded-2xl">
          <p className="text-xs text-ink-muted mb-2">Your Region: {user.accessible_regions?.join(', ').toUpperCase()}</p>
          <div className="flex flex-wrap gap-2">
            {user.accessible_stores?.map(storeId => (
              <span key={storeId} className="px-3 py-1 rounded-full bg-violet-100 text-violet-600 text-xs font-medium border border-violet-200">
                Store #{storeId}
              </span>
            ))}
          </div>
        </div>
      )}

      {user?.role === 'store_manager' && (
        <div className="mt-4 p-4 glass rounded-2xl">
          <p className="text-xs text-ink-muted mb-2">Your Store</p>
          <p className="text-lg font-semibold text-teal-600">Meridian Hypermarket Al Barsha, Dubai</p>
        </div>
      )}
    </header>
  );
}
