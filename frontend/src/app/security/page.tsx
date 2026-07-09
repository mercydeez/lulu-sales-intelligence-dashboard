'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Shield, ShieldAlert, ShieldCheck, RefreshCw, Activity, KeyRound,
  UserX, Ban, AlertTriangle, Radio, Download,
} from 'lucide-react';
import { PageHeader, Card, Badge, Button, Skeleton, EmptyState } from '@/components/ui';
import { useEventStream } from '@/hooks/useEventStream';
import { exportCsv } from '@/lib/csv';
import {
  fetchSecuritySummary, fetchSecurityEvents,
  SecuritySummary, SecurityEvent, SecuritySeverity,
} from '@/lib/api';

const SEV_STYLE: Record<SecuritySeverity, { badge: 'danger' | 'warning' | 'coral' | 'neutral'; dot: string; ring: string }> = {
  critical: { badge: 'danger', dot: 'bg-rose-600', ring: 'ring-rose-500/40' },
  high: { badge: 'coral', dot: 'bg-orange-500', ring: 'ring-orange-500/40' },
  medium: { badge: 'warning', dot: 'bg-amber-500', ring: 'ring-amber-500/30' },
  low: { badge: 'neutral', dot: 'bg-ink-muted', ring: 'ring-ink-muted/30' },
  info: { badge: 'neutral', dot: 'bg-teal-400', ring: 'ring-teal-300/30' },
};

const TYPE_ICON: Record<string, ReactNode> = {
  login_failed: <UserX className="w-4 h-4" />,
  account_locked: <Ban className="w-4 h-4" />,
  permission_denied: <ShieldAlert className="w-4 h-4" />,
  role_denied: <ShieldAlert className="w-4 h-4" />,
  rate_limited: <Activity className="w-4 h-4" />,
  csrf_failed: <ShieldAlert className="w-4 h-4" />,
  token_invalid: <KeyRound className="w-4 h-4" />,
  token_blacklisted: <KeyRound className="w-4 h-4" />,
  token_tenant_mismatch: <ShieldAlert className="w-4 h-4" />,
  api_key_invalid: <KeyRound className="w-4 h-4" />,
  api_key_created: <KeyRound className="w-4 h-4" />,
  api_key_revoked: <KeyRound className="w-4 h-4" />,
  password_changed: <KeyRound className="w-4 h-4" />,
  signup: <Activity className="w-4 h-4" />,
};

const STATUS_STYLE = {
  ok: { label: 'Secure', cls: 'text-teal-700 bg-teal-50', Icon: ShieldCheck },
  watch: { label: 'Watch', cls: 'text-amber-700 bg-amber-50', Icon: Shield },
  alert: { label: 'Alert', cls: 'text-rose-700 bg-rose-50', Icon: ShieldAlert },
};

const CATEGORY_FILTERS: { label: string; value: '' | 'threat' | 'audit' }[] = [
  { label: 'All', value: '' },
  { label: 'Threats', value: 'threat' },
  { label: 'Audit', value: 'audit' },
];

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function SecurityPage() {
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<'' | 'threat' | 'audit'>('');
  const [flash, setFlash] = useState<SecurityEvent | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([
        fetchSecuritySummary(24),
        fetchSecurityEvents(category ? { category, limit: 100 } : { limit: 100 }),
      ]);
      setSummary(s);
      setEvents(e.data);
    } catch {
      /* keep last good state */
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  // Live feed: prepend new events; flash a banner for high/critical.
  const { isConnected } = useEventStream('/stream/security', {
    eventHandlers: {
      security: (evt: SecurityEvent) => {
        setEvents((prev) => [evt, ...prev].slice(0, 200));
        if (evt.severity === 'critical' || evt.severity === 'high') {
          setFlash(evt);
          if (flashTimer.current) clearTimeout(flashTimer.current);
          flashTimer.current = setTimeout(() => setFlash(null), 8000);
        }
        // refresh KPIs shortly after a live event
        setTimeout(load, 600);
      },
    },
  });

  const sev = summary?.by_severity;
  const st = STATUS_STYLE[summary?.status ?? 'ok'];
  const shown = category ? events.filter((e) => e.category === category) : events;

  return (
    <main className="space-y-6">
      <PageHeader
        title="Security"
        description="Real-time security operations — every blocked attack and sensitive action, as it happens."
        icon={<Shield className="w-6 h-6" />}
        actions={
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${isConnected ? 'text-teal-700 bg-teal-50' : 'text-ink-muted bg-surface-2'}`}>
              <Radio className={`w-3.5 h-3.5 ${isConnected ? 'animate-pulse' : ''}`} />
              {isConnected ? 'Live' : 'Offline'}
            </span>
            <Button variant="secondary" size="sm" onClick={load}>
              <RefreshCw className="w-4 h-4 me-1.5" /> Refresh
            </Button>
            <Button
              variant="secondary" size="sm" disabled={shown.length === 0}
              onClick={() => exportCsv(
                `security-events-${new Date().toISOString().slice(0, 10)}`,
                shown.map((e) => ({
                  occurred_at: e.occurred_at, severity: e.severity, event_type: e.event_type,
                  category: e.category, actor: e.actor_email, ip: e.ip_address,
                  method: e.method, path: e.path, detail: e.detail,
                })),
              )}
            >
              <Download className="w-4 h-4 me-1.5" /> Export CSV
            </Button>
          </div>
        }
      />

      {/* Real-time high/critical banner */}
      {flash && (
        <div className="flex items-center gap-3 rounded-xl bg-rose-50 ring-1 ring-rose-200 px-4 py-3 animate-fade-in">
          <ShieldAlert className="w-5 h-5 text-rose-600 shrink-0" />
          <div className="text-sm text-rose-800">
            <span className="font-semibold uppercase">{flash.severity} · {flash.event_type}</span>
            <span className="ms-2">{flash.detail}</span>
          </div>
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card variant="glass" padding="md">
          <div className="flex items-center gap-3">
            <div className={`p-2.5 rounded-xl ${st.cls}`}><st.Icon className="w-5 h-5" /></div>
            <div>
              <div className="text-2xl font-bold text-ink">{summary?.posture_score ?? '—'}</div>
              <div className="text-xs text-ink-muted">Posture score · {st.label}</div>
            </div>
          </div>
        </Card>
        <Card variant="glass" padding="md">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-rose-50 text-rose-600"><ShieldAlert className="w-5 h-5" /></div>
            <div>
              <div className="text-2xl font-bold text-ink">{summary?.threats_active ?? 0}</div>
              <div className="text-xs text-ink-muted">Active threats (24h)</div>
            </div>
          </div>
        </Card>
        <Card variant="glass" padding="md">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-amber-50 text-amber-600"><UserX className="w-5 h-5" /></div>
            <div>
              <div className="text-2xl font-bold text-ink">{summary?.failed_logins ?? 0}</div>
              <div className="text-xs text-ink-muted">Failed logins (24h)</div>
            </div>
          </div>
        </Card>
        <Card variant="glass" padding="md">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-orange-50 text-orange-600"><Ban className="w-5 h-5" /></div>
            <div>
              <div className="text-2xl font-bold text-ink">{summary?.blocked_requests ?? 0}</div>
              <div className="text-xs text-ink-muted">Blocked requests (24h)</div>
            </div>
          </div>
        </Card>
      </div>

      {/* Severity breakdown */}
      <div className="grid grid-cols-3 md:grid-cols-5 gap-3">
        {(['critical', 'high', 'medium', 'low', 'info'] as SecuritySeverity[]).map((s) => (
          <Card key={s} variant="glass" padding="sm">
            <div className="flex items-center gap-2.5">
              <span className={`w-2.5 h-2.5 rounded-full ${SEV_STYLE[s].dot}`} />
              <div>
                <div className="text-lg font-bold text-ink leading-none">{sev?.[s] ?? 0}</div>
                <div className="text-[11px] text-ink-muted capitalize">{s}</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Category filter */}
      <div className="flex gap-2">
        {CATEGORY_FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setCategory(f.value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              category === f.value ? 'bg-teal-50 text-teal-700' : 'text-ink-muted hover:bg-surface-2'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Live event feed */}
      {loading ? (
        <div className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} width="100%" height="64px" rounded="lg" />)}</div>
      ) : shown.length === 0 ? (
        <EmptyState title="No security events" description="Nothing suspicious in this window. New events stream in live." />
      ) : (
        <div className="space-y-2">
          {shown.map((e, i) => {
            const sv = SEV_STYLE[e.severity] ?? SEV_STYLE.info;
            return (
              <Card key={e.id ?? `${e.occurred_at}-${i}`} variant="glass" padding="sm">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg text-white ${sv.dot}`}>
                    {TYPE_ICON[e.event_type] ?? <AlertTriangle className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={sv.badge} size="sm">{e.severity}</Badge>
                      <span className="text-sm font-medium text-ink">{e.event_type.replace(/_/g, ' ')}</span>
                      {e.category === 'audit' && <Badge variant="neutral" size="sm">audit</Badge>}
                    </div>
                    <p className="text-sm text-ink-soft truncate">{e.detail}</p>
                  </div>
                  <div className="text-end shrink-0">
                    <div className="text-xs text-ink-muted">{timeAgo(e.occurred_at)}</div>
                    {e.ip_address && <div className="text-[11px] text-ink-muted font-mono">{e.ip_address}</div>}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </main>
  );
}
