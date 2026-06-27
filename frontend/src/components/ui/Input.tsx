import { InputHTMLAttributes, ReactNode, forwardRef } from 'react';
import { cn } from '@/lib/cn';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  icon?: ReactNode;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, icon, error, className, id, ...props }, ref) => {
    return (
      <div>
        {label && (
          <label htmlFor={id} className="block text-sm font-medium text-ink-soft mb-2">
            {label}
          </label>
        )}
        <div className="relative group">
          {icon && (
            <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none text-ink-muted group-focus-within:text-teal-600 transition-colors">
              {icon}
            </div>
          )}
          <input
            ref={ref}
            id={id}
            className={cn(
              'w-full py-3 px-4 rounded-2xl bg-surface border text-ink placeholder-ink-muted shadow-sm transition-all',
              'focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-400',
              icon && 'ps-12',
              error ? 'border-rose-300' : 'border-line',
              className
            )}
            {...props}
          />
        </div>
        {error && <p className="mt-1.5 text-xs text-rose-600">{error}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';
