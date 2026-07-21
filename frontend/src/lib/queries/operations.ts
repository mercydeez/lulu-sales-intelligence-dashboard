'use client';

/**
 * TanStack Query hooks for the Operations Copilot (Phase 4).
 *
 * Mirrors lib/queries/procurement.ts: typed useQuery/useMutation over apiRequest,
 * and every decision mutation invalidates the ['operations'] tree so the queue,
 * metrics, and the open run all refetch without a hand-rolled reload. The
 * idempotency key is minted client-side per attempt (crypto.randomUUID) so a
 * double-click can't double-approve.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

// ---------------------------------------------------------------------------
// Types — match backend/app/routes/operations.py
// ---------------------------------------------------------------------------

export interface Evidence {
  evidence_id: string;
  metric_name: string;
  current_value: number | string | null;
  comparison_value?: number | string | null;
  comparison_period?: string | null;
  unit: string | null;
  source_type: string;           // 'derived' | 'inventory' | 'measured' | ...
  source_reference: string | null;
  observed_at: string | null;
}

export interface ProposedAction {
  action_type: string;
  title: string;
  description?: string;
  target_store_ids?: number[];
  target_item_ids?: number[];
  calculated_parameters?: Record<string, unknown>;
  expected_effect?: string;
  expected_effect_basis?: string;
  risk_level?: string;
  reversible?: boolean;
  required_approval_role?: string;
  prerequisites?: string[];
  expires_at?: string | null;
  evidence_ids?: string[];
}

export interface MeasuredFact { statement: string; evidence_ids?: string[]; }
export interface Hypothesis { statement: string; check?: string; supporting_evidence_ids?: string[]; }

export interface MeasurementPlan {
  metric_name?: string;
  baseline_value?: number | string | null;
  unit?: string | null;
  window_days?: number | null;
  success_criterion?: string | null;
}

export interface Recommendation {
  title?: string;
  executive_summary?: string;
  severity?: string;
  confidence?: number;
  measured_facts?: MeasuredFact[];
  hypotheses?: Hypothesis[];
  evidence?: Evidence[];
  proposed_actions?: ProposedAction[];
  assumptions?: string[];
  risks?: string[];
  missing_data?: string[];
  approval_requirement?: { required_role?: string; reason?: string; scope_store_ids?: number[] };
  measurement_plan?: MeasurementPlan;
  refusal_reason?: string | null;
  llm_available?: boolean;
}

/** Queue item as returned by /briefing.awaiting_approval (no recommendation/status). */
export interface Proposal {
  id: number;
  run_id: number;
  action_type: string;
  status?: string;
  title: string;
  risk_level: string | null;
  required_approval_role: string | null;
  version: number;
  expires_at: string | null;
  executed_ref?: string | null;
  recommendation?: Recommendation | null;
  calculated_parameters?: Record<string, unknown> | null;
  created_at: string | null;
}

export interface Run {
  id: number;
  finding_id: number;
  status: string;
  phase: string | null;
  refusal_reason: string | null;
  error: string | null;
  graph_version: string | null;
  prompt_version: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AuditEvent {
  event_type: string;
  actor: string | null;
  actor_user_id?: number | null;
  payload?: Record<string, unknown> | null;
  created_at: string | null;
}

export interface Briefing {
  runs_by_status: Record<string, number>;
  proposals_by_status: Record<string, number>;
  awaiting_approval: Proposal[];
}

export interface OperationsMetrics {
  runs_total: number;
  refused_or_escalated: number;
  proposals_total: number;
  approved: number;
  rejected: number;
  executed: number;
  superseded: number;
  expired: number;
}

export interface RunDetail { run: Run; proposals: Proposal[]; }

export interface DecisionResult {
  proposal_id: number;
  status: string;
  executed_ref?: string | null;
  idempotent?: boolean;
}

export interface RecommendResult {
  run_id: number;
  status: string;
  proposal_id?: number;
  recommendation?: Recommendation;
  refusal_reason?: string;
  existing?: boolean;
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const operationsKeys = {
  all: ['operations'] as const,
  briefing: () => ['operations', 'briefing'] as const,
  metrics: () => ['operations', 'metrics'] as const,
  run: (id: number) => ['operations', 'run', id] as const,
  audit: (id: number) => ['operations', 'audit', id] as const,
};

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useBriefing() {
  return useQuery<Briefing>({
    queryKey: operationsKeys.briefing(),
    queryFn: () => apiRequest<Briefing>('/api/operations/briefing', { ttl: 0 }),
  });
}

export function useOperationsMetrics() {
  return useQuery<OperationsMetrics>({
    queryKey: operationsKeys.metrics(),
    queryFn: () => apiRequest<OperationsMetrics>('/api/operations/metrics', { ttl: 0 }),
  });
}

export function useRun(runId: number | null) {
  return useQuery<RunDetail>({
    queryKey: operationsKeys.run(runId ?? -1),
    queryFn: () => apiRequest<RunDetail>(`/api/operations/runs/${runId}`, { ttl: 0 }),
    enabled: runId != null,
  });
}

export function useProposalAudit(proposalId: number | null) {
  return useQuery<{ proposal_id: number; run_id: number; events: AuditEvent[] }>({
    queryKey: operationsKeys.audit(proposalId ?? -1),
    queryFn: () =>
      apiRequest(`/api/operations/proposals/${proposalId}/audit`, { ttl: 0 }),
    enabled: proposalId != null,
  });
}

// ---------------------------------------------------------------------------
// Mutations — each invalidates the whole operations tree (queue + metrics + run).
// ---------------------------------------------------------------------------

export function useRecommend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (findingId: number) =>
      apiRequest<RecommendResult>(`/api/operations/findings/${findingId}/recommend`, {
        method: 'POST',
        body: {},
        ttl: 0,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: operationsKeys.all }),
  });
}

export function useApproveProposal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; version: number }) =>
      apiRequest<DecisionResult>(`/api/operations/proposals/${vars.id}/approve`, {
        method: 'POST',
        body: { version: vars.version, idempotency_key: crypto.randomUUID() },
        ttl: 0,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: operationsKeys.all }),
  });
}

export function useRejectProposal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; version: number; reason: string }) =>
      apiRequest<DecisionResult>(`/api/operations/proposals/${vars.id}/reject`, {
        method: 'POST',
        body: { version: vars.version, idempotency_key: crypto.randomUUID(), reason: vars.reason },
        ttl: 0,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: operationsKeys.all }),
  });
}

export function useCancelProposal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; version: number }) =>
      apiRequest<DecisionResult>(`/api/operations/proposals/${vars.id}/cancel`, {
        method: 'POST',
        body: { version: vars.version },
        ttl: 0,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: operationsKeys.all }),
  });
}
