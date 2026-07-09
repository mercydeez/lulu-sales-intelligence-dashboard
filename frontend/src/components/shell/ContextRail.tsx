'use client';

/**
 * Context Rail — the secondary rail: the pages of the active domain, grouped
 * into labeled sections when the domain declares them (DESIGN_SYSTEM §5.2).
 * Shows live badge counts and the sliding active-page indicator.
 */
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Settings } from 'lucide-react';
import { useLanguage } from '@/contexts/LanguageContext';
import { cn } from '@/lib/cn';
import type { DomainGroup, FlatNavItem } from '@/lib/nav/adapter';

/** Badge accent by route (mirrors the old sidebar). */
const BADGE_TONE: Record<string, string> = {
  '/alerts': 'bg-rose-600', '/security': 'bg-rose-600',
  '/approvals': 'bg-teal-500', '/decisions': 'bg-teal-600',
};

function PageLink({
  item, active, badge, onNavigate,
}: {
  item: FlatNavItem; active: boolean; badge?: number; onNavigate?: () => void;
}) {
  const { t } = useLanguage();
  const showBadge = badge != null && badge > 0;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors',
        active ? 'text-teal-700' : 'text-ink-muted hover:text-ink hover:bg-surface-2',
      )}
    >
      {active && (
        <motion.span
          layoutId="context-active"
          className="absolute inset-0 rounded-xl bg-teal-50 ring-1 ring-teal-100"
          transition={{ type: 'spring', stiffness: 380, damping: 32 }}
        />
      )}
      <span className="relative z-10 flex items-center">{item.icon}</span>
      <span className="relative z-10 flex-1 truncate">{item.tKey ? t(item.tKey) : item.label}</span>
      {showBadge && (
        <span className={cn(
          'relative z-10 ms-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full text-white text-[10px] font-bold',
          BADGE_TONE[item.href] ?? 'bg-teal-600',
        )}>
          {badge}
        </span>
      )}
    </Link>
  );
}

export function ContextRail({
  group, pathname, badges, onNavigate,
}: {
  group: DomainGroup | null;
  pathname: string;
  badges: Record<string, number>;
  onNavigate?: () => void;
}) {
  const { t } = useLanguage();
  const isActive = (href: string) =>
    pathname === href || (href !== '/' && pathname.startsWith(href + '/'));

  return (
    <div className="flex flex-col h-full">
      <div className="h-16 px-4 flex items-center shrink-0 border-b border-line">
        <h2 className="text-sm font-bold text-ink truncate">{group ? t(group.tKey) : ''}</h2>
      </div>

      <nav aria-label="Section" className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {group && group.sections.length > 0
          ? group.sections.map((section) => (
              <div key={section.label} className="pb-1">
                <p className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  {section.label}
                </p>
                {section.pages.map((item) => (
                  <PageLink key={item.href} item={item} active={isActive(item.href)}
                    badge={badges[item.href]} onNavigate={onNavigate} />
                ))}
              </div>
            ))
          : group?.pages.map((item) => (
              <PageLink key={item.href} item={item} active={isActive(item.href)}
                badge={badges[item.href]} onNavigate={onNavigate} />
            ))}
      </nav>

      {/* Preferences stays in the utility layer, but a quiet link here mirrors
          the old sidebar footer so nothing regresses for muscle memory. */}
      <div className="px-3 py-4 border-t border-line">
        <Link
          href="/settings"
          onClick={onNavigate}
          className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors"
        >
          <Settings className="w-5 h-5" />
          {t('nav.preferences') || 'Preferences'}
        </Link>
      </div>
    </div>
  );
}
