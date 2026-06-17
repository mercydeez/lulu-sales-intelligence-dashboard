import { HTMLAttributes, ReactNode } from 'react';
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
  height?: number | string;
  loading?: boolean;
  empty?: boolean;
  emptyState?: ReactNode;
  children?: ReactNode;
}

/** Card wrapper for chart components — handles the title/actions row plus loading and empty states. */
export function ChartFrame({
  title,
  subtitle,
  actions,
  live = false,
  height = 300,
  loading = false,
  empty = false,
  emptyState,
  children,
  className,
  ...props
}: ChartFrameProps) {
  return (
    <Card variant="glass" padding="md" className={className} {...props}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-ink">{title}</h3>
            {live && <LiveIndicator size="sm" />}
          </div>
          {subtitle && <p className="text-sm text-ink-muted mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
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
  );
}
