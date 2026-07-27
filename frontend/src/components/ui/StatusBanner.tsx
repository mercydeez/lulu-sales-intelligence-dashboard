import { HTMLAttributes, ReactNode } from 'react';
import { Info, CheckCircle2, AlertTriangle, WifiOff, XCircle } from 'lucide-react';
import { cn } from '@/lib/cn';

export type StatusBannerVariant = 'info' | 'success' | 'warning' | 'degraded' | 'error';

export interface StatusBannerProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  variant?: StatusBannerVariant;
  title?: ReactNode;
  children?: ReactNode;
  /** optional trailing action (e.g. a retry / reconnect button) */
  action?: ReactNode;
}

const VARIANT: Record<StatusBannerVariant, { icon: typeof Info; cls: string; iconCls: string }> = {
  info:     { icon: Info,          cls: 'bg-blue-50 text-blue-800 ring-blue-200',           iconCls: 'text-blue-600' },
  success:  { icon: CheckCircle2,  cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200',  iconCls: 'text-emerald-600' },
  warning:  { icon: AlertTriangle, cls: 'bg-amber-50 text-amber-800 ring-amber-200',         iconCls: 'text-amber-600' },
  degraded: { icon: WifiOff,       cls: 'bg-amber-50 text-amber-800 ring-amber-200',         iconCls: 'text-amber-600' },
  error:    { icon: XCircle,       cls: 'bg-rose-50 text-rose-800 ring-rose-200',            iconCls: 'text-rose-600' },
};

/**
 * Inline status/trust banner for page-level system messages — info, success,
 * warning, degraded (live-connection), and error (COMPONENT_LIBRARY §10.1).
 * Uses semantic tones with an icon so state never relies on color alone
 * (VISUAL_LANGUAGE §11).
 */
export function StatusBanner({
  variant = 'info', title, children, action, className, ...props
}: StatusBannerProps) {
  const v = VARIANT[variant];
  const Icon = v.icon;
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={cn('flex items-start gap-3 rounded-2xl ring-1 px-4 py-3', v.cls, className)}
      {...props}
    >
      <Icon className={cn('w-5 h-5 mt-0.5 shrink-0', v.iconCls)} />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn('leading-relaxed', title && 'mt-0.5 opacity-90')}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
