import { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export interface HomeTemplateProps {
  /** focal hero verdict/summary (HeroVerdict) */
  hero?: ReactNode;
  /** compact metric strip beneath the hero (MetricStrip) */
  metrics?: ReactNode;
  /** 2–4 priority modules + a supporting AI/workflow module */
  children?: ReactNode;
  /** trailing signature/footer line */
  footer?: ReactNode;
  className?: string;
  /** comfortable (Home/Briefing/Copilot) vs compact reading width */
  width?: 'comfortable' | 'wide';
}

/**
 * Home template (DESIGN_SYSTEM §6.1): hero verdict → metric strip → priority
 * modules → supporting module. One structure for Today, Executive Briefing, and
 * Sage Copilot so they read as one system. Generous whitespace, single reading
 * column (VISUAL_LANGUAGE §6).
 */
export function HomeTemplate({
  hero, metrics, children, footer, className, width = 'comfortable',
}: HomeTemplateProps) {
  return (
    <main className={cn('min-h-screen px-4 md:px-8 py-6 md:py-10', className)}>
      <div className={cn('mx-auto space-y-6', width === 'wide' ? 'max-w-5xl' : 'max-w-3xl')}>
        {hero}
        {metrics}
        {children}
        {footer && <div className="pt-2">{footer}</div>}
      </div>
    </main>
  );
}
