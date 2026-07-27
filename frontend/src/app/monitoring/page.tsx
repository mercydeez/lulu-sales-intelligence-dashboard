'use client';

import { useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { PageHeader, Button, Badge } from '@/components/ui';
import {
  StatusPill, HealthChecksGrid, SystemStatsCards, MetricsPanel,
} from '@/components/monitoring';
import { useMonitoring } from '@/lib/queries/monitoring';

export default function MonitoringPage() {
  const [autoRefresh, setAutoRefresh] = useState(true);
  // Reactive health/stats/metrics — the 10s poll is driven by refetchInterval
  // inside the hook (toggled by autoRefresh), replacing the manual setInterval.
  const { health, stats, metrics, loading, lastUpdated, refetch } = useMonitoring(autoRefresh);
  const fetchData = refetch;

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
