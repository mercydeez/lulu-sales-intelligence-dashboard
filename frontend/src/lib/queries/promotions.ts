'use client';

/** TanStack Query hooks for the promotions page. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';
import type { Promotion, PromotionSummary, CategoryPerformance, PromotionTab } from '@/components/promotions';

export const promotionsKeys = {
  all: ['promotions'] as const,
  overview: () => ['promotions', 'overview'] as const,
  list: (status: string) => ['promotions', 'list', status] as const,
};

interface PromotionOverview {
  summary: PromotionSummary | null;
  activePromotions: Promotion[];
  categories: CategoryPerformance[];
  loading: boolean;
}

/** Summary + active promotions + category performance behind one hook. */
export function usePromotionOverview(): PromotionOverview {
  const summary = useQuery<PromotionSummary>({
    queryKey: [...promotionsKeys.overview(), 'summary'],
    queryFn: () => apiRequest<PromotionSummary>('/api/promotions/summary', { ttl: 60000 }),
  });
  const active = useQuery<{ promotions?: Promotion[] }>({
    queryKey: [...promotionsKeys.overview(), 'active'],
    queryFn: () => apiRequest<{ promotions?: Promotion[] }>('/api/promotions/active', { ttl: 60000 }),
  });
  const categories = useQuery<{ categories?: CategoryPerformance[] }>({
    queryKey: [...promotionsKeys.overview(), 'categories'],
    queryFn: () => apiRequest<{ categories?: CategoryPerformance[] }>('/api/promotions/categories', { ttl: 60000 }),
  });

  return {
    summary: summary.data ?? null,
    activePromotions: active.data?.promotions ?? [],
    categories: categories.data?.categories ?? [],
    loading: summary.isLoading || active.isLoading || categories.isLoading,
  };
}

/** Full promotions list for a tab/status ('' = all). */
export function usePromotionList(status: PromotionTab) {
  const statusParam = status === 'all' ? '' : status;
  return useQuery<Promotion[]>({
    queryKey: promotionsKeys.list(statusParam),
    queryFn: async () => {
      const res = await apiRequest<{ promotions?: Promotion[] }>('/api/promotions/list', {
        params: { status: statusParam, limit: 100 },
        ttl: 30000,
      });
      return res.promotions ?? [];
    },
  });
}
