import { HTMLAttributes, ReactNode } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Skeleton } from './Skeleton';

export type StatCardTone = 'coral' | 'teal' | 'violet' | 'amber';

export interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: StatCardTone;
  /** 'surface' = flat bordered card (default), 'gradient' = solid brand panel for hero metrics */
  variant?: 'surface' | 'gradient';
  trend?: 'up' | 'down' | 'flat';
  trendLabel?: string;
  footnote?: ReactNode;
  loading?: boolean;
  /** Absolutely-positioned overlay content (tooltip etc.) — caller controls its own positioning. */
  children?: ReactNode;
}

/** Thin left-accent colour per tone — the only colour on a calm card. */
const toneAccent: Record<StatCardTone, string> = {
  coral: '#c8451f',
  teal: '#0f766e',
  violet: '#0f766e',
  amber: '#d97706',
};

const deltaChip: Record<'up' | 'down' | 'flat', string> = {
  up: 'bg-teal-50 text-teal-700',
  down: 'bg-coral-50 text-coral-700',
  flat: 'bg-surface-2 text-ink-muted',
};

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'flat' }) {
  if (trend === 'up') return <TrendingUp className="w-3.5 h-3.5" />;
  if (trend === 'down') return <TrendingDown className="w-3.5 h-3.5" />;
  return <Minus className="w-3.5 h-3.5" />;
}

export function StatCard({
  label,
  value,
  icon,
  tone = 'teal',
  variant = 'surface',
  trend,
  trendLabel,
  footnote,
  loading = false,
  className,
  children,
  ...props
}: StatCardProps) {
  if (loading) {
    return (
      <div className={cn('bg-surface border border-line rounded-lg p-5', className)} {...props}>
        <Skeleton width="45%" height="0.75rem" className="mb-4" />
        <Skeleton width="70%" height="1.75rem" />
      </div>
    );
  }

  if (variant === 'gradient') {
    return (
      <div
        className={cn(
          'relative overflow-hidden rounded-lg p-5 bg-sunset-gradient text-white',
          className
        )}
        {...props}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-[11px] uppercase tracking-wide text-white/80">{label}</span>
          {icon && <div className="text-white/80">{icon}</div>}
        </div>
        <div className="text-3xl font-semibold tabular-nums leading-tight">{value}</div>
        {(trend || footnote) && (
          <div className="mt-2 flex items-center gap-2 text-sm text-white/85">
            {trend && (
              <span className="inline-flex items-center gap-1 tabular-nums">
                <TrendIcon trend={trend} />
                {trendLabel}
              </span>
            )}
            {footnote && <span className="text-white/75">{footnote}</span>}
          </div>
        )}
        {children}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'relative bg-surface border border-line rounded-lg p-5 card-hover',
        className
      )}
      style={{ borderLeft: `3px solid ${toneAccent[tone]}` }}
      {...props}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">{label}</span>
        {icon && <div className="text-ink-muted/70">{icon}</div>}
      </div>
      <div className="text-3xl font-semibold text-ink tabular-nums leading-tight">{value}</div>
      <div className="mt-2 flex items-center gap-2">
        {trend && (
          <span
            className={cn(
              'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full tabular-nums',
              deltaChip[trend]
            )}
          >
            <TrendIcon trend={trend} />
            {trendLabel}
          </span>
        )}
        {footnote && <span className="text-xs text-ink-muted">{footnote}</span>}
      </div>
      {children}
    </div>
  );
}
