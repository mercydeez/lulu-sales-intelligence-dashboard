'use client';

import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Bell, ClipboardList, Settings, RefreshCw } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useEventStream } from '@/hooks/useEventStream';
import { PageHeader, Tabs, LiveIndicator, Badge, Button } from '@/components/ui';
import {
  AlertsSummaryCards,
  AlertFilters,
  AlertsList,
  RecentAlertsPanel,
  TrendPanel,
  ResolveModal,
  RulesModal,
  Alert,
  AlertSummary,
  AlertStats,
  AlertRule,
} from '@/components/alerts';

export default function AlertsPage() {
  const { authFetch, hasRole } = useAuth();
  const { t } = useLanguage();
  const canManageRules = hasRole(['super_admin', 'regional_manager']);

  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [sideLoading, setSideLoading] = useState(true);

  const [activeTab, setActiveTab] = useState<'all' | 'tasks'>('all');
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [listLoading, setListLoading] = useState(true);

  const [myTasks, setMyTasks] = useState<Alert[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);

  const [showRules, setShowRules] = useState(false);
  const [resolveTarget, setResolveTarget] = useState<Alert | null>(null);

  const fetchOverview = useCallback(async () => {
    setSideLoading(true);
    try {
      const [summaryRes, recentRes, statsRes] = await Promise.all([
        authFetch('/api/alerts/summary'),
        authFetch('/api/alerts/recent?limit=5'),
        authFetch('/api/alerts/stats?days=7'),
      ]);
      if (summaryRes.ok) setSummary(await summaryRes.json());
      if (recentRes.ok) {
        const data = await recentRes.json();
        setRecentAlerts(data.alerts || []);
      }
      if (statsRes.ok) setStats(await statsRes.json());
    } catch (error) {
      console.error('Failed to fetch alerts overview:', error);
    } finally {
      setSideLoading(false);
    }
  }, [authFetch]);

  const fetchRules = useCallback(async () => {
    try {
      const res = await authFetch('/api/alerts/rules');
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      }
    } catch (error) {
      console.error('Failed to fetch alert rules:', error);
    }
  }, [authFetch]);

  const fetchList = useCallback(async (targetPage: number) => {
    setListLoading(true);
    try {
      const params = new URLSearchParams();
      if (severity) params.append('severity', severity);
      if (status) params.append('status', status);
      if (category) params.append('alert_type', category);
      params.append('page', String(targetPage));
      params.append('limit', '20');

      const res = await authFetch(`/api/alerts/list?${params}`);
      if (res.ok) {
        const data = await res.json();
        setAlerts(data.alerts || []);
        setPages(data.pages || 1);
      }
    } catch (error) {
      console.error('Failed to fetch alerts:', error);
    } finally {
      setListLoading(false);
    }
  }, [authFetch, severity, status, category]);

  const fetchMyTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      const res = await authFetch('/api/alerts/my-tasks');
      if (res.ok) {
        const data = await res.json();
        setMyTasks(data.tasks || []);
      }
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    } finally {
      setTasksLoading(false);
    }
  }, [authFetch]);

  useEffect(() => { fetchOverview(); }, [fetchOverview]);
  useEffect(() => { if (canManageRules) fetchRules(); }, [canManageRules, fetchRules]);
  useEffect(() => { if (activeTab === 'all') fetchList(page); }, [activeTab, page, fetchList]);
  useEffect(() => { if (activeTab === 'tasks') fetchMyTasks(); }, [activeTab, fetchMyTasks]);

  const refetchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventHandlers = useMemo(() => ({
    alert: () => {
      if (refetchTimeoutRef.current) clearTimeout(refetchTimeoutRef.current);
      refetchTimeoutRef.current = setTimeout(() => {
        fetchOverview();
        if (activeTab === 'all' && page === 1) fetchList(1);
      }, 1500);
    },
  }), [activeTab, page, fetchOverview, fetchList]);

  const { isConnected: isLiveConnected } = useEventStream('/stream/alerts', { eventHandlers });

  const handleSeverityChange = (value: string) => { setSeverity(value); setPage(1); };
  const handleStatusChange = (value: string) => { setStatus(value); setPage(1); };
  const handleCategoryChange = (value: string) => { setCategory(value); setPage(1); };

  const handleAcknowledge = async (alert: Alert) => {
    try {
      const res = await authFetch(`/api/alerts/${alert.id}/acknowledge`, { method: 'POST' });
      if (res.ok) {
        fetchOverview();
        if (activeTab === 'all') fetchList(page); else fetchMyTasks();
      }
    } catch (error) {
      console.error('Failed to acknowledge alert:', error);
    }
  };

  const confirmResolve = async (notes: string) => {
    if (!resolveTarget) return;
    try {
      const res = await authFetch(`/api/alerts/${resolveTarget.id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: notes || null }),
      });
      if (res.ok) {
        setResolveTarget(null);
        fetchOverview();
        if (activeTab === 'all') fetchList(page); else fetchMyTasks();
      }
    } catch (error) {
      console.error('Failed to resolve alert:', error);
    }
  };

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title={t('alerts.title')}
          description={t('alerts.description')}
          icon={<Bell className="w-5 h-5" />}
          actions={
            <>
              {isLiveConnected && <LiveIndicator tone="rose" />}
              {canManageRules && (
                <Button variant="secondary" size="sm" onClick={() => setShowRules(true)}>
                  <Settings className="w-4 h-4" />
                  Alert Rules
                </Button>
              )}
            </>
          }
        />

        <Tabs
          className="mb-6"
          value={activeTab}
          onChange={(id) => setActiveTab(id as typeof activeTab)}
          items={[
            {
              id: 'all', label: t('alerts.tab.all'), icon: <Bell className="w-4 h-4" />,
              badge: !!summary?.total_active && <Badge variant="danger" size="sm">{summary.total_active}</Badge>,
            },
            {
              id: 'tasks', label: t('alerts.tab.tasks'), icon: <ClipboardList className="w-4 h-4" />,
              badge: myTasks.length > 0 && <Badge variant="warning" size="sm">{myTasks.length}</Badge>,
            },
          ]}
        />

        <AlertsSummaryCards summary={summary} loading={sideLoading} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-6">
            <RecentAlertsPanel alerts={recentAlerts} loading={sideLoading} />
            <TrendPanel stats={stats} loading={sideLoading} />
          </div>

          <div className="lg:col-span-2">
            {activeTab === 'all' ? (
              <>
                <AlertFilters
                  severity={severity}
                  onSeverityChange={handleSeverityChange}
                  status={status}
                  onStatusChange={handleStatusChange}
                  category={category}
                  onCategoryChange={handleCategoryChange}
                  onRefresh={() => fetchList(page)}
                  loading={listLoading}
                />
                <AlertsList
                  alerts={alerts}
                  loading={listLoading}
                  onAcknowledge={handleAcknowledge}
                  onResolve={setResolveTarget}
                  pagination={{ page, pages, onPageChange: setPage }}
                />
              </>
            ) : (
              <>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold text-ink flex items-center gap-2">
                    <ClipboardList className="w-6 h-6 text-coral-500" />
                    My Open Tasks
                  </h2>
                  <Button variant="secondary" size="sm" onClick={fetchMyTasks} aria-label="Refresh">
                    <RefreshCw className={`w-4 h-4 ${tasksLoading ? 'animate-spin' : ''}`} />
                  </Button>
                </div>
                <AlertsList
                  alerts={myTasks}
                  loading={tasksLoading}
                  emptyTitle="No open tasks"
                  emptyDescription="Alerts assigned to you will show up here."
                  onAcknowledge={handleAcknowledge}
                  onResolve={setResolveTarget}
                />
              </>
            )}
          </div>
        </div>

        <ResolveModal
          open={!!resolveTarget}
          alert={resolveTarget}
          onCancel={() => setResolveTarget(null)}
          onConfirm={confirmResolve}
        />

        {canManageRules && (
          <RulesModal open={showRules} rules={rules} onClose={() => setShowRules(false)} />
        )}
      </div>
    </main>
  );
}
