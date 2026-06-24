'use client';

import { useAuth } from '@/contexts/AuthContext';
import { Card, Badge, PageHeader } from '@/components/ui';
import TwoFactorSettings from '@/components/settings/TwoFactorSettings';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import {
  User as UserIcon,
  Mail,
  Store,
  MapPin,
  Briefcase,
  Building2,
  Clock,
  CheckCircle2,
} from 'lucide-react';

const roleBadge: Record<string, 'violet' | 'teal' | 'coral' | 'neutral'> = {
  super_admin: 'violet',
  regional_manager: 'teal',
  store_manager: 'coral',
};

function Field({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="p-2 rounded-lg bg-coral-50 text-coral-500 shrink-0">{icon}</div>
      <div className="min-w-0">
        <p className="text-xs text-ink-muted">{label}</p>
        <p className="text-sm font-medium text-ink truncate">{value}</p>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();

  if (!user) return null;

  const initials = `${user.first_name?.[0] ?? ''}${user.last_name?.[0] ?? ''}`.toUpperCase();
  const roleLabel = ROLE_DISPLAY_NAMES[user.role as UserRole] || user.role;
  const lastLogin = user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'This session';

  const permissions = Object.entries(user.permissions || {})
    .filter(([key, val]) => key.startsWith('can_') && val === true)
    .map(([key]) => key.replace(/^can_/, '').replace(/_/g, ' '));

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title="Profile"
          description="Your account details and access scope"
          icon={<UserIcon className="w-5 h-5" />}
        />

        {/* Identity */}
        <Card padding="lg" className="mb-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-2xl sunset-gradient flex items-center justify-center text-white text-xl font-bold shrink-0 shadow-sunset">
              {initials}
            </div>
            <div className="min-w-0">
              <h2 className="text-xl font-bold text-ink truncate">
                {user.first_name} {user.last_name}
              </h2>
              <p className="text-sm text-ink-muted truncate">{user.email}</p>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant={roleBadge[user.role] || 'neutral'} size="sm">
                  {roleLabel}
                </Badge>
                <Badge variant="neutral" size="sm">
                  {user.status}
                </Badge>
              </div>
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Details */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Account</h3>
            <div className="space-y-4">
              <Field icon={<Mail className="w-4 h-4" />} label="Email" value={user.email} />
              <Field icon={<Briefcase className="w-4 h-4" />} label="Job title" value={user.job_title || '—'} />
              <Field icon={<Building2 className="w-4 h-4" />} label="Department" value={user.department || '—'} />
              <Field icon={<Clock className="w-4 h-4" />} label="Last login" value={lastLogin} />
            </div>
          </Card>

          {/* Access scope */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Data Access</h3>
            <div className="space-y-4">
              <Field
                icon={<Store className="w-4 h-4" />}
                label="Stores"
                value={
                  user.role === 'super_admin'
                    ? 'All stores'
                    : `${user.accessible_stores?.length || 0} store(s)`
                }
              />
              <Field
                icon={<MapPin className="w-4 h-4" />}
                label="Regions"
                value={
                  user.accessible_regions?.length
                    ? user.accessible_regions.join(', ')
                    : user.role === 'super_admin'
                    ? 'All regions'
                    : '—'
                }
              />
            </div>
          </Card>
        </div>

        {/* Permissions */}
        {permissions.length > 0 && (
          <Card padding="lg" className="mt-6">
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Permissions</h3>
            <div className="flex flex-wrap gap-2">
              {permissions.map((perm) => (
                <span
                  key={perm}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-coral-50 text-ink-soft text-xs font-medium capitalize"
                >
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                  {perm}
                </span>
              ))}
            </div>
          </Card>
        )}

        {/* Security: 2-step verification */}
        <TwoFactorSettings />
      </div>
    </main>
  );
}
