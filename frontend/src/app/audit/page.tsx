'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import {
  PageHeader, Card, Badge, Button, Select, EmptyState, SkeletonCard, ErrorState,
  NoPermissionState,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { ScrollText, Download, ShieldAlert, RefreshCw } from 'lucide-react';

interface AuditEvent {
  id: number; occurred_at: string; event_type: string; severity: string;
  category: string; actor_email: string | null; ip_address: string | null;
  method: string | null; path: string | null; detail: string | null;
}

const SEV_TONE: Record<string, BadgeVariant> = {
  critical: 'danger', high: 'danger', medium: 'amber', low: 'neutral', info: 'neutral',
};

const WINDOWS = [
  { value: '24', label: 'Last 24 hours' },
  { value: '168', label: 'Last 7 days' },
  { value: '720', label: 'Last 30 days' },
  { value: '2160', label: 'Last 90 days' },
];

export default function AuditPage() {
  const { user, authFetch } = useAuth();
  const { t } = useLanguage();
  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hours, setHours] = useState('720');
  const [severity, setSeverity] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const qs = new URLSearchParams({ category: 'audit', hours, limit: '500' });
      if (severity) qs.set('severity', severity);
      const res = await authFetch(`/api/security/events?${qs.toString()}`);
      if (res.ok) setEvents((await res.json()).data ?? []);
      else setError('Failed to load audit log');
    } catch {
      setError('Failed to load audit log');
    } finally { setLoading(false); }
  }, [authFetch, hours, severity]);

  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const exportLog = async (fmt: 'csv' | 'json') => {
    const qs = new URLSearchParams({ category: 'audit', hours, fmt });
    if (severity) qs.set('severity', severity);
    const res = await authFetch(`/api/security/events/export?${qs.toString()}`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `audit-log.${fmt}`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="none">
          <NoPermissionState
            title="Admin access required"
            description="Only administrators can view the audit log."
          />
        </Card>
      </div></main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title={t('audit.title')}
          description={t('audit.description')}
          icon={<ScrollText className="w-5 h-5" />}
          actions={
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="md" onClick={() => exportLog('csv')}><Download className="w-4 h-4" />CSV</Button>
              <Button variant="secondary" size="md" onClick={() => exportLog('json')}><Download className="w-4 h-4" />JSON</Button>
              <Button variant="secondary" size="md" onClick={load} aria-label="Refresh"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>
            </div>
          }
        />

        <div className="flex flex-wrap gap-3 mb-6">
          <Select value={hours} onChange={(e) => setHours(e.target.value)} className="w-48">
            {WINDOWS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
          </Select>
          <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-48">
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
            <option value="info">Info</option>
          </Select>
        </div>

        {loading ? <div className="space-y-3"><SkeletonCard /><SkeletonCard /></div>
        : error ? <ErrorState title="Couldn't load audit log" description={error} onRetry={load} />
        : events.length === 0 ? <EmptyState title="No audit events" description="No sensitive actions recorded in this window." />
        : (
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-2/60 text-ink-muted text-xs">
                  <tr>
                    <th className="text-start p-3">When</th>
                    <th className="text-start p-3">Event</th>
                    <th className="text-start p-3">Actor</th>
                    <th className="text-start p-3">Detail</th>
                    <th className="text-start p-3">Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id} className="border-t border-line/60">
                      <td className="p-3 text-ink-soft whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
                      <td className="p-3"><code className="text-xs text-ink">{e.event_type}</code></td>
                      <td className="p-3 text-ink-soft">{e.actor_email ?? '—'}</td>
                      <td className="p-3 text-ink-soft">{e.detail ?? '—'}</td>
                      <td className="p-3"><Badge variant={SEV_TONE[e.severity] ?? 'neutral'}>{e.severity}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </main>
  );
}
