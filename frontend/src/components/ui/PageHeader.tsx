import { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface PageHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  icon?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, description, icon, actions, className, ...props }: PageHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-4 mb-6', className)} {...props}>
      <div className="flex items-start gap-3">
        {icon && (
          <div className="w-11 h-11 rounded-2xl sunset-gradient flex items-center justify-center text-white shrink-0 shadow-sunset">
            {icon}
          </div>
        )}
        <div>
          <h1 className="text-2xl font-bold text-ink">{title}</h1>
          {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
