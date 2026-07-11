'use client';

/** TanStack Query hooks for decision triage. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface TriageDecision {
  id: number | null;
  severity: string;
  problem: string;
  impact: { aed: number | null; units: number | null; per: string | null };
  recommended_action: string;
  href?: string;
  kind?: string;
}
export interface DecisionTriage {
  total: number;
  executive: { decisions: TriageDecision[] };
}

export const decisionsKeys = {
  all: ['decisions'] as const,
  triage: () => ['decisions', 'triage'] as const,
};

/** Role-scoped decision triage (executive band). */
export function useDecisionTriage() {
  return useQuery<DecisionTriage>({
    queryKey: decisionsKeys.triage(),
    queryFn: () => apiRequest<DecisionTriage>('/api/decisions/triage', { ttl: 30000 }),
  });
}
