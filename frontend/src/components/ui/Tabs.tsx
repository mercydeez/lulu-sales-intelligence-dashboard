'use client';

import { HTMLAttributes, ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/cn';

export interface TabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Optional trailing count pill, e.g. unread alerts */
  badge?: ReactNode;
}

export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
}

export function Tabs({ items, value, onChange, className, ...props }: TabsProps) {
  // One layoutId per Tabs instance so the active pill animates only within its
  // own group (multiple Tabs on a page won't share/steal the indicator).
  const layoutId = `tab-indicator-${(props.id as string) ?? items.map((i) => i.id).join('-')}`;
  return (
    <div
      role="tablist"
      className={cn('inline-flex items-center gap-1 p-1 rounded-2xl bg-surface-2/70 border border-line', className)}
      {...props}
    >
      {items.map((item) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            className={cn(
              'relative flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50',
              active ? 'text-teal-700' : 'text-ink-muted hover:text-ink'
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-xl bg-surface shadow-soft"
                transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              />
            )}
            <span className="relative z-10 flex items-center gap-1.5">
              {item.icon}
              {item.label}
              {item.badge}
            </span>
          </button>
        );
      })}
    </div>
  );
}
