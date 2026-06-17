import { BadgeVariant } from '@/components/ui';
import { DiscountType, Promotion, PromotionStatus } from './types';

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-AE', {
    style: 'currency',
    currency: 'AED',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value || 0);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-AE').format(value || 0);
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-AE', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function discountDisplay(promo: Pick<Promotion, 'discount_type' | 'discount_value'>): string {
  switch (promo.discount_type) {
    case 'percentage':
      return `${promo.discount_value}% OFF`;
    case 'fixed':
      return `${formatCurrency(promo.discount_value)} OFF`;
    case 'bogo':
      return 'BUY 1 GET 1';
    default:
      return `${promo.discount_value}% OFF`;
  }
}

export const discountTypeLabels: Record<DiscountType, string> = {
  percentage: 'Percentage Off',
  fixed: 'Fixed Amount',
  bogo: 'Buy One Get One',
};

export function statusVariant(status: PromotionStatus): BadgeVariant {
  switch (status) {
    case 'active':
      return 'success';
    case 'scheduled':
      return 'violet';
    case 'draft':
      return 'warning';
    case 'ended':
    default:
      return 'neutral';
  }
}

/** Days until the promotion ends (negative/zero clamped to 0). */
export function daysRemaining(promo: Pick<Promotion, 'end_date' | 'days_remaining'>): number {
  if (typeof promo.days_remaining === 'number') return Math.max(0, promo.days_remaining);
  const end = new Date(promo.end_date).getTime();
  if (Number.isNaN(end)) return 0;
  return Math.max(0, Math.ceil((end - Date.now()) / (1000 * 60 * 60 * 24)));
}
