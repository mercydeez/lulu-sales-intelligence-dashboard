'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage, Lang } from '@/contexts/LanguageContext';
import { Card, PageHeader, Button, Stagger, RevealItem } from '@/components/ui';
import NotificationPreferences from '@/components/settings/NotificationPreferences';
import { Settings as SettingsIcon, Globe, User as UserIcon, LogOut, Check, Building2, CreditCard, ShieldCheck, Scale, Users } from 'lucide-react';

const LANGUAGES: { code: Lang; label: string; native: string }[] = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'ar', label: 'Arabic', native: 'العربية' },
];

export default function SettingsPage() {
  const router = useRouter();
  const { logout, user } = useAuth();
  const { lang, setLang } = useLanguage();
  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-3xl mx-auto">
        <PageHeader
          title="Preferences"
          description="Manage your language and account settings"
          icon={<SettingsIcon className="w-5 h-5" />}
        />

        <Stagger className="space-y-6">
        {/* Language */}
        <RevealItem><Card padding="lg">
          <div className="flex items-center gap-2 mb-4">
            <Globe className="w-4 h-4 text-teal-600" />
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Language</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {LANGUAGES.map((l) => {
              const active = lang === l.code;
              return (
                <button
                  key={l.code}
                  onClick={() => setLang(l.code)}
                  className={`flex items-center justify-between px-4 py-3 rounded-xl border transition-all text-start ${
                    active
                      ? 'border-teal-400 bg-teal-50 text-ink'
                      : 'border-line hover:bg-surface-2/60 text-ink-soft'
                  }`}
                >
                  <span>
                    <span className="block text-sm font-medium">{l.native}</span>
                    <span className="block text-xs text-ink-muted">{l.label}</span>
                  </span>
                  {active && <Check className="w-4 h-4 text-teal-600" />}
                </button>
              );
            })}
          </div>
          <p className="text-xs text-ink-muted mt-3">
            Arabic switches the interface to right-to-left. Data values remain in their source format.
          </p>
        </Card></RevealItem>

        {/* Notification preferences */}
        <RevealItem><NotificationPreferences /></RevealItem>

        {/* Trust & security */}
        <RevealItem><Card padding="lg">
          <div className="flex items-center gap-2 mb-2">
            <ShieldCheck className="w-4 h-4 text-teal-600" />
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Trust &amp; security</h3>
          </div>
          <p className="text-xs text-ink-muted mb-4">
            How your data is isolated, protected and governed — ready for a security review.
          </p>
          <Link href="/trust">
            <Button variant="secondary" size="sm">
              <ShieldCheck className="w-4 h-4" />
              View trust &amp; security
            </Button>
          </Link>
        </Card></RevealItem>

        {/* Company profile (admins only) */}
        {isAdmin && (
          <RevealItem><Card padding="lg">
            <div className="flex items-center gap-2 mb-2">
              <Building2 className="w-4 h-4 text-teal-600" />
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Company</h3>
            </div>
            <p className="text-xs text-ink-muted mb-4">
              UAE legal &amp; billing details (TRN, trade licence, emirate, VAT) used on invoices and procurement.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link href="/settings/company">
                <Button variant="secondary" size="sm">
                  <Building2 className="w-4 h-4" />
                  Manage company profile
                </Button>
              </Link>
              <Link href="/settings/billing">
                <Button variant="secondary" size="sm">
                  <CreditCard className="w-4 h-4" />
                  Billing &amp; invoices
                </Button>
              </Link>
              <Link href="/outcome-pricing">
                <Button variant="secondary" size="sm">
                  <Scale className="w-4 h-4" />
                  Outcome pricing
                </Button>
              </Link>
              <Link href="/settings/team">
                <Button variant="secondary" size="sm">
                  <Users className="w-4 h-4" />
                  Team
                </Button>
              </Link>
            </div>
          </Card></RevealItem>
        )}

        {/* Account */}
        <RevealItem><Card padding="lg">
          <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Account</h3>
          <div className="flex flex-wrap items-center gap-3">
            <Link href="/profile">
              <Button variant="secondary" size="sm">
                <UserIcon className="w-4 h-4" />
                View profile
              </Button>
            </Link>
            <Button variant="ghost" size="sm" onClick={handleLogout} className="text-rose-600 hover:bg-rose-50">
              <LogOut className="w-4 h-4" />
              Sign out
            </Button>
          </div>
        </Card></RevealItem>
        </Stagger>
      </div>
    </main>
  );
}
