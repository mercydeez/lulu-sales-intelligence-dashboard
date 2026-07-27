'use client';

/** TanStack Query hook for the daily briefing (persona verdict). */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

/** Subset of GET /api/briefing consumed by the Today verdict zone. The endpoint
 *  returns more; structural typing ignores the extra fields. */
export interface Briefing {
  greeting: string;
  tldr: string;
  headline: { summary: string };
}

export const briefingKeys = {
  all: ['briefing'] as const,
  briefing: () => ['briefing', 'daily'] as const,
};

export function useBriefing() {
  return useQuery<Briefing>({
    queryKey: briefingKeys.briefing(),
    queryFn: () => apiRequest<Briefing>('/api/briefing', { ttl: 60000 }),
  });
}
