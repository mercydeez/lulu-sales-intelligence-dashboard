'use client';

/**
 * TanStack Query hooks for procurement (approval inbox + PO decisions).
 * This module is the REFERENCE for the mutation pattern: a mutation that, on
 * success, invalidates the query it affects so the UI reflects the new state
 * without a hand-rolled reload.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface PO {
  id: number;
  po_number: string;
  status: string;
  total_amount: number;
  currency: string;
  source: string;
  supplier_name: string;
  line_count: number;
  created_at: string | null;
}
export interface ApprovalInbox {
  count: number;
  total_value: number;
  currency: string;
  purchase_orders: PO[];
}

export const procurementKeys = {
  all: ['procurement'] as const,
  approvals: () => ['procurement', 'approvals'] as const,
};

/** Purchase orders awaiting a decision. */
export function useApprovalInbox() {
  return useQuery<ApprovalInbox>({
    queryKey: procurementKeys.approvals(),
    queryFn: () => apiRequest<ApprovalInbox>('/api/procurement/approvals', { ttl: 0 }),
  });
}

/** Approve/reject a PO, then refresh the inbox. Throws on a rejected decision
 *  (e.g. an approval-rule cap) so callers can surface the server message. */
export function useDecidePO() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; status: 'approved' | 'cancelled' }) =>
      apiRequest(`/api/procurement/purchase-orders/${vars.id}/status`, {
        method: 'POST',
        body: { status: vars.status },
        ttl: 0,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: procurementKeys.approvals() });
    },
  });
}
