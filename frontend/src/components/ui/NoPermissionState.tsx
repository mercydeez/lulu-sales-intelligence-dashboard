import { HTMLAttributes, ReactNode } from 'react';
import Link from 'next/link';
import { Lock } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface NoPermissionStateProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  /** State the boundary plainly; never leak the hidden values (DESIGN_SYSTEM §10). */
  description?: ReactNode;
  /** Where to send the user next (e.g. back to Today, or who can grant access). */
  actionHref?: string;
  actionLabel?: string;
}

/**
 * No-permission state — respects the backend's role boundary clearly and offers
 * a way out, without hinting at data the user isn't allowed to see.
 */
export function NoPermissionState({
  title = 'You don’t have access to this',
  description = 'This area is limited by your role. If you need it, ask a workspace admin to grant access.',
  actionHref = '/today',
  actionLabel = 'Back to Today',
  className,
  ...props
}: NoPermissionStateProps) {
  return (
    <div
      role="status"
      className={cn('flex flex-col items-center justify-center text-center py-12 px-6', className)}
      {...props}
    >
      <div className="w-14 h-14 rounded-2xl bg-surface-2 text-ink-muted flex items-center justify-center mb-4">
        <Lock className="w-7 h-7" />
      </div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description && <p className="text-sm text-ink-muted mt-1 max-w-sm">{description}</p>}
      {actionHref && (
        <Link
          href={actionHref}
          className="mt-5 inline-flex items-center gap-2 px-4 py-2 rounded-2xl bg-surface border border-line text-ink font-semibold text-sm hover:border-teal-300 hover:bg-teal-50 transition-colors"
        >
          {actionLabel}
        </Link>
      )}
    </div>
  );
}
