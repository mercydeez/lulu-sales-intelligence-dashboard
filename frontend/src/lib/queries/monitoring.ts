'use client';

/** TanStack Query hooks for the system-monitoring page. */
import { useQuery } from '@tanstack/react-query';
import { apiRequest } from '@/lib/apiClient';
import type { HealthCheck, SystemStats, MetricsData } from '@/components/monitoring';

export const monitoringKeys = {
  all: ['monitoring'] as const,
  health: () => ['monitoring', 'health'] as const,
  stats: () => ['monitoring', 'stats'] as const,
  metrics: () => ['monitoring', 'metrics'] as const,
};

/**
 * Health + stats + metrics for the monitoring dashboard. `autoRefresh` drives a
 * 10s poll via refetchInterval (replacing the page's hand-rolled setInterval).
 * `lastUpdated` comes from the freshest query's dataUpdatedAt.
 */
export function useMonitoring(autoRefresh: boolean) {
  const refetchInterval = autoRefresh ? 10000 : (false as const);
  const health = useQuery<HealthCheck>({
    queryKey: monitoringKeys.health(),
    queryFn: () => apiRequest<HealthCheck>('/api/monitoring/health/detailed', { ttl: 0 }),
    refetchInterval,
  });
  const stats = useQuery<SystemStats>({
    queryKey: monitoringKeys.stats(),
    queryFn: () => apiRequest<SystemStats>('/api/monitoring/stats', { ttl: 0 }),
    refetchInterval,
  });
  const metrics = useQuery<MetricsData>({
    queryKey: monitoringKeys.metrics(),
    queryFn: () => apiRequest<MetricsData>('/api/monitoring/metrics/json', { ttl: 0 }),
    refetchInterval,
  });

  const updatedAt = Math.max(health.dataUpdatedAt, stats.dataUpdatedAt, metrics.dataUpdatedAt);
  return {
    health: health.data ?? null,
    stats: stats.data ?? null,
    metrics: metrics.data ?? null,
    loading: health.isLoading || stats.isLoading || metrics.isLoading,
    lastUpdated: updatedAt > 0 ? new Date(updatedAt) : null,
    refetch: () => {
      health.refetch();
      stats.refetch();
      metrics.refetch();
    },
  };
}
