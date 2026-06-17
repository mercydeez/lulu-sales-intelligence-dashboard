import { HTMLAttributes, forwardRef } from 'react';
import { cn } from '@/lib/cn';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** 'glass' = translucent panel (default), 'solid' = opaque white panel */
  variant?: 'glass' | 'solid';
  /** lift-on-hover treatment for interactive/clickable cards */
  hover?: 'none' | 'lift' | 'pop';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const paddingClasses = {
  none: '',
  sm: 'p-4',
  md: 'p-6',
  lg: 'p-8',
};

const hoverClasses = {
  none: '',
  lift: 'card-hover',
  pop: 'card-pop',
};

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ variant = 'glass', hover = 'none', padding = 'md', className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'rounded-2xl',
          variant === 'glass' ? 'glass' : 'bg-white border border-coral-100 shadow-soft',
          hoverClasses[hover],
          paddingClasses[padding],
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);

Card.displayName = 'Card';

export function CardHeader({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('flex items-center justify-between mb-4', className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-lg font-semibold text-ink', className)} {...props}>
      {children}
    </h3>
  );
}
