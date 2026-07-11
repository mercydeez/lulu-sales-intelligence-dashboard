'use client';

/** TanStack Query hook for the ROI / value-summary page. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface Metric {
  aed?: number | null; value?: number | null; count?: number; per_day_aed?: number;
  projection_days?: number; label: string; needs?: string | null; is_estimate?: boolean;
  gross_margin_90d_aed?: number | null;
}
export interface RoiSummary {
  currency: string;
  metrics: Record<string, Metric>;
  context: {
    revenue_90d_aed: number; below_reorder_count: number; total_skus: number;
    total_stock_units: number; has_cost_data: boolean;
  };
  headline: { label: string; aed: number };
}

export const roiKeys = {
  all: ['roi'] as const,
  summary: () => ['roi', 'summary'] as const,
};

/** ROI summary (dead stock, stockout risk, margins). `enabled` gates on the
 *  inventory-visible roles the page checks. */
export function useRoiSummary(enabled: boolean) {
  return useQuery<RoiSummary>({
    queryKey: roiKeys.summary(),
    enabled,
    queryFn: () => apiRequest<RoiSummary>('/api/roi/summary', { ttl: 30000 }),
  });
}
