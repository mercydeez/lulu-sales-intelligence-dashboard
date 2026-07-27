/**
 * Product branding — single source of truth for the product name on the frontend.
 *
 * The product is "Retail Intelligence" (owner-confirmed). Change it here (or
 * set NEXT_PUBLIC_PRODUCT_NAME at build time) and every user-facing surface
 * updates from one place. Keep in sync with backend settings.product_name.
 * NOTE: "Meridian Hypermarket" is the fictional DEMO RETAILER (tenant data),
 * never the product name.
 */

export const PRODUCT_NAME: string =
  process.env.NEXT_PUBLIC_PRODUCT_NAME?.trim() || 'Retail Intelligence';

/** Short form for tight spaces (sidebar collapsed, favicons, etc.). */
export const PRODUCT_NAME_SHORT: string =
  process.env.NEXT_PUBLIC_PRODUCT_NAME_SHORT?.trim() || PRODUCT_NAME;

/** Tagline used on auth screens / marketing surfaces. */
export const PRODUCT_TAGLINE: string =
  process.env.NEXT_PUBLIC_PRODUCT_TAGLINE?.trim() ||
  'Retail operations intelligence';

/**
 * The AI assistant's name (NL->SQL diagnostic chatbot). Single source of truth
 * for the frontend; keep in sync with the backend settings.chatbot_name ("Sage").
 */
export const CHATBOT_NAME: string =
  process.env.NEXT_PUBLIC_CHATBOT_NAME?.trim() || 'Sage';
