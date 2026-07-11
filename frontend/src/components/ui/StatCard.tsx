'use client';

import { HTMLAttributes, ReactNode } from 'react';
import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Skeleton } from './Skeleton';

export type StatCardTone = 'coral' | 'teal' | 'violet' | 'amber';

// Omit the DOM drag/animation handlers that collide with framer-motion's typed
// equivalents when we spread `...props` onto a motion.div.
type DivProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  'onDrag' | 'onDragStart' | 'onDragEnd' | 'onAnimationStart' | 'onAnimationEnd' | 'onAnimationIteration'
>;

export interface StatCardProps extends DivProps {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: StatCardTone;
  /** 'surface' = bordered card (default), 'gradient' = solid brand panel for hero metrics */
  variant?: 'surface' | 'gradient';
  trend?: 'up' | 'down' | 'flat';
  trendLabel?: string;
  footnote?: ReactNode;
  /** Optional micro-trend: a short series (e.g. last 7–14 points) rendered as a
   *  tiny inline sparkline — the "one micro-visual" of the KPI-card anatomy.
   *  Pure SVG, no chart lib, so it adds ~0 to the bundle. */
  sparkline?: number[];
  loading?: boolean;
  /** Absolutely-positioned overlay content (tooltip etc.) — caller controls its own positioning. */
  children?: ReactNode;
}

// Accent channel vars (globals.css) — light values match the old hex exactly;
// dark mode swaps in brightened hues so the left border keeps AA on dark.
const toneAccent: Record<StatCardTone, string> = {
  coral: 'rgb(var(--a-coral))',
  teal: 'rgb(var(--a-teal))',
  violet: 'rgb(var(--a-violet))',
  amber: 'rgb(var(--a-amber))',
};

/** Tinted icon chip per tone — a touch of color-coding on the calm card. */
const toneChip: Record<StatCardTone, string> = {
  coral: 'bg-coral-50 text-coral-600 dark:bg-coral-500/15 dark:text-coral-300',
  teal: 'bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300',
  violet: 'bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300',
  amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300',
};

/** Tone-mapped gradient for the hero (gradient) variant — so the cards are
 *  color-coded, not all teal. */
const toneGradient: Record<StatCardTone, string> = {
  coral: 'bg-grad-coral',
  teal: 'bg-sunset-gradient',
  violet: 'bg-grad-violet',
  amber: 'bg-grad-amber',
};

const deltaChip: Record<'up' | 'down' | 'flat', string> = {
  up: 'bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300',
  down: 'bg-coral-50 text-coral-700 dark:bg-coral-500/15 dark:text-coral-300',
  flat: 'bg-surface-2 text-ink-muted',
};

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'flat' }) {
  if (trend === 'up') return <TrendingUp className="w-3.5 h-3.5" />;
  if (trend === 'down') return <TrendingDown className="w-3.5 h-3.5" />;
  return <Minus className="w-3.5 h-3.5" />;
}

/** Tiny inline sparkline — pure SVG (no chart lib). Normalizes the series into a
 *  fixed viewBox and draws a polyline; a soft area fill underneath adds weight at
 *  ~60px wide. `stroke` defaults to currentColor so callers colour it via text. */
function MiniSparkline({ data, stroke = 'currentColor', width = 64, height = 22 }: {
  data: number[]; stroke?: string; width?: number; height?: number;
}) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = i * stepX;
    const y = height - 2 - ((v - min) / span) * (height - 4);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden
         className="shrink-0" style={{ color: stroke }} preserveAspectRatio="none">
      <path d={area} fill="currentColor" fillOpacity={0.12} stroke="none" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Colour the sparkline by trend (green up / coral down) else the card tone. */
function sparkStroke(trend: StatCardProps['trend'], tone: StatCardTone): string {
  if (trend === 'up') return 'rgb(var(--a-teal))';
  if (trend === 'down') return 'rgb(var(--a-coral))';
  return toneAccent[tone];
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
  sparkline,
  loading = false,
  className,
  children,
  ...props
}: StatCardProps) {
  if (loading) {
    return (
      <div className={cn('bg-surface border border-line rounded-xl p-5', className)} {...props}>
        <Skeleton width="45%" height="0.75rem" className="mb-4" />
        <Skeleton width="70%" height="1.75rem" />
      </div>
    );
  }

  if (variant === 'gradient') {
    return (
      <motion.div
        variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}
        whileHover={{ y: -4 }}
        transition={{ type: 'spring', stiffness: 320, damping: 24 }}
        className={cn(
          'on-sunset relative overflow-hidden rounded-xl p-5 text-white shadow-elevated',
          toneGradient[tone],
          className
        )}
        {...props}
      >
        {/* soft sheen */}
        <div aria-hidden className="absolute -top-10 -right-8 w-32 h-32 rounded-full bg-white/15 blur-2xl" />
        <div className="relative flex items-center justify-between mb-2">
          <span className="font-mono text-[11px] uppercase tracking-wide text-white/80">{label}</span>
          {icon && <div className="text-white/85">{icon}</div>}
        </div>
        <div className="relative text-3xl font-bold tabular-nums leading-tight">{value}</div>
        {(trend || footnote || sparkline) && (
          <div className="relative mt-2 flex items-center justify-between gap-2 text-sm text-white/85">
            <div className="flex items-center gap-2 min-w-0">
              {trend && (
                <span className="inline-flex items-center gap-1 tabular-nums">
                  <TrendIcon trend={trend} />
                  {trendLabel}
                </span>
              )}
              {footnote && <span className="text-white/80 truncate">{footnote}</span>}
            </div>
            {sparkline && <MiniSparkline data={sparkline} stroke="rgba(255,255,255,0.9)" />}
          </div>
        )}
        {children}
      </motion.div>
    );
  }

  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}
      whileHover={{ y: -3 }}
      transition={{ type: 'spring', stiffness: 320, damping: 26 }}
      className={cn(
        'group relative bg-surface border border-line rounded-xl p-5 shadow-card hover:shadow-elevated transition-shadow',
        className
      )}
      style={{ borderLeft: `3px solid ${toneAccent[tone]}` }}
      {...props}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">{label}</span>
        {icon && (
          <div className={cn('flex items-center justify-center w-9 h-9 rounded-xl', toneChip[tone])}>
            {icon}
          </div>
        )}
      </div>
      <div className="text-3xl font-bold text-ink tabular-nums leading-tight">{value}</div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {trend && (
            <span
              className={cn(
                'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full tabular-nums font-medium',
                deltaChip[trend]
              )}
            >
              <TrendIcon trend={trend} />
              {trendLabel}
            </span>
          )}
          {footnote && <span className="text-xs text-ink-muted truncate">{footnote}</span>}
        </div>
        {sparkline && <MiniSparkline data={sparkline} stroke={sparkStroke(trend, tone)} />}
      </div>
      {children}
    </motion.div>
  );
}
