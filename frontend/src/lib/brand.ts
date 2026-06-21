/**
 * Product branding — single source of truth for the product name on the frontend.
 *
 * Product name is "Foresia". Override at build time with NEXT_PUBLIC_PRODUCT_NAME
 * (and the short/tagline vars below) and every user-facing surface updates from
 * one place. The AI assistant is named "Sage" (see ai_assistant.py / ChatBot).
 */

export const PRODUCT_NAME: string =
  process.env.NEXT_PUBLIC_PRODUCT_NAME?.trim() || 'Foresia';

/** Short form for tight spaces (sidebar collapsed, favicons, etc.). */
export const PRODUCT_NAME_SHORT: string =
  process.env.NEXT_PUBLIC_PRODUCT_NAME_SHORT?.trim() || PRODUCT_NAME;

/** Tagline used on auth screens / marketing surfaces. */
export const PRODUCT_TAGLINE: string =
  process.env.NEXT_PUBLIC_PRODUCT_TAGLINE?.trim() ||
  'Anticipatory retail intelligence';
