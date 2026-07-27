import { SelectHTMLAttributes, forwardRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, className, id, children, ...props }, ref) => {
    return (
      <div>
        {label && (
          <label htmlFor={id} className="block text-sm font-medium text-ink-soft mb-2">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={id}
            className={cn(
              'w-full py-3 px-4 pe-10 rounded-2xl bg-surface border text-ink shadow-sm transition-all appearance-none',
              'focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-400',
              error ? 'border-rose-300' : 'border-line',
              className
            )}
            {...props}
          >
            {children}
          </select>
          <ChevronDown className="absolute end-4 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-muted pointer-events-none" />
        </div>
        {error && <p className="mt-1.5 text-xs text-rose-600">{error}</p>}
      </div>
    );
  }
);

Select.displayName = 'Select';
