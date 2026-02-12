'use client';

import React, { useState, useEffect } from 'react';
import { 
  Bell, AlertTriangle, AlertCircle, Info, CheckCircle,
  Search, Filter, RefreshCw, ChevronRight, Clock,
  Package, TrendingUp, Tag, Settings, X, Check
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

interface Alert {
  id: number;
  title: string;
  message: string;
  alert_type: 'inventory' | 'sales' | 'promotion' | 'system';
  severity: 'critical' | 'warning' | 'info';
  status: 'active' | 'acknowledged' | 'resolved';
  store_id?: number;
  store_name?: string;
  item_id?: number;
  created_at: string;
  acknowledged_at?: string;
  resolved_at?: string;
  time_ago?: string;
}

interface AlertSummary {
  critical_alerts: number;
  warning_alerts: number;
  info_alerts: number;
  acknowledged: number;
  resolved_today: number;
  total_active: number;
}

interface AlertRule {
  id: number;
  name: string;
  rule_type: string;
  condition: any;
  action: string;
  severity: string;
  is_active: boolean;
  last_triggered?: string;
}

interface AlertStats {
  date: string;
  critical: number;
  warning: number;
  info: number;
}

const severityConfig = {
  critical: {
    icon: AlertTriangle,
    color: 'text-red-500',
    bg: 'bg-red-100 dark:bg-red-900/30',
    border: 'border-red-200 dark:border-red-800',
    badge: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  },
  warning: {
    icon: AlertCircle,
    color: 'text-yellow-500',
    bg: 'bg-yellow-100 dark:bg-yellow-900/30',
    border: 'border-yellow-200 dark:border-yellow-800',
    badge: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  },
  info: {
    icon: Info,
    color: 'text-blue-500',
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    border: 'border-blue-200 dark:border-blue-800',
    badge: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  },
};

const typeIcons = {
  inventory: Package,
  sales: TrendingUp,
  promotion: Tag,
  system: Settings,
};

export default function AlertsPage() {
  const { user, authFetch, hasRole } = useAuth();
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [recentAlerts, setRecentAlerts] = useState<Alert[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [stats, setStats] = useState<AlertStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTab, setSelectedTab] = useState<'all' | 'critical' | 'warning' | 'info'>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [selectedType, setSelectedType] = useState<string>('');
  const [showRulesPanel, setShowRulesPanel] = useState(false);

  const canManageRules = hasRole('super_admin') || hasRole('regional_manager');

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    fetchAlerts();
  }, [selectedTab, selectedStatus, selectedType]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [summaryRes, recentRes, rulesRes, statsRes] = await Promise.all([
        authFetch('/api/alerts/summary'),
        authFetch('/api/alerts/recent?limit=5'),
        authFetch('/api/alerts/rules'),
        authFetch('/api/alerts/stats?days=7'),
      ]);

      if (summaryRes.ok) setSummary(await summaryRes.json());
      if (recentRes.ok) {
        const data = await recentRes.json();
        setRecentAlerts(data.alerts || []);
      }
      if (rulesRes.ok) {
        const data = await rulesRes.json();
        setRules(data.rules || []);
      }
      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data.stats || []);
      }
    } catch (error) {
      console.error('Failed to fetch alerts data:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchAlerts = async () => {
    try {
      const params = new URLSearchParams();
      if (selectedTab !== 'all') params.append('severity', selectedTab);
      if (selectedStatus) params.append('status', selectedStatus);
      if (selectedType) params.append('alert_type', selectedType);

      const res = await authFetch(`/api/alerts/list?${params}`);
      if (res.ok) {
        const data = await res.json();
        setAlerts(data.alerts || []);
      }
    } catch (error) {
      console.error('Failed to fetch alerts:', error);
    }
  };

  const handleAcknowledge = async (alertId: number) => {
    try {
      const res = await authFetch(`/api/alerts/${alertId}/acknowledge`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchAlerts();
        fetchData();
      }
    } catch (error) {
      console.error('Failed to acknowledge alert:', error);
    }
  };

  const handleResolve = async (alertId: number) => {
    try {
      const res = await authFetch(`/api/alerts/${alertId}/resolve`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchAlerts();
        fetchData();
      }
    } catch (error) {
      console.error('Failed to resolve alert:', error);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-AE', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Calculate max for chart scaling
  const maxAlerts = Math.max(...stats.flatMap(s => [s.critical, s.warning, s.info]), 1);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
              <Bell className="w-8 h-8 text-red-600" />
              Alerts & Notifications
            </h1>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Monitor system alerts, inventory warnings, and operational notifications
            </p>
          </div>
          {canManageRules && (
            <button
              onClick={() => setShowRulesPanel(!showRulesPanel)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            >
              <Settings className="w-5 h-5" />
              Alert Rules
            </button>
          )}
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-red-200 dark:border-red-800">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-red-600 dark:text-red-400">Critical</p>
                <p className="text-2xl font-bold text-red-600 dark:text-red-400">
                  {summary?.critical_alerts || 0}
                </p>
              </div>
              <AlertTriangle className="w-10 h-10 text-red-500" />
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-yellow-200 dark:border-yellow-800">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-yellow-600 dark:text-yellow-400">Warnings</p>
                <p className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                  {summary?.warning_alerts || 0}
                </p>
              </div>
              <AlertCircle className="w-10 h-10 text-yellow-500" />
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-blue-200 dark:border-blue-800">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-blue-600 dark:text-blue-400">Info</p>
                <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                  {summary?.info_alerts || 0}
                </p>
              </div>
              <Info className="w-10 h-10 text-blue-500" />
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-purple-200 dark:border-purple-800">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-purple-600 dark:text-purple-400">Acknowledged</p>
                <p className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                  {summary?.acknowledged || 0}
                </p>
              </div>
              <Check className="w-10 h-10 text-purple-500" />
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-green-200 dark:border-green-800">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-green-600 dark:text-green-400">Resolved</p>
                <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                  {summary?.resolved_today || 0}
                </p>
              </div>
              <CheckCircle className="w-10 h-10 text-green-500" />
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Total Active</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {summary?.total_active || 0}
                </p>
              </div>
              <Bell className="w-10 h-10 text-gray-400" />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Recent Alerts (Quick View) */}
          <div className="lg:col-span-1">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 mb-6">
              <div className="p-4 border-b border-gray-100 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <Clock className="w-5 h-5" />
                  Recent Alerts
                </h2>
              </div>
              <div className="divide-y divide-gray-100 dark:divide-gray-700">
                {recentAlerts.map((alert) => {
                  const config = severityConfig[alert.severity];
                  const SeverityIcon = config.icon;
                  const TypeIcon = typeIcons[alert.alert_type] || Bell;
                  
                  return (
                    <div key={alert.id} className="p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                      <div className="flex items-start gap-3">
                        <div className={`p-2 rounded-lg ${config.bg}`}>
                          <SeverityIcon className={`w-4 h-4 ${config.color}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-gray-900 dark:text-white text-sm truncate">
                            {alert.title}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                            {alert.store_name || 'System'} · {alert.time_ago}
                          </p>
                        </div>
                        <span className={`px-2 py-0.5 text-xs rounded-full ${config.badge}`}>
                          {alert.severity}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Alert Trend Chart */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700">
              <div className="p-4 border-b border-gray-100 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  7-Day Trend
                </h2>
              </div>
              <div className="p-4">
                <div className="space-y-3">
                  {stats.slice(-7).map((day, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 dark:text-gray-400 w-12">
                        {new Date(day.date).toLocaleDateString('en-AE', { weekday: 'short' })}
                      </span>
                      <div className="flex-1 flex gap-1 h-4">
                        <div 
                          className="bg-red-500 rounded-sm"
                          style={{ width: `${(day.critical / maxAlerts) * 100}%` }}
                          title={`${day.critical} critical`}
                        />
                        <div 
                          className="bg-yellow-500 rounded-sm"
                          style={{ width: `${(day.warning / maxAlerts) * 100}%` }}
                          title={`${day.warning} warnings`}
                        />
                        <div 
                          className="bg-blue-500 rounded-sm"
                          style={{ width: `${(day.info / maxAlerts) * 100}%` }}
                          title={`${day.info} info`}
                        />
                      </div>
                      <span className="text-xs text-gray-500 dark:text-gray-400 w-8 text-right">
                        {day.critical + day.warning + day.info}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="flex items-center justify-center gap-4 mt-4 text-xs">
                  <span className="flex items-center gap-1">
                    <div className="w-3 h-3 bg-red-500 rounded-sm" /> Critical
                  </span>
                  <span className="flex items-center gap-1">
                    <div className="w-3 h-3 bg-yellow-500 rounded-sm" /> Warning
                  </span>
                  <span className="flex items-center gap-1">
                    <div className="w-3 h-3 bg-blue-500 rounded-sm" /> Info
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* All Alerts */}
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700">
              {/* Filters */}
              <div className="p-4 border-b border-gray-100 dark:border-gray-700">
                <div className="flex flex-wrap items-center gap-3">
                  {/* Severity Tabs */}
                  <div className="flex gap-1">
                    {(['all', 'critical', 'warning', 'info'] as const).map((tab) => (
                      <button
                        key={tab}
                        onClick={() => setSelectedTab(tab)}
                        className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                          selectedTab === tab
                            ? 'bg-red-600 text-white'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                        }`}
                      >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                      </button>
                    ))}
                  </div>

                  {/* Status Filter */}
                  <select
                    value={selectedStatus}
                    onChange={(e) => setSelectedStatus(e.target.value)}
                    className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white"
                  >
                    <option value="">All Status</option>
                    <option value="active">Active</option>
                    <option value="acknowledged">Acknowledged</option>
                    <option value="resolved">Resolved</option>
                  </select>

                  {/* Type Filter */}
                  <select
                    value={selectedType}
                    onChange={(e) => setSelectedType(e.target.value)}
                    className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white"
                  >
                    <option value="">All Types</option>
                    <option value="inventory">Inventory</option>
                    <option value="sales">Sales</option>
                    <option value="promotion">Promotion</option>
                    <option value="system">System</option>
                  </select>

                  <button
                    onClick={fetchData}
                    className="ml-auto p-2 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                  </button>
                </div>
              </div>

              {/* Alerts List */}
              <div className="divide-y divide-gray-100 dark:divide-gray-700 max-h-[600px] overflow-y-auto">
                {loading ? (
                  <div className="p-8 text-center text-gray-500">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                    Loading alerts...
                  </div>
                ) : alerts.length === 0 ? (
                  <div className="p-8 text-center text-gray-500">
                    <Bell className="w-12 h-12 mx-auto mb-2 text-gray-300" />
                    No alerts found
                  </div>
                ) : (
                  alerts.map((alert) => {
                    const config = severityConfig[alert.severity];
                    const SeverityIcon = config.icon;
                    const TypeIcon = typeIcons[alert.alert_type] || Bell;
                    
                    return (
                      <div key={alert.id} className={`p-4 ${config.bg} bg-opacity-50`}>
                        <div className="flex items-start gap-4">
                          <div className={`p-2 rounded-lg ${config.bg}`}>
                            <SeverityIcon className={`w-5 h-5 ${config.color}`} />
                          </div>
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <h3 className="font-medium text-gray-900 dark:text-white">
                                {alert.title}
                              </h3>
                              <span className={`px-2 py-0.5 text-xs rounded-full ${config.badge}`}>
                                {alert.severity}
                              </span>
                              <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                                {alert.status}
                              </span>
                            </div>
                            <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                              {alert.message}
                            </p>
                            <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
                              <span className="flex items-center gap-1">
                                <TypeIcon className="w-3 h-3" />
                                {alert.alert_type}
                              </span>
                              {alert.store_name && (
                                <span className="flex items-center gap-1">
                                  <Package className="w-3 h-3" />
                                  {alert.store_name}
                                </span>
                              )}
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {formatDate(alert.created_at)}
                              </span>
                            </div>
                          </div>
                          {alert.status === 'active' && (
                            <div className="flex gap-2">
                              <button
                                onClick={() => handleAcknowledge(alert.id)}
                                className="px-3 py-1.5 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 rounded-lg hover:bg-yellow-200 dark:hover:bg-yellow-900/50 transition-colors"
                              >
                                Acknowledge
                              </button>
                              <button
                                onClick={() => handleResolve(alert.id)}
                                className="px-3 py-1.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-lg hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors"
                              >
                                Resolve
                              </button>
                            </div>
                          )}
                          {alert.status === 'acknowledged' && (
                            <button
                              onClick={() => handleResolve(alert.id)}
                              className="px-3 py-1.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-lg hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors"
                            >
                              Resolve
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Alert Rules Panel (Slide-out) */}
        {showRulesPanel && (
          <div className="fixed inset-0 z-50 overflow-hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setShowRulesPanel(false)} />
            <div className="absolute right-0 top-0 h-full w-full max-w-md bg-white dark:bg-gray-800 shadow-xl">
              <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Alert Rules</h2>
                <button
                  onClick={() => setShowRulesPanel(false)}
                  className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-4 space-y-4 overflow-y-auto h-[calc(100%-64px)]">
                {rules.map((rule) => (
                  <div
                    key={rule.id}
                    className={`p-4 rounded-lg border ${
                      rule.is_active
                        ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20'
                        : 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-medium text-gray-900 dark:text-white">{rule.name}</h3>
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        rule.is_active
                          ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                          : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400'
                      }`}>
                        {rule.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
                      <p>Type: {rule.rule_type}</p>
                      <p>Action: {rule.action}</p>
                      <p>Severity: {rule.severity}</p>
                      {rule.last_triggered && (
                        <p className="text-xs">Last triggered: {formatDate(rule.last_triggered)}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
