'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { 
  Activity, Server, Database, HardDrive, Cpu, 
  Clock, CheckCircle, XCircle, AlertTriangle,
  RefreshCw, Wifi, WifiOff, TrendingUp
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

interface HealthCheck {
  status: string;
  timestamp: string;
  version: string;
  environment: string;
  checks: {
    database: {
      status: string;
      sales_records?: number;
      streaming_records?: number;
      error?: string;
    };
    redis: {
      status: string;
      connected_clients?: number;
      used_memory_human?: string;
      uptime_in_seconds?: number;
      error?: string;
    };
    application: {
      status: string;
      uptime_seconds?: number;
      requests_in_progress?: number;
      total_requests?: number;
      error?: string;
    };
  };
}

interface SystemStats {
  timestamp: string;
  database: {
    total_sales: number;
    streaming_sales: number;
    active_stores: number;
    active_items: number;
    date_range: {
      start: string | null;
      end: string | null;
    };
  };
  streaming: {
    last_hour_count: number;
    last_hour_avg_sales: number;
    last_generated: string | null;
  };
  cache: {
    connected_clients: number;
    used_memory: string;
    total_keys: number;
  };
}

interface MetricsData {
  counters: Record<string, number>;
  gauges: Record<string, number>;
  histograms: Record<string, { sum: number; count: number; avg: number }>;
  requests_in_progress: number;
  uptime_seconds: number;
}

const StatusBadge = ({ status }: { status: string }) => {
  const colors = {
    healthy: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    degraded: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
    unhealthy: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
    unknown: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400',
  };
  
  const icons = {
    healthy: <CheckCircle className="w-4 h-4" />,
    degraded: <AlertTriangle className="w-4 h-4" />,
    unhealthy: <XCircle className="w-4 h-4" />,
    unknown: <AlertTriangle className="w-4 h-4" />,
  };
  
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${colors[status as keyof typeof colors] || colors.unknown}`}>
      {icons[status as keyof typeof icons] || icons.unknown}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
};

export default function MonitoringPage() {
  const { authFetch, hasPermission } = useAuth();
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
    } catch (error) {
      console.error('Failed to fetch monitoring data:', error);
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return;
    
    const interval = setInterval(fetchData, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  };

  const formatNumber = (num: number) => {
    return new Intl.NumberFormat('en-US').format(num);
  };

  if (!hasPermission('is_admin')) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col items-center justify-center h-[60vh]">
            <Server className="w-16 h-16 text-red-500 mb-4" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Access Denied</h1>
            <p className="text-gray-600 dark:text-gray-400">You don't have permission to view system monitoring.</p>
          </div>
        </div>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto flex items-center justify-center h-[60vh]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mx-auto mb-4"></div>
            <p className="text-slate-400">Loading monitoring data...</p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
              <Activity className="w-8 h-8 text-cyan-500" />
              System Monitoring
            </h1>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Real-time health and performance metrics
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`p-2 rounded-lg transition-colors ${
                  autoRefresh 
                    ? 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400' 
                    : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                }`}
                title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
              >
                {autoRefresh ? <Wifi className="w-5 h-5" /> : <WifiOff className="w-5 h-5" />}
              </button>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : ''}
              </span>
            </div>
            <button
              onClick={fetchData}
              className="flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700"
            >
              <RefreshCw className="w-5 h-5" />
              Refresh
            </button>
          </div>
        </div>

        {/* Overall Status */}
        {health && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 mb-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className={`p-4 rounded-full ${
                  health.status === 'healthy' ? 'bg-green-100 dark:bg-green-900/30' :
                  health.status === 'degraded' ? 'bg-yellow-100 dark:bg-yellow-900/30' :
                  'bg-red-100 dark:bg-red-900/30'
                }`}>
                  <Server className={`w-8 h-8 ${
                    health.status === 'healthy' ? 'text-green-600 dark:text-green-400' :
                    health.status === 'degraded' ? 'text-yellow-600 dark:text-yellow-400' :
                    'text-red-600 dark:text-red-400'
                  }`} />
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                    System Status
                  </h2>
                  <p className="text-gray-500 dark:text-gray-400">
                    Version {health.version} • {health.environment}
                  </p>
                </div>
              </div>
              <StatusBadge status={health.status} />
            </div>
          </div>
        )}

        {/* Health Checks Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
          {/* Database Health */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <Database className="w-6 h-6 text-blue-500" />
                <h3 className="font-semibold text-gray-900 dark:text-white">Database</h3>
              </div>
              {health && <StatusBadge status={health.checks.database.status} />}
            </div>
            {health?.checks.database.status === 'healthy' ? (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Total Records</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {formatNumber(health.checks.database.sales_records || 0)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Streaming Records</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {formatNumber(health.checks.database.streaming_records || 0)}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-red-500">{health?.checks.database.error}</p>
            )}
          </div>

          {/* Redis Health */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <HardDrive className="w-6 h-6 text-red-500" />
                <h3 className="font-semibold text-gray-900 dark:text-white">Redis Cache</h3>
              </div>
              {health && <StatusBadge status={health.checks.redis.status} />}
            </div>
            {health?.checks.redis.status === 'healthy' ? (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Connected Clients</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {health.checks.redis.connected_clients}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Memory Used</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {health.checks.redis.used_memory_human}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Uptime</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {formatUptime(health.checks.redis.uptime_in_seconds || 0)}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-red-500">{health?.checks.redis.error}</p>
            )}
          </div>

          {/* Application Health */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <Cpu className="w-6 h-6 text-purple-500" />
                <h3 className="font-semibold text-gray-900 dark:text-white">Application</h3>
              </div>
              {health && <StatusBadge status={health.checks.application.status} />}
            </div>
            {health?.checks.application.status === 'healthy' ? (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Uptime</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {formatUptime(health.checks.application.uptime_seconds || 0)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Active Requests</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {health.checks.application.requests_in_progress}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-red-500">{health?.checks.application.error}</p>
            )}
          </div>
        </div>

        {/* Statistics */}
        {stats && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Database Statistics */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <Database className="w-5 h-5 text-blue-500" />
                Database Statistics
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Total Sales</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatNumber(stats.database.total_sales)}
                  </p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Streaming Sales</p>
                  <p className="text-2xl font-bold text-cyan-600 dark:text-cyan-400">
                    {formatNumber(stats.database.streaming_sales)}
                  </p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Active Stores</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {stats.database.active_stores}
                  </p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Active Items</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {stats.database.active_items}
                  </p>
                </div>
              </div>
              {stats.database.date_range.start && (
                <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">
                  Data range: {stats.database.date_range.start} to {stats.database.date_range.end}
                </p>
              )}
            </div>

            {/* Streaming Statistics */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-green-500" />
                Streaming Statistics (Last Hour)
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Records Generated</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">
                    {formatNumber(stats.streaming.last_hour_count)}
                  </p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                  <p className="text-sm text-gray-500 dark:text-gray-400">Avg Sales Value</p>
                  <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                    {stats.streaming.last_hour_avg_sales.toFixed(1)}
                  </p>
                </div>
              </div>
              {stats.streaming.last_generated && (
                <div className="mt-4 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                  <Clock className="w-4 h-4" />
                  Last generated: {new Date(stats.streaming.last_generated).toLocaleString()}
                </div>
              )}
              
              {/* Cache Stats */}
              <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h4 className="font-medium text-gray-900 dark:text-white mb-3">Cache Status</h4>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-500 dark:text-gray-400">Memory</span>
                  <span className="font-medium text-gray-900 dark:text-white">{stats.cache.used_memory}</span>
                </div>
                <div className="flex items-center justify-between text-sm mt-1">
                  <span className="text-gray-500 dark:text-gray-400">Clients</span>
                  <span className="font-medium text-gray-900 dark:text-white">{stats.cache.connected_clients}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Metrics */}
        {metrics && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <h3 className="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <Activity className="w-5 h-5 text-cyan-500" />
              Application Metrics
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                <p className="text-sm text-gray-500 dark:text-gray-400">Uptime</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {formatUptime(metrics.uptime_seconds)}
                </p>
              </div>
              <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                <p className="text-sm text-gray-500 dark:text-gray-400">In-Progress Requests</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {metrics.requests_in_progress}
                </p>
              </div>
              {Object.entries(metrics.histograms).map(([name, data]) => {
                const histData = data as { sum: number; count: number; avg: number };
                return (
                  <div key={name} className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                    <p className="text-sm text-gray-500 dark:text-gray-400 truncate" title={name}>
                      {name.replace(/_/g, ' ')}
                    </p>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {histData.avg.toFixed(3)}s avg
                    </p>
                    <p className="text-xs text-gray-400">{histData.count} requests</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
