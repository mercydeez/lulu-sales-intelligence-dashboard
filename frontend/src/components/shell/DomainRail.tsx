'use client';

/**
 * Domain Rail — the primary left rail: six domains only (DESIGN_SYSTEM §5.1).
 * Icon-first, role-filtered (only domains with ≥1 authorized page appear).
 * Clicking a domain goes to its first page; the Context Rail then lists siblings.
 */
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  Home, Inbox, Package, BarChart3, Database, Shield, type LucideIcon,
} from 'lucide-react';
import { useLanguage } from '@/contexts/LanguageContext';
import { PRODUCT_NAME } from '@/lib/brand';
import { BrandIcon } from '@/components/branding/BrandIcon';
import { cn } from '@/lib/cn';
import type { DomainGroup, DomainKey } from '@/lib/nav';

const DOMAIN_ICONS: Record<string, LucideIcon> = {
  Home, Inbox, Package, BarChart3, Database, Shield,
};

export function DomainRail({
  groups, activeKey, onNavigate,
}: {
  groups: DomainGroup[];
  activeKey: DomainKey | null;
  onNavigate?: () => void;
}) {
  const { t } = useLanguage();
  return (
    <nav aria-label="Primary" className="flex flex-col items-center h-full py-3 gap-1">
      <Link
        href="/today"
        onClick={onNavigate}
        aria-label={`${PRODUCT_NAME} home`}
        className="w-11 h-11 rounded-2xl sunset-gradient flex items-center justify-center shadow-sunset shrink-0 mb-2"
      >
        <BrandIcon size={20} decorative className="text-white" />
      </Link>

      {groups.map((g) => {
        const Icon = DOMAIN_ICONS[g.icon] ?? Home;
        const active = g.key === activeKey;
        const target = g.pages[0]?.href ?? '/today';
        return (
          <Link
            key={g.key}
            href={target}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            title={t(g.tKey)}
            className={cn(
              'relative w-14 flex flex-col items-center gap-1 py-2 rounded-xl text-[11px] font-medium transition-colors',
              active ? 'text-teal-700' : 'text-ink-muted hover:text-ink hover:bg-surface-2',
            )}
          >
            {active && (
              <motion.span
                layoutId="domain-active"
                className="absolute inset-0 rounded-xl bg-teal-50 ring-1 ring-teal-100"
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
              />
            )}
            {active && (
              <motion.span
                layoutId="domain-active-bar"
                className="absolute start-0 top-1/2 -translate-y-1/2 h-6 w-1 rounded-full bg-teal-600"
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
              />
            )}
            <span className="relative z-10 flex items-center justify-center"><Icon className="w-5 h-5" /></span>
            <span className="relative z-10 leading-none text-center">{t(g.tKey)}</span>
          </Link>
        );
      })}
    </nav>
  );
}
