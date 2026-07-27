import { SVGProps } from 'react';
import { PRODUCT_NAME } from '@/lib/brand';

export interface BrandIconProps extends Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'width' | 'height'> {
  /** pixel size (width & height); default 32 */
  size?: number | string;
  /** accessible label (ignored when `decorative`) */
  title?: string;
  /** render as decorative (aria-hidden, no title) — use when a sibling label exists */
  decorative?: boolean;
}

/**
 * Brand mark — ascending growth bars fused into a bold "R".
 *
 * Single-color (currentColor) so it adapts to context: set the color via
 * `className` (e.g. `text-[#17284B]`, `text-white`) or let it inherit. Geometry
 * lives here and in `public/branding/*.svg` — keep the two in sync if edited.
 */
export function BrandIcon({ size = 32, title = PRODUCT_NAME, decorative = false, ...props }: BrandIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="8 12 76 76"
      width={size}
      height={size}
      fill="currentColor"
      fillRule="evenodd"
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : title}
      {...props}
    >
      {!decorative && <title>{title}</title>}
      <path d="M18 64l10-10v24H18z" />
      <path d="M30 52l10-10v36H30z" />
      <path d="M42 18h10v60H42z" />
      <path d="M52 18h8c12 0 12 34 0 34h-8zM52 28h6c6 0 6 14 0 14h-6z" />
      <path d="M44 48h10l20 30H64z" />
    </svg>
  );
}
