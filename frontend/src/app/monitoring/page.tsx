'use client';

import { useState, useEffect, useCallback } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Button, Badge } from '@/components/ui';
import {
  StatusPill, HealthChecksGrid, SystemStatsCards, MetricsPanel,
  HealthCheck, SystemStats, MetricsData,
} from '@/components/monitoring';

export default function MonitoringPage() {
  const { authFetch } = useAuth();
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [healthRes, statsRes, metricsRes] = await Promise.all([
        authFetch('/api/monitoring/health/detailed'),
        authFetch('/api/monitoring/stats'),
        authFetch('/api/monitoring/metrics/json'),
      ]);
      if (healthRes.ok) setHealth(await healthRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
      if (metricsRes.ok) setMetrics(await metricsRes.json());
      setLastUpdated(new Date());
    } catch (err) {
      console.error('Failed to fetch monitoring data:', err);
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="System Monitoring"
          description="Live health, database/cache status, and application metrics"
          icon={<Activity className="w-5 h-5" />}
          actions={
            <div className="flex items-center gap-3">
              {health && <StatusPill status={health.status} />}
              <button
                type="button"
                onClick={() => setAutoRefresh((v) => !v)}
                className={`px-3 py-2 rounded-2xl text-sm font-medium transition-colors ${
                  autoRefresh ? 'bg-teal-100 text-teal-700' : 'bg-surface-2 text-ink-muted'
                }`}
              >
                Auto-refresh {autoRefresh ? 'on' : 'off'}
              </button>
              <Button variant="secondary" size="md" onClick={fetchData} aria-label="Refresh">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          }
        />

        <div className="flex items-center gap-2 mb-6 text-sm text-ink-muted">
          {health && (
            <Badge variant="neutral" size="sm">{health.environment} · v{health.version}</Badge>
          )}
          {lastUpdated && <span>Updated {lastUpdated.toLocaleTimeString()}</span>}
        </div>

        <HealthChecksGrid health={health} loading={loading} />
        <SystemStatsCards stats={stats} loading={loading} />
        <MetricsPanel metrics={metrics} loading={loading} />
      </div>
    </main>
  );
}
