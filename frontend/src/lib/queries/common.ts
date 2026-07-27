'use client';

/** Shared, cross-domain query hooks (reference data used by many pages). */
import { useQuery } from '@tanstack/react-query';
import { fetchStores } from '@/lib/api';
import type { Store } from '@/types';

export const commonKeys = {
  stores: () => ['common', 'stores'] as const,
};

/** Store list — reference data; long staleTime since it rarely changes. */
export function useStores() {
  return useQuery<Store[]>({
    queryKey: commonKeys.stores(),
    queryFn: () => fetchStores(),
    staleTime: 300000,
  });
}
