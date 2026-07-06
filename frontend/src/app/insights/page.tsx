'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Lightbulb, RefreshCw, CheckCircle2, Eye, AlertTriangle,
  TrendingUp, TrendingDown, Minus, Clock, Wand2, ChevronDown,
} from 'lucide-react';
import { PageHeader, Card, Badge, Button, Skeleton, EmptyState, ErrorState, Stagger, RevealItem, useToast } from '@/components/ui';
import { apiPost, ApiError } from '@/lib/apiClient';
import {
  fetchFindings,
  fetchFindingsSummary,
  acknowledgeFinding,
  resolveFinding,
  acceptFindingAction,
} from '@/lib/api';
import { Finding, FindingsSummary, FindingSeverity, FindingStatus, FindingOutcome } from '@/types';

/**
 * The findings API now attaches the Decision Center's derived intelligence
 * (same pure builders as /api/decisions — one derivation, no way to disagree).
 * Local extension type: the shared Finding hub type stays untouched.
 */
type EnrichedFinding = Finding & {
  impact?: { aed: number | null; units: number | null; per: string | null; basis: string };
  confidence?: { score: number; level: 'high' | 'medium' | 'low'; factors: string[] };
  expected_outcome?: string;
  evidence_facts?: { label: string; value: string }[];
};

/** Same confidence-pill grammar as the Decision Center, so the two surfaces read identically. */
const CONF_PILL: Record<string, string> = {
  high: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  medium: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  low: 'bg-surface-2 text-ink-muted ring-1 ring-line',
};

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
  const [findings, setFindings] = useState<EnrichedFinding[]>([]);
  const [summary, setSummary] = useState<FindingsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<FilterValue>('open');
  const [busyId, setBusyId] = useState<number | null>(null);
  const { show } = useToast();

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
      setError(null);
    } catch (e) {
      // Keep the last good state on a background-refresh failure, but remember the
      // error so a *first* load that fails doesn't masquerade as "nothing to see".
      setError(e instanceof ApiError ? e.message : 'Failed to load insights');
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

  // Autonomy level 1: draft a human-approvable action from the finding. Never executes.
  const draftAction = async (id: number) => {
    setBusyId(id);
    try {
      const d = await apiPost<{ draft_type: string }>(`/api/action-drafts/from-finding/${id}`, {});
      show(`Drafted a ${d.draft_type.replace('_', ' ')} — review it in Action Drafts`,
           { variant: 'success' });
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Could not draft action', { variant: 'error' });
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
      ) : findings.length === 0 && error ? (
        <ErrorState title="Couldn't load your insights" description={error} onRetry={load} />
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
        <Stagger className="space-y-3">
          {findings.map((f) => {
            const sev = SEVERITY_STYLES[f.severity];
            return (
              <RevealItem key={f.id}>
              <Card variant="glass" padding="md">
                <div className="flex items-start gap-4">
                  <div className={`mt-1 p-2 rounded-xl text-white ${sev.dot}`}>
                    <AlertTriangle className="w-4 h-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-ink">{f.title}</h3>
                      <Badge variant={sev.badge} size="sm">{f.severity}</Badge>
                      <Badge variant="neutral" size="sm">{f.category}</Badge>
                      {f.confidence && (
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${CONF_PILL[f.confidence.level]}`}>
                          {f.confidence.level} confidence
                        </span>
                      )}
                      {f.status !== 'open' && <Badge variant="neutral" size="sm">{f.status}</Badge>}
                    </div>
                    <p className="text-sm text-ink-soft mt-1">{f.detail}</p>
                    {f.evidence_facts && f.evidence_facts.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {f.evidence_facts.map((fact, i) => (
                          <span key={i} className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2 py-1 text-xs text-ink-soft">
                            <span className="text-ink-muted">{fact.label}</span>
                            <span className="font-semibold text-ink tabular-nums">{fact.value}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    {f.recommended_action && (
                      <div className="mt-2 rounded-lg bg-teal-50/70 px-3 py-2">
                        <div className="flex items-start gap-2">
                          <Lightbulb className="w-4 h-4 text-teal-600 mt-0.5 shrink-0" />
                          <div className="text-sm text-teal-800">
                            <span className="font-medium">Sage recommends: </span>{f.recommended_action}
                            {f.action_accepted_at && (
                              <span className="ms-1 text-xs text-teal-600">
                                · accepted by {f.action_accepted_by ?? 'a manager'}
                              </span>
                            )}
                          </div>
                        </div>
                        {f.expected_outcome && (
                          <p className="mt-1.5 ps-6 text-[13px] text-teal-800/90">
                            <span className="font-medium">Expected outcome:</span> {f.expected_outcome}
                          </p>
                        )}
                      </div>
                    )}
                    {f.confidence && f.impact && (
                      <details className="mt-2 group">
                        <summary className="flex items-center gap-1 text-xs text-ink-muted cursor-pointer select-none hover:text-ink w-fit">
                          <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" />
                          Why this confidence &amp; impact
                        </summary>
                        <div className="mt-2 ps-4 space-y-1">
                          {f.confidence.factors.map((factor, i) => (
                            <p key={i} className="text-xs text-ink-soft flex items-start gap-1.5">
                              <CheckCircle2 className="w-3 h-3 text-teal-500 mt-0.5 shrink-0" />{factor}
                            </p>
                          ))}
                          <p className="text-xs text-ink-muted">Impact basis: {f.impact.basis}.</p>
                        </div>
                      </details>
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
                      {f.recommended_action && (
                        <Button
                          variant="secondary" size="sm" disabled={busyId === f.id}
                          onClick={() => draftAction(f.id)}
                          title="Draft a concrete, human-approvable action (never auto-executed)"
                        >
                          <Wand2 className="w-4 h-4 me-1.5" /> Draft action
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
              </RevealItem>
            );
          })}
        </Stagger>
      )}
    </div>
  );
}
