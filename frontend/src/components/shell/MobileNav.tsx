'use client';

/**
 * Mobile navigation drawer — the two rails collapse into one off-canvas list on
 * small screens, grouped by domain (domain label = section header). Same links,
 * same badges as the desktop rails.
 */
import Link from 'next/link';
import { X, Settings } from 'lucide-react';
import { useLanguage } from '@/contexts/LanguageContext';
import { cn } from '@/lib/cn';
import type { DomainGroup } from '@/lib/nav/adapter';

const BADGE_TONE: Record<string, string> = {
  '/alerts': 'bg-rose-600', '/security': 'bg-rose-600',
  '/approvals': 'bg-teal-500', '/decisions': 'bg-teal-600',
};

export function MobileNav({
  groups, pathname, badges, onClose,
}: {
  groups: DomainGroup[];
  pathname: string;
  badges: Record<string, number>;
  onClose: () => void;
}) {
  const { t } = useLanguage();
  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href + '/'));

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <aside className="absolute inset-y-0 start-0 w-72 bg-surface shadow-2xl flex flex-col animate-slide-in">
        <button
          onClick={onClose}
          className="absolute top-4 end-4 p-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors"
          aria-label="Close navigation"
        >
          <X className="w-4 h-4" />
        </button>
        <nav aria-label="Navigation" className="flex-1 overflow-y-auto px-3 py-5 space-y-4 mt-8">
          {groups.map((g) => (
            <div key={g.key}>
              <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                {t(g.tKey)}
              </p>
              {g.pages.map((item) => {
                const badge = badges[item.href];
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onClose}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors',
                      active ? 'text-teal-700 bg-teal-50 ring-1 ring-teal-100' : 'text-ink-muted hover:text-ink hover:bg-surface-2',
                    )}
                  >
                    <span className="flex items-center">{item.icon}</span>
                    <span className="flex-1 truncate">{item.tKey ? t(item.tKey) : item.label}</span>
                    {badge != null && badge > 0 && (
                      <span className={cn('ms-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full text-white text-[10px] font-bold', BADGE_TONE[item.href] ?? 'bg-teal-600')}>
                        {badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="px-3 py-4 border-t border-line">
          <Link href="/settings" onClick={onClose}
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors">
            <Settings className="w-5 h-5" /> {t('nav.preferences') || 'Preferences'}
          </Link>
        </div>
      </aside>
    </div>
  );
}
