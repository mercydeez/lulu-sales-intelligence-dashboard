'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage, Lang } from '@/contexts/LanguageContext';
import { useTheme } from '@/contexts/ThemeContext';
import { Card, PageHeader, Button } from '@/components/ui';
import { Settings as SettingsIcon, Globe, User as UserIcon, LogOut, Check, Sun, Moon } from 'lucide-react';

const LANGUAGES: { code: Lang; label: string; native: string }[] = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'ar', label: 'Arabic', native: 'العربية' },
];

export default function SettingsPage() {
  const router = useRouter();
  const { logout } = useAuth();
  const { lang, setLang } = useLanguage();
  const { theme, setTheme } = useTheme();

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

        {/* Language */}
        <Card padding="lg" className="mb-6">
          <div className="flex items-center gap-2 mb-4">
            <Globe className="w-4 h-4 text-coral-500" />
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
                      ? 'border-coral-300 bg-coral-50 text-ink'
                      : 'border-coral-100 hover:bg-coral-50/60 text-ink-soft'
                  }`}
                >
                  <span>
                    <span className="block text-sm font-medium">{l.native}</span>
                    <span className="block text-xs text-ink-muted">{l.label}</span>
                  </span>
                  {active && <Check className="w-4 h-4 text-coral-500" />}
                </button>
              );
            })}
          </div>
          <p className="text-xs text-ink-muted mt-3">
            Arabic switches the interface to right-to-left. Data values remain in their source format.
          </p>
        </Card>

        {/* Appearance */}
        <Card padding="lg" className="mb-6">
          <div className="flex items-center gap-2 mb-4">
            <Sun className="w-4 h-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Appearance</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {([
              { code: 'light' as const, label: 'Light', desc: 'Bright, default', Icon: Sun },
              { code: 'dark' as const, label: 'Dark', desc: 'Dim, low-light', Icon: Moon },
            ]).map(({ code, label, desc, Icon }) => {
              const active = theme === code;
              return (
                <button
                  key={code}
                  onClick={() => setTheme(code)}
                  className={`flex items-center justify-between px-4 py-3 rounded-xl border transition-all text-start ${
                    active ? 'border-teal-300 bg-teal-50 text-ink' : 'border-line hover:bg-surface-2 text-ink-soft'
                  }`}
                >
                  <span className="flex items-center gap-3">
                    <Icon className="w-4 h-4" />
                    <span>
                      <span className="block text-sm font-medium">{label}</span>
                      <span className="block text-xs text-ink-muted">{desc}</span>
                    </span>
                  </span>
                  {active && <Check className="w-4 h-4 text-teal-500" />}
                </button>
              );
            })}
          </div>
        </Card>

        {/* Account */}
        <Card padding="lg">
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
        </Card>
      </div>
    </main>
  );
}
