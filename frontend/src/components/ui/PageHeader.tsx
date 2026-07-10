import { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface PageHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  eyebrow?: string;
}

export function PageHeader({ title, description, icon, actions, eyebrow, className, ...props }: PageHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-4 mb-6', className)} {...props}>
      <div className="flex items-start gap-3">
        {icon && (
          <div className="w-11 h-11 rounded-xl bg-teal-50 text-teal-700 ring-1 ring-teal-100 dark:bg-teal-500/10 dark:text-teal-300 dark:ring-teal-500/20 flex items-center justify-center shrink-0">
            {icon}
          </div>
        )}
        <div className="space-y-1">
          {eyebrow && (
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
              {eyebrow}
            </p>
          )}
          <h1 className="text-2xl font-bold text-ink">{title}</h1>
          {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">{actions}</div>}
    </div>
  );
}
