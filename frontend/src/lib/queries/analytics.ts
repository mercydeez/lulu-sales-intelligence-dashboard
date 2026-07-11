'use client';

/**
 * TanStack Query hooks for analytics data.
 *
 * These wrap the existing typed fetchers in `lib/api.ts` (which go through
 * `lib/apiClient.ts` for auth/CSRF/refresh) so a component gets dedup, SWR,
 * background refetch and error/loading state for free — replacing the hand-rolled
 * `useEffect`+useState triad. This module is the REFERENCE PATTERN; add a hook
 * here per endpoint and migrate pages to it incrementally.
 *
 * Query-key convention: `['<domain>', '<resource>', ...params]` so related keys
 * invalidate together (e.g. `queryClient.invalidateQueries({ queryKey: ['analytics'] })`).
 */
import { useQuery } from '@tanstack/react-query';
import { fetchTopItems, fetchStoreDistribution, fetchCategoryBreakdown, fetchTrend } from '@/lib/api';
import type { TopItemPoint, StoreDistributionPoint, CategoryBreakdownPoint, TrendPoint } from '@/types';

export const analyticsKeys = {
  all: ['analytics'] as const,
  topItems: (limit: number) => ['analytics', 'top-items', limit] as const,
  storeDistribution: () => ['analytics', 'store-distribution'] as const,
  categoryBreakdown: () => ['analytics', 'category-breakdown'] as const,
  trend: (days: number, forecast: boolean) => ['analytics', 'trend', days, forecast] as const,
};

/** Daily sales trend. Query-keyed so panels that fetch the same window (chart +
 *  KPI sparkline) DEDUP to one request — a concrete win of the reactive layer. */
export function useSalesTrend(days = 30, includeForecast = true) {
  return useQuery<TrendPoint[]>({
    queryKey: analyticsKeys.trend(days, includeForecast),
    queryFn: async () => (await fetchTrend(days, includeForecast)).data ?? [],
  });
}

/** Top-selling items by revenue. */
export function useTopItems(limit = 10) {
  return useQuery<TopItemPoint[]>({
    queryKey: analyticsKeys.topItems(limit),
    queryFn: async () => (await fetchTopItems(limit)).data ?? [],
  });
}

/** Revenue distribution across stores. */
export function useStoreDistribution() {
  return useQuery<StoreDistributionPoint[]>({
    queryKey: analyticsKeys.storeDistribution(),
    queryFn: async () => (await fetchStoreDistribution()).data ?? [],
  });
}

/** Revenue breakdown by category. */
export function useCategoryBreakdown() {
  return useQuery<CategoryBreakdownPoint[]>({
    queryKey: analyticsKeys.categoryBreakdown(),
    queryFn: async () => (await fetchCategoryBreakdown()).data ?? [],
  });
}
