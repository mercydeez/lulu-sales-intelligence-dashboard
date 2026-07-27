'use client';

import { ReactNode } from 'react';
import {
  CheckCircle, AlertTriangle, XCircle, Database, Server, Activity, Cpu, Clock, Boxes,
} from 'lucide-react';
import { Card, Badge, BadgeVariant, StatCard, SkeletonCard } from '@/components/ui';
import { HealthCheck, SystemStats, MetricsData } from './types';

function healthVariant(status: string): BadgeVariant {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'unhealthy') return 'danger';
  return 'neutral';
}

function HealthIcon({ status }: { status: string }) {
  if (status === 'healthy') return <CheckCircle className="w-4 h-4" />;
  if (status === 'unhealthy') return <XCircle className="w-4 h-4" />;
  return <AlertTriangle className="w-4 h-4" />;
}

export function StatusPill({ status }: { status: string }) {
  return (
    <Badge variant={healthVariant(status)} size="md">
      <HealthIcon status={status} />
      {status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown'}
    </Badge>
  );
}

function formatUptime(seconds?: number): string {
  if (!seconds || seconds < 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function HealthCheckCard({ title, icon, status, rows }: { title: string; icon: ReactNode; status: string; rows: { label: string; value: ReactNode }[] }) {
  return (
    <Card variant="glass" padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-xl bg-teal-100 text-teal-700">{icon}</div>
          <h3 className="font-semibold text-ink">{title}</h3>
        </div>
        <StatusPill status={status} />
      </div>
      <dl className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between text-sm">
            <dt className="text-ink-muted">{r.label}</dt>
            <dd className="text-ink font-medium">{r.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function HealthChecksGrid({ health, loading }: { health: HealthCheck | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {[0, 1, 2].map((i) => <SkeletonCard key={i} />)}
      </div>
    );
  }
  if (!health) return null;
  const { database: db, redis, application: app } = health.checks;
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <HealthCheckCard
        title="Database"
        icon={<Database className="w-4 h-4" />}
        status={db.status}
        rows={[
          { label: 'Sales records', value: (db.sales_records ?? 0).toLocaleString() },
          { label: 'Streaming records', value: (db.streaming_records ?? 0).toLocaleString() },
          ...(db.error ? [{ label: 'Error', value: db.error }] : []),
        ]}
      />
      <HealthCheckCard
        title="Redis"
        icon={<Server className="w-4 h-4" />}
        status={redis.status}
        rows={[
          { label: 'Connected clients', value: redis.connected_clients ?? '—' },
          { label: 'Memory', value: redis.used_memory_human ?? '—' },
          { label: 'Uptime', value: formatUptime(redis.uptime_in_seconds) },
        ]}
      />
      <HealthCheckCard
        title="Application"
        icon={<Activity className="w-4 h-4" />}
        status={app.status}
        rows={[
          { label: 'Uptime', value: formatUptime(app.uptime_seconds) },
          { label: 'In-progress requests', value: app.requests_in_progress ?? '—' },
          { label: 'Total requests', value: (app.total_requests ?? 0).toLocaleString() },
        ]}
      />
    </div>
  );
}

export function SystemStatsCards({ stats, loading }: { stats: SystemStats | null; loading: boolean }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard tone="coral" label="Total Sales Records" value={loading ? '—' : (stats?.database.total_sales ?? 0).toLocaleString()} icon={<Database className="w-5 h-5" />} loading={loading} />
      <StatCard tone="teal" label="Streaming Records" value={loading ? '—' : (stats?.database.streaming_sales ?? 0).toLocaleString()} icon={<Activity className="w-5 h-5" />} footnote={stats ? `${stats.streaming.last_hour_count}/hr` : undefined} loading={loading} />
      <StatCard tone="violet" label="Active Stores" value={loading ? '—' : stats?.database.active_stores ?? 0} icon={<Boxes className="w-5 h-5" />} footnote={stats ? `${stats.database.active_items} items` : undefined} loading={loading} />
      <StatCard tone="amber" label="Cache Keys" value={loading ? '—' : (stats?.cache.total_keys ?? 0).toLocaleString()} icon={<Cpu className="w-5 h-5" />} footnote={stats ? stats.cache.used_memory : undefined} loading={loading} />
    </div>
  );
}

export function MetricsPanel({ metrics, loading }: { metrics: MetricsData | null; loading: boolean }) {
  const counters = metrics ? Object.entries(metrics.counters) : [];
  const histograms = metrics ? Object.entries(metrics.histograms) : [];
  return (
    <Card variant="glass" padding="md">
      <div className="flex items-center gap-2 mb-4">
        <Clock className="w-5 h-5 text-teal-600" />
        <div>
          <h3 className="text-lg font-semibold text-ink">Application Metrics</h3>
          <p className="text-sm text-ink-muted mt-0.5">Counters and request latency since last restart</p>
        </div>
      </div>
      {loading ? (
        <div className="grid grid-cols-2 gap-3">{[0, 1, 2, 3].map((i) => <div key={i} className="h-16 shimmer rounded-2xl" />)}</div>
      ) : !metrics || (counters.length === 0 && histograms.length === 0) ? (
        <p className="text-sm text-ink-muted py-6 text-center">No metrics reported yet.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {counters.map(([key, value]) => (
            <div key={key} className="flex justify-between items-center p-3 rounded-2xl bg-surface-2/60">
              <span className="text-sm text-ink-soft font-mono truncate">{key}</span>
              <span className="text-sm font-semibold text-ink">{value.toLocaleString()}</span>
            </div>
          ))}
          {histograms.map(([key, h]) => (
            <div key={key} className="flex justify-between items-center p-3 rounded-2xl bg-teal-50/50">
              <span className="text-sm text-ink-soft font-mono truncate">{key}</span>
              <span className="text-sm font-semibold text-ink">avg {h.avg.toFixed(1)} ({h.count})</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
