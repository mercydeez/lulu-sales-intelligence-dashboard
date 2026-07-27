export type DiscountType = 'percentage' | 'fixed' | 'bogo';
export type PromotionStatus = 'active' | 'scheduled' | 'ended' | 'draft';
export type PromotionTab = 'active' | 'scheduled' | 'ended' | 'all';

export interface Promotion {
  id: number;
  name: string;
  description: string;
  discount_type: DiscountType;
  discount_value: number;
  start_date: string;
  end_date: string;
  status: PromotionStatus;
  redemption_count: number;
  total_discount_given: number;
  category?: string | null;
  min_purchase?: number | null;
  max_discount?: number | null;
  days_remaining?: number;
  promotion_code?: string | null;
  source?: string;
}

export interface PromotionSummary {
  active_promotions: number;
  scheduled_promotions: number;
  ended_promotions: number;
  draft_promotions: number;
  total_discounts_given: number;
  total_redemptions: number;
  currency: string;
}

// Shape returned by GET /api/promotions/categories (real sales-derived data).
export interface CategoryPerformance {
  category: string;
  total_units: number;
  total_revenue: number;
  previous_units: number;
  growth_rate: number;
  // null outside demo mode: there is no promotion-event source to derive an
  // average discount from, and the product never invents one (B6).
  avg_discount: number | null;
  data_basis?: 'derived_from_sales' | 'demo_synthetic';
}
