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
import { fetchTopItems } from '@/lib/api';
import type { TopItemPoint } from '@/types';

export const analyticsKeys = {
  all: ['analytics'] as const,
  topItems: (limit: number) => ['analytics', 'top-items', limit] as const,
};

/** Top-selling items by revenue. */
export function useTopItems(limit = 10) {
  return useQuery<TopItemPoint[]>({
    queryKey: analyticsKeys.topItems(limit),
    queryFn: async () => (await fetchTopItems(limit)).data ?? [],
  });
}
