import { HTMLAttributes, ReactNode } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface MetricItem {
  key: string;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  /** subtle emphasis for a value that carries risk/AED-at-stake framing */
  tone?: 'default' | 'amber' | 'brand';
  /** optional directional cue; never color-only (icon + text) */
  trend?: 'up' | 'down' | 'flat';
}

export interface MetricStripProps extends HTMLAttributes<HTMLDivElement> {
  items: MetricItem[];
}

const TREND = {
  up: { Icon: TrendingUp, cls: 'text-emerald-600' },
  down: { Icon: TrendingDown, cls: 'text-rose-600' },
  flat: { Icon: Minus, cls: 'text-ink-muted' },
};

/**
 * Metric strip — orient quickly beneath a page header or hero. 3–6 items, shared
 * alignment, tabular numerals (COMPONENT_LIBRARY §4.4, DESIGN_SYSTEM §8.3).
 * Never mix units and AED in one item without clear separation.
 */
export function MetricStrip({ items, className, ...props }: MetricStripProps) {
  return (
    <div
      className={cn('grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3', className)}
      {...props}
    >
      {items.slice(0, 6).map((m) => {
        const t = m.trend ? TREND[m.trend] : null;
        return (
          <div key={m.key} className="rounded-2xl bg-surface border border-line shadow-card p-3.5">
            <p className="text-[11px] uppercase tracking-widest text-ink-muted">{m.label}</p>
            <p className={cn(
              'mt-1 text-lg font-bold tabular-nums flex items-center gap-1.5',
              m.tone === 'amber' ? 'text-amber-700' : m.tone === 'brand' ? 'text-teal-700' : 'text-ink',
            )}>
              {t && <t.Icon className={cn('w-4 h-4', t.cls)} />}
              {m.value}
            </p>
            {m.sub && <p className="text-[11px] text-ink-muted mt-0.5">{m.sub}</p>}
          </div>
        );
      })}
    </div>
  );
}
