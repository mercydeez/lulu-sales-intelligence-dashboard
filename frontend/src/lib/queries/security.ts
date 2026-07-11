'use client';

/** TanStack Query hooks for security/audit data. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';

export interface AuditEvent {
  id: number;
  occurred_at: string;
  event_type: string;
  severity: string;
  category: string;
  actor_email: string | null;
  ip_address: string | null;
  method: string | null;
  path: string | null;
  detail: string | null;
}

export const securityKeys = {
  all: ['security'] as const,
  auditEvents: (hours: string, severity: string) =>
    ['security', 'audit-events', hours, severity] as const,
};

/** Audit-category security events for the given window. `enabled` gates the
 *  fetch on admin access (the page hides the log for non-admins). */
export function useAuditEvents(hours: string, severity: string, enabled: boolean) {
  return useQuery<AuditEvent[]>({
    queryKey: securityKeys.auditEvents(hours, severity),
    enabled,
    queryFn: async () => {
      const params: Record<string, unknown> = { category: 'audit', hours, limit: 500 };
      if (severity) params.severity = severity;
      const res = await apiRequest<{ data?: AuditEvent[] }>('/api/security/events', { params, ttl: 0 });
      return res.data ?? [];
    },
  });
}
