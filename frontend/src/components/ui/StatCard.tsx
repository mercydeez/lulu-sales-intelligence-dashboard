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
  /** 'surface' = light card with tinted icon chip (default), 'gradient' = sunset gradient panel for hero metrics */
  variant?: 'surface' | 'gradient';
  trend?: 'up' | 'down' | 'flat';
  trendLabel?: string;
  footnote?: ReactNode;
  loading?: boolean;
}

const toneChipClasses: Record<StatCardTone, string> = {
  coral: 'bg-coral-100 text-coral-600',
  teal: 'bg-teal-100 text-teal-600',
  violet: 'bg-violet-100 text-violet-600',
  amber: 'bg-amber-100 text-amber-600',
};

const gradientClasses: Record<StatCardTone, string> = {
  coral: 'sunset-warm shadow-sunset',
  teal: 'sunset-cool shadow-sunset-violet',
  violet: 'sunset-gradient shadow-sunset-violet',
  amber: 'sunset-warm shadow-sunset',
};

const trendClasses: Record<'up' | 'down' | 'flat', string> = {
  up: 'text-emerald-600',
  down: 'text-rose-600',
  flat: 'text-ink-muted',
};

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'flat' }) {
  if (trend === 'up') return <TrendingUp className="w-4 h-4" />;
  if (trend === 'down') return <TrendingDown className="w-4 h-4" />;
  return <Minus className="w-4 h-4" />;
}

export function StatCard({
  label,
  value,
  icon,
  tone = 'coral',
  variant = 'surface',
  trend,
  trendLabel,
  footnote,
  loading = false,
  className,
  ...props
}: StatCardProps) {
  if (loading) {
    return (
      <div className={cn('glass rounded-2xl p-6', className)} {...props}>
        <Skeleton width="50%" height="0.875rem" className="mb-4" />
        <Skeleton width="75%" height="2rem" />
      </div>
    );
  }

  if (variant === 'gradient') {
    return (
      <div
        className={cn(
          'on-sunset relative overflow-hidden rounded-2xl p-6 card-pop text-white group',
          gradientClasses[tone],
          className
        )}
        {...props}
      >
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-white/90">{label}</span>
            {icon && <div className="text-white/80">{icon}</div>}
          </div>
          <div className="text-4xl font-bold text-white">{value}</div>
          {footnote && <div className="mt-2 text-sm text-white/80">{footnote}</div>}
        </div>
        <div className="absolute -right-4 -bottom-4 w-24 h-24 bg-white/15 rounded-full blur-xl group-hover:scale-150 transition-transform duration-500" />
      </div>
    );
  }

  return (
    <div className={cn('glass rounded-2xl p-6 card-hover group', className)} {...props}>
      <div className="flex items-center justify-between mb-4">
        {icon && (
          <div className={cn('p-2 rounded-xl group-hover:scale-110 transition-transform', toneChipClasses[tone])}>
            {icon}
          </div>
        )}
        {trend && (
          <span className={cn('flex items-center gap-1 text-xs font-medium', trendClasses[trend])}>
            <TrendIcon trend={trend} />
            {trendLabel}
          </span>
        )}
      </div>
      <div className="text-3xl font-bold text-ink mb-1">{value}</div>
      <div className="text-sm text-ink-muted">{label}</div>
      {footnote && <div className="text-xs text-ink-muted/80 mt-0.5">{footnote}</div>}
    </div>
  );
}
