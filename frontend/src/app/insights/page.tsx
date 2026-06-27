'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Lightbulb, RefreshCw, CheckCircle2, Eye, AlertTriangle,
  TrendingUp, TrendingDown, Minus, Clock,
} from 'lucide-react';
import { PageHeader, Card, Badge, Button, Skeleton, EmptyState } from '@/components/ui';
import {
  fetchFindings,
  fetchFindingsSummary,
  acknowledgeFinding,
  resolveFinding,
  acceptFindingAction,
} from '@/lib/api';
import { Finding, FindingsSummary, FindingSeverity, FindingStatus, FindingOutcome } from '@/types';

const SEVERITY_STYLES: Record<FindingSeverity, { badge: 'danger' | 'warning' | 'coral' | 'neutral'; dot: string }> = {
  critical: { badge: 'danger', dot: 'bg-rose-600' },
  high: { badge: 'coral', dot: 'bg-orange-500' },
  medium: { badge: 'warning', dot: 'bg-amber-500' },
  low: { badge: 'neutral', dot: 'bg-slate-400' },
};

// 'outcomes' is a pseudo-filter: accepted findings the measure loop has evaluated.
type FilterValue = FindingStatus | '' | 'outcomes';
const STATUS_FILTERS: { label: string; value: FilterValue }[] = [
  { label: 'Open', value: 'open' },
  { label: 'Acknowledged', value: 'acknowledged' },
  { label: 'Resolved', value: 'resolved' },
  { label: 'Outcomes', value: 'outcomes' },
  { label: 'All', value: '' },
];

const fmtPct = (n: number) => `${(n * 100).toFixed(1)}%`;

// Presentation for the measure-loop outcome of an accepted finding.
const OUTCOME_STYLES: Record<
  FindingOutcome,
  { label: string; cls: string; icon: typeof TrendingUp }
> = {
  improved: { label: 'Resolved — metric recovered after the action', cls: 'bg-emerald-50 text-emerald-700', icon: CheckCircle2 },
  unchanged: { label: 'Not yet recovered since accepted', cls: 'bg-amber-50 text-amber-700', icon: Minus },
  worsened: { label: 'Worsened since the action was accepted', cls: 'bg-rose-50 text-rose-700', icon: TrendingDown },
  pending: { label: 'Awaiting outcome measurement', cls: 'bg-slate-50 text-ink-muted', icon: Clock },
};

function OutcomeBlock({ f }: { f: Finding }) {
  if (!f.action_accepted_at) return null;
  const o = OUTCOME_STYLES[f.outcome_status] ?? OUTCOME_STYLES.pending;
  const Icon = o.icon;
  const before = f.metric_before;
  const after = f.metric_after;
  const delta =
    before != null && after != null
      ? ` (${fmtPct(before)} → ${fmtPct(after)})`
      : before != null && f.outcome_status === 'improved'
      ? ` (was ${fmtPct(before)})`
      : '';
  return (
    <div className={`mt-2 flex items-start gap-2 rounded-lg px-3 py-2 ${o.cls}`}>
      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="text-sm">
        <span className="font-medium">{o.label}</span>{delta}
        {f.measured_at && (
          <span className="ms-1 text-xs opacity-75">
            · measured {new Date(f.measured_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  );
}

export default function InsightsPage() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [summary, setSummary] = useState<FindingsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<FilterValue>('open');
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const findingsParams =
        status === 'outcomes'
          ? { measured: true, limit: 100 }
          : status
          ? { status, limit: 100 }
          : { limit: 100 };
      const [f, s] = await Promise.all([
        fetchFindings(findingsParams),
        fetchFindingsSummary(),
      ]);
      setFindings(f.data);
      setSummary(s);
    } catch {
      /* keep last good state */
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    setLoading(true);
    load();
    const id = setInterval(load, 30000); // diagnostics refresh on the worker's cadence
    return () => clearInterval(id);
  }, [load]);

  const act = async (id: number, action: 'ack' | 'resolve' | 'accept') => {
    setBusyId(id);
    try {
      if (action === 'ack') await acknowledgeFinding(id);
      else if (action === 'resolve') await resolveFinding(id);
      else await acceptFindingAction(id);
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const counts = summary?.by_severity ?? {};

  return (
    <div className="space-y-6">
      <PageHeader
        title="Insights"
        description="What's going wrong — and why. Detected automatically from your live data."
        icon={<Lightbulb className="w-6 h-6" />}
        actions={
          <Button variant="secondary" size="sm" onClick={load}>
            <RefreshCw className="w-4 h-4 me-1.5" /> Refresh
          </Button>
        }
      />

      {/* Severity summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {(['critical', 'high', 'medium', 'low'] as FindingSeverity[]).map((sev) => (
          <Card key={sev} variant="glass" padding="md">
            <div className="flex items-center gap-3">
              <span className={`w-2.5 h-2.5 rounded-full ${SEVERITY_STYLES[sev].dot}`} />
              <div>
                <div className="text-2xl font-bold text-ink">{counts[sev] ?? 0}</div>
                <div className="text-xs text-ink-muted capitalize">{sev}</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Status filter */}
      <div className="flex gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setStatus(f.value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              status === f.value ? 'bg-teal-50 text-teal-700' : 'text-ink-muted hover:bg-surface-2'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Findings list */}
      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} width="100%" height="92px" rounded="lg" />)}
        </div>
      ) : findings.length === 0 ? (
        <EmptyState
          title="No findings"
          description={
            status === 'open'
              ? 'Nothing needs attention right now. The diagnostics worker scans every few minutes.'
              : status === 'outcomes'
              ? 'No accepted actions have been measured yet. Accept a recommended action, and the worker will track whether the metric recovers.'
              : 'No findings match this filter.'
          }
        />
      ) : (
        <div className="space-y-3">
          {findings.map((f) => {
            const sev = SEVERITY_STYLES[f.severity];
            return (
              <Card key={f.id} variant="glass" padding="md">
                <div className="flex items-start gap-4">
                  <div className={`mt-1 p-2 rounded-xl text-white ${sev.dot}`}>
                    <AlertTriangle className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-ink">{f.title}</h3>
                      <Badge variant={sev.badge} size="sm">{f.severity}</Badge>
                      <Badge variant="neutral" size="sm">{f.category}</Badge>
                      {f.status !== 'open' && <Badge variant="neutral" size="sm">{f.status}</Badge>}
                    </div>
                    <p className="text-sm text-ink-soft mt-1">{f.detail}</p>
                    {f.recommended_action && (
                      <div className="mt-2 flex items-start gap-2 rounded-lg bg-teal-50/70 px-3 py-2">
                        <Lightbulb className="w-4 h-4 text-teal-600 mt-0.5 shrink-0" />
                        <div className="text-sm text-teal-800">
                          <span className="font-medium">Recommended: </span>{f.recommended_action}
                          {f.action_accepted_at && (
                            <span className="ms-1 text-xs text-teal-600">
                              · accepted by {f.action_accepted_by ?? 'a manager'}
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    <OutcomeBlock f={f} />
                    {f.entity_name && (
                      <p className="text-xs text-ink-muted mt-1">
                        {f.entity_type}: {f.entity_name} ·{' '}
                        detected {new Date(f.detected_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                  {f.status !== 'resolved' && (
                    <div className="flex flex-col gap-2 shrink-0">
                      {f.recommended_action && !f.action_accepted_at && (
                        <Button
                          variant="secondary" size="sm" disabled={busyId === f.id}
                          onClick={() => act(f.id, 'accept')}
                          title="Accept the recommended action (records your decision)"
                        >
                          <Lightbulb className="w-4 h-4 me-1.5" /> Accept action
                        </Button>
                      )}
                      {f.status === 'open' && (
                        <Button
                          variant="secondary" size="sm" disabled={busyId === f.id}
                          onClick={() => act(f.id, 'ack')}
                        >
                          <Eye className="w-4 h-4 me-1.5" /> Acknowledge
                        </Button>
                      )}
                      <Button
                        variant="primary" size="sm" disabled={busyId === f.id}
                        onClick={() => act(f.id, 'resolve')}
                      >
                        <CheckCircle2 className="w-4 h-4 me-1.5" /> Resolve
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
