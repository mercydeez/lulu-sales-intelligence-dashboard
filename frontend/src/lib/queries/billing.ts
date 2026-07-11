'use client';

/**
 * TanStack Query hooks for billing/plan data. Same conventions as
 * lib/queries/analytics.ts (see that file for the query-key rationale).
 */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface Plan {
  plan: string;
  tagline: string;
  monthly_price_aed: number | null;
  custom_pricing: boolean;
  limits: { users: number | null; api_requests_month: number | null; sage_messages_month: number | null };
  features: string[];
}

export const billingKeys = {
  all: ['billing'] as const,
  plans: () => ['billing', 'plans'] as const,
};

/** Public plan catalogue for the pricing page. */
export function usePlans() {
  return useQuery<Plan[]>({
    queryKey: billingKeys.plans(),
    queryFn: async () => {
      const res = await apiRequest<{ plans?: Plan[] }>('/api/billing/plans', { ttl: 300000 });
      return res.plans ?? [];
    },
    staleTime: 300000, // plan catalogue rarely changes
  });
}
