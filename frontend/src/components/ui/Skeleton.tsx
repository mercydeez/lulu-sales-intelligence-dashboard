import { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  width?: string;
  height?: string;
  rounded?: 'md' | 'lg' | 'full';
}

const roundedClasses = {
  md: 'rounded-md',
  lg: 'rounded-2xl',
  full: 'rounded-full',
};

export function Skeleton({ width, height = '1rem', rounded = 'md', className, style, ...props }: SkeletonProps) {
  return (
    <div
      className={cn('shimmer', roundedClasses[rounded], className)}
      style={{ width, height, ...style }}
      {...props}
    />
  );
}

/** Skeleton mimicking a KPI/stat card while data loads. */
export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn('glass rounded-2xl p-6', className)}>
      <Skeleton width="50%" height="0.875rem" className="mb-4" />
      <Skeleton width="75%" height="2rem" />
    </div>
  );
}

/** A handful of skeleton text lines, e.g. for table rows or paragraphs. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '60%' : '100%'} />
      ))}
    </div>
  );
}
