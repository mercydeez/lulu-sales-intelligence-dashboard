/**
 * Formatting utilities for Lulu Intelligence Dashboard
 * Includes AED (UAE Dirhams) currency formatting and standardized unit labels
 * Following enterprise standards similar to Apple, Microsoft, and major retailers
 */

// Currency code for UAE Dirhams
export const CURRENCY_CODE = 'AED';
export const CURRENCY_SYMBOL = 'د.إ';
export const CURRENCY_LOCALE = 'en-AE';

/**
 * Format a number as AED currency
 * @param value - The numeric value to format
 * @param showSymbol - Whether to show currency symbol (default: true)
 * @returns Formatted currency string
 */
export const formatCurrency = (value: number, showSymbol: boolean = true): string => {
  const formatted = value.toLocaleString(CURRENCY_LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return showSymbol ? `${CURRENCY_CODE} ${formatted}` : formatted;
};

/**
 * Format a number with compact notation (K, M, B) with AED
 * @param value - The numeric value to format
 * @returns Formatted compact currency string
 */
export const formatCurrencyCompact = (value: number): string => {
  if (value >= 1_000_000_000) {
    return `${CURRENCY_CODE} ${(value / 1_000_000_000).toFixed(1)}B`;
  }
  if (value >= 1_000_000) {
    return `${CURRENCY_CODE} ${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${CURRENCY_CODE} ${(value / 1_000).toFixed(1)}K`;
  }
  return formatCurrency(value);
};

/**
 * Standard unit labels following enterprise conventions (Apple, Microsoft style)
 */
export const UNIT_LABELS = {
  UNITS: 'Units',
  QTY: 'Qty',
  PIECES: 'Pcs',
  ITEMS: 'Items',
  TRANSACTIONS: 'Txns',
  RETURNS: 'Returns',
} as const;

/**
 * Format a quantity/units value with appropriate suffix
 * @param value - The numeric value
 * @param unit - The unit type (default: 'Units')
 * @returns Formatted string with unit
 */
export const formatQuantity = (value: number, unit: keyof typeof UNIT_LABELS = 'UNITS'): string => {
  return `${value.toLocaleString()} ${UNIT_LABELS[unit]}`;
};

/**
 * Format a number with compact notation (K, M, B)
 * @param value - The numeric value
 * @returns Formatted compact string
 */
export const formatNumber = (value: number): string => {
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}B`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return value.toLocaleString();
};

/**
 * Format a quantity with compact notation and unit
 * @param value - The numeric value
 * @param unit - The unit type (default: 'Units')
 * @returns Formatted compact string with unit
 */
export const formatQuantityCompact = (value: number, unit: keyof typeof UNIT_LABELS = 'UNITS'): string => {
  return `${formatNumber(value)} ${UNIT_LABELS[unit]}`;
};

/**
 * Format percentage with precision
 * @param value - The percentage value (0-100)
 * @param decimals - Number of decimal places (default: 1)
 * @returns Formatted percentage string
 */
export const formatPercentage = (value: number, decimals: number = 1): string => {
  return `${value.toFixed(decimals)}%`;
};
