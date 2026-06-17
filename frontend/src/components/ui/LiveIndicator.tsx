import { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export type LiveIndicatorTone = 'teal' | 'coral' | 'rose' | 'violet';

export interface LiveIndicatorProps extends HTMLAttributes<HTMLSpanElement> {
  label?: string;
  tone?: LiveIndicatorTone;
  size?: 'sm' | 'md';
}

const dotClasses: Record<LiveIndicatorTone, string> = {
  teal: 'bg-teal-400',
  coral: 'bg-coral-400',
  rose: 'bg-rose-400',
  violet: 'bg-violet-400',
};

const solidDotClasses: Record<LiveIndicatorTone, string> = {
  teal: 'bg-teal-500',
  coral: 'bg-coral-500',
  rose: 'bg-rose-500',
  violet: 'bg-violet-500',
};

const textClasses: Record<LiveIndicatorTone, string> = {
  teal: 'text-teal-600',
  coral: 'text-coral-600',
  rose: 'text-rose-600',
  violet: 'text-violet-600',
};

/** Pulsing dot + label, e.g. for "LIVE" badges next to streaming data. */
export function LiveIndicator({ label = 'LIVE', tone = 'teal', size = 'md', className, ...props }: LiveIndicatorProps) {
  const dotSize = size === 'sm' ? 'h-1.5 w-1.5' : 'h-2 w-2';
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)} {...props}>
      <span className={cn('relative flex', dotSize)}>
        <span className={cn('animate-ping absolute inline-flex h-full w-full rounded-full opacity-75', dotClasses[tone])} />
        <span className={cn('relative inline-flex rounded-full h-full w-full', solidDotClasses[tone])} />
      </span>
      {label && (
        <span className={cn('font-medium uppercase tracking-wide', size === 'sm' ? 'text-[10px]' : 'text-xs', textClasses[tone])}>
          {label}
        </span>
      )}
    </span>
  );
}
