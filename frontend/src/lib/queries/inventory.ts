'use client';

/** TanStack Query hook for the inventory summary KPIs. Kept separate from the
 *  full inventory page (which layers an SSE stream on top) so lightweight
 *  consumers — the Today stock zone, dashboards — can share this one query. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface InventorySummaryLite {
  out_of_stock_count?: number;
  low_stock_count?: number;
  overstocked_count?: number;
  total_items?: number;
}

export const inventoryKeys = {
  all: ['inventory'] as const,
  summary: () => ['inventory', 'summary'] as const,
};

/** Store-inventory summary counts (out-of-stock, low, overstocked). */
export function useInventorySummary() {
  return useQuery<InventorySummaryLite>({
    queryKey: inventoryKeys.summary(),
    queryFn: () => apiRequest<InventorySummaryLite>('/api/inventory/summary', { ttl: 30000 }),
  });
}
