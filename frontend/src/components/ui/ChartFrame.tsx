'use client';

import { HTMLAttributes, ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/cn';
import { Card } from './Card';
import { LiveIndicator } from './LiveIndicator';
import { Skeleton } from './Skeleton';
import { EmptyState } from './EmptyState';

export interface ChartFrameProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  live?: boolean;
  /** Optional accent hue for the title rule (defaults to brand teal). */
  accent?: string;
  height?: number | string;
  loading?: boolean;
  empty?: boolean;
  emptyState?: ReactNode;
  children?: ReactNode;
}

/**
 * Card wrapper for charts — title/actions row, an accent rule, a live badge, and
 * loading/empty states. Enters with a subtle rise so dashboards feel alive.
 */
export function ChartFrame({
  title,
  subtitle,
  actions,
  live = false,
  accent = '#0f766e',
  height = 300,
  loading = false,
  empty = false,
  emptyState,
  children,
  className,
  ...props
}: ChartFrameProps) {
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}
      className="h-full"
    >
      <Card variant="glass" padding="md" className={cn('h-full', className)} {...props}>
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-4 w-1 rounded-full"
                style={{ background: accent }}
              />
              <h3 className="text-base font-semibold text-ink truncate">{title}</h3>
              {live && <LiveIndicator size="sm" />}
            </div>
            {subtitle && <p className="text-sm text-ink-muted mt-0.5 ps-3">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>

        <div style={{ height }}>
          {loading ? (
            <Skeleton width="100%" height="100%" rounded="lg" />
          ) : empty ? (
            emptyState ?? <EmptyState title="No data yet" description="Check back once data starts flowing in." />
          ) : (
            children
          )}
        </div>
      </Card>
    </motion.div>
  );
}
