import { describe, it, expect } from 'vitest';
import {
  formatCurrency,
  formatCurrencyCompact,
  formatQuantity,
  formatNumber,
  CURRENCY_CODE,
} from './formatters';

// These guard the units-vs-AED honesty convention at the formatting layer:
// VALUE metrics carry the AED currency code; VOLUME metrics carry a unit label.
describe('formatters — units vs AED', () => {
  it('formatCurrency labels values with the AED code', () => {
    expect(CURRENCY_CODE).toBe('AED');
    expect(formatCurrency(1234.5)).toContain('AED');
    expect(formatCurrency(1234.5, false)).not.toContain('AED');
  });

  it('formatQuantity labels volumes with a unit, never AED', () => {
    const out = formatQuantity(2500);
    expect(out).toContain('Units');
    expect(out).not.toContain('AED');
  });

  it('formatQuantity honors explicit unit kinds', () => {
    expect(formatQuantity(10, 'TRANSACTIONS')).toContain('Txns');
    expect(formatQuantity(3, 'RETURNS')).toContain('Returns');
  });

  it('compact formatters use K/M/B suffixes', () => {
    expect(formatCurrencyCompact(2_500_000)).toBe('AED 2.5M');
    expect(formatNumber(1_500)).toBe('1.5K');
    expect(formatNumber(3_200_000_000)).toBe('3.2B');
  });
});
