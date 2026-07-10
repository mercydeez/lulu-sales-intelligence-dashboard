import type { BadgeVariant } from '@/components/ui';

/**
 * Severity → color, once.
 *
 * The single source of truth for how critical/high/medium/low read across the
 * product (badges, accent bars, chips, text). Previously three files carried
 * conflicting maps (inventory badges said high=coral; the copilot feed said
 * high=orange — off the brand palette entirely). The inventory mapping wins:
 *
 *   critical → rose · high → coral · medium → amber · low → teal
 *
 * Dark mode: accents use the --a-* channel vars (brightened by html.dark), and
 * the tinted classes are remapped by the globals.css dark compat shim.
 */
export type Severity = 'critical' | 'high' | 'medium' | 'low';

/** Badge variant per severity (mirrors ui/Badge's palette). */
export const SEVERITY_BADGE: Record<Severity, BadgeVariant> = {
  critical: 'danger',
  high: 'coral',
  medium: 'warning',
  low: 'teal',
};

/** CSS color values for accent bars / inline style props (themeable). */
export const SEVERITY_ACCENT: Record<Severity, string> = {
  critical: '#f43f5e',
  high: 'rgb(var(--a-coral))',
  medium: 'rgb(var(--a-amber))',
  low: 'rgb(var(--a-teal))',
};

/** Ring-pill classes (the copilot/briefing chip idiom). */
export const SEVERITY_CHIP: Record<Severity, string> = {
  critical: 'bg-rose-50 text-rose-700 ring-rose-200',
  high: 'bg-coral-50 text-coral-700 ring-coral-200',
  medium: 'bg-amber-50 text-amber-700 ring-amber-200',
  low: 'bg-teal-50 text-teal-700 ring-teal-200',
};

/** Plain text emphasis per severity (dark mode handled by the compat shim). */
export const SEVERITY_TEXT: Record<Severity, string> = {
  critical: 'text-rose-600 dark:text-rose-400',
  high: 'text-coral-600',
  medium: 'text-amber-600 dark:text-amber-400',
  low: 'text-teal-600 dark:text-teal-300',
};

/** Solid status dots (literal classes so the Tailwind JIT emits them — never
 *  build these with string surgery like `.replace('text-','bg-')`). */
export const SEVERITY_DOT: Record<Severity, string> = {
  critical: 'bg-rose-500',
  high: 'bg-coral-500',
  medium: 'bg-amber-500',
  low: 'bg-teal-500',
};

/** Safe lookup for API-sourced severity strings (unknown → low). */
export const severityAccent = (sev: string): string =>
  SEVERITY_ACCENT[sev as Severity] ?? SEVERITY_ACCENT.low;

export const severityDot = (sev: string): string =>
  SEVERITY_DOT[sev as Severity] ?? SEVERITY_DOT.low;

/**
 * Feed-action priority chips (urgent/high/normal/low). Priorities ride the same
 * scale — urgent reads as critical, normal as calm brand, low as muted.
 */
export const PRIORITY_CHIP: Record<'urgent' | 'high' | 'normal' | 'low', string> = {
  urgent: SEVERITY_CHIP.critical,
  high: SEVERITY_CHIP.high,
  normal: SEVERITY_CHIP.low,
  low: 'bg-surface-2 text-ink-muted ring-line',
};
