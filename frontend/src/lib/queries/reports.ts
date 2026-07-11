'use client';

/** TanStack Query hooks for the sales-reports page. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';
import type { SalesReport, ReportRange } from '@/components/reports';
import { REPORT_RANGE_DAYS } from '@/components/reports';

export const reportsKeys = {
  all: ['reports'] as const,
  sales: (range: ReportRange, storeId: number | null) =>
    ['reports', 'sales', range, storeId] as const,
};

/** Period sales report scoped to a range and (optionally) a single store. */
export function useSalesReport(range: ReportRange, storeId: number | null) {
  return useQuery<SalesReport>({
    queryKey: reportsKeys.sales(range, storeId),
    queryFn: () => {
      const params: Record<string, unknown> = { days: REPORT_RANGE_DAYS[range] };
      if (storeId) params.store_id = storeId;
      return apiRequest<SalesReport>('/api/reports/sales', { params, ttl: 30000 });
    },
  });
}
