import { CSSProperties } from 'react';
import { cn } from '@/lib/cn';
import { BrandIcon } from './BrandIcon';

export type LogoVariant = 'default' | 'dark' | 'mono';

export interface LogoProps {
  /** color treatment. default = navy + blue (auto-flips to white in dark mode);
   *  dark = force white + blue (for colored/photographic backgrounds);
   *  mono = single currentColor (inherits text color) */
  variant?: LogoVariant;
  /** icon box size in px; the wordmark scales from it. default 32 */
  size?: number;
  /** icon only, no wordmark */
  iconOnly?: boolean;
  className?: string;
  title?: string;
}

const ICON_COLOR: Record<LogoVariant, string> = {
  default: 'text-[#17284B] dark:text-white',
  dark: 'text-white',
  mono: 'text-current',
};
const RETAIL_COLOR: Record<LogoVariant, string> = {
  default: 'text-[#17284B] dark:text-white',
  dark: 'text-white',
  mono: 'text-current',
};
const IQ_COLOR: Record<LogoVariant, string> = {
  default: 'text-[#2563EB] dark:text-[#3B82F6]',
  dark: 'text-[#3B82F6]',
  mono: 'text-current',
};

/**
 * RetailIQ lockup — <BrandIcon/> + the "RetailIQ" wordmark, set in the app font
 * (Manrope) so it stays crisp at any size and needs no font embedding. Proportions
 * mirror `public/branding/retailiq-logo.svg`. Use `iconOnly` for tight spaces.
 */
export function Logo({ variant = 'default', size = 32, iconOnly = false, className, title = 'RetailIQ' }: LogoProps) {
  const wordStyle: CSSProperties = { fontSize: Math.round(size * 0.5), letterSpacing: '-0.02em' };
  return (
    <span
      className={cn('inline-flex items-center select-none', className)}
      style={{ gap: Math.round(size * 0.22) }}
      role="img"
      aria-label={title}
    >
      <BrandIcon size={size} decorative className={cn('shrink-0', ICON_COLOR[variant])} />
      {!iconOnly && (
        <span className="font-extrabold leading-none" style={wordStyle}>
          <span className={RETAIL_COLOR[variant]}>Retail</span>
          <span className={IQ_COLOR[variant]}>IQ</span>
        </span>
      )}
    </span>
  );
}
