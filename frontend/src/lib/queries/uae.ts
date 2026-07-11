'use client';

/** TanStack Query hooks for the UAE-intelligence page (calendar, emirate
 *  performance, transfer suggestions, dead stock). */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface CalEvent {
  key: string; name: string; start: string; end: string; approx: boolean;
  note: string; active?: boolean; days_until?: number;
}
export interface Emirate { emirate: string; units: number; revenue_aed: number; stores: number; }
export interface Transfer { item_name: string; from_store: string; to_store: string; suggested_qty: number; reason: string; }
export interface DeadEmirate { emirate: string; dead_value_aed: number; dead_skus: number; }

export const uaeKeys = {
  all: ['uae'] as const,
  calendar: () => ['uae', 'calendar'] as const,
  emirates: () => ['uae', 'emirate-performance'] as const,
  transfers: () => ['uae', 'transfer-suggestions'] as const,
  deadStock: () => ['uae', 'dead-stock'] as const,
};

const TTL = 60000; // these are day-scale aggregates; 1-min cache is plenty

/** Everything the UAE-insights screen needs, as four deduped queries surfaced
 *  through one hook so the page keeps its simple {list, loading} shape. */
interface UaeInsights {
  upcoming: CalEvent[];
  emirates: Emirate[];
  transfers: Transfer[];
  dead: DeadEmirate[];
  loading: boolean;
}

export function useUaeInsights(): UaeInsights {
  const calendar = useQuery<{ upcoming?: CalEvent[] }>({
    queryKey: uaeKeys.calendar(),
    queryFn: () => apiRequest<{ upcoming?: CalEvent[] }>('/api/uae-intelligence/calendar', { ttl: TTL }),
  });
  const emirates = useQuery<{ emirates?: Emirate[] }>({
    queryKey: uaeKeys.emirates(),
    queryFn: () => apiRequest<{ emirates?: Emirate[] }>('/api/uae-intelligence/emirate-performance', { ttl: TTL }),
  });
  const transfers = useQuery<{ suggestions?: Transfer[] }>({
    queryKey: uaeKeys.transfers(),
    queryFn: () => apiRequest<{ suggestions?: Transfer[] }>('/api/uae-intelligence/transfer-suggestions', { ttl: TTL }),
  });
  const dead = useQuery<{ emirates?: DeadEmirate[] }>({
    queryKey: uaeKeys.deadStock(),
    queryFn: () => apiRequest<{ emirates?: DeadEmirate[] }>('/api/uae-intelligence/dead-stock-by-emirate', { ttl: TTL }),
  });

  return {
    upcoming: calendar.data?.upcoming ?? [],
    emirates: emirates.data?.emirates ?? [],
    transfers: transfers.data?.suggestions ?? [],
    dead: dead.data?.emirates ?? [],
    loading: calendar.isLoading || emirates.isLoading || transfers.isLoading || dead.isLoading,
  };
}
