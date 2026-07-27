'use client';

/**
 * Operations Copilot (Phase 4) — the human-in-the-loop queue for evidence-backed
 * action proposals. Mirrors insights/page.tsx: a status-tabbed queue on the left,
 * a detail Modal that renders the proposal's grounded recommendation, human
 * approve/reject/cancel controls (OCC via proposal.version), an audit timeline,
 * and honest data-provenance labelling. Live via SSE /stream/operations.
 */
import { useMemo, useState } from 'react';
import {
  ClipboardCheck, RefreshCw, AlertTriangle, ShieldAlert, Clock, FlaskConical,
  CheckCircle2, XCircle, Ban, FileText, Beaker, Layers, Info,
  FilePlus2, Search, ShieldCheck, Send, TimerOff, Sparkles,
} from 'lucide-react';
import {
  PageHeader, Card, Badge, Button, StatCard, Tabs, Modal, Skeleton,
  EmptyState, ErrorState, StatusBanner, useToast,
} from '@/components/ui';
import { ApiError } from '@/lib/apiClient';
import { useAuth } from '@/contexts/AuthContext';
import { useEventStream } from '@/hooks/useEventStream';
import { useQueryClient } from '@tanstack/react-query';
import {
  useBriefing, useOperationsMetrics, useRun, useProposalAudit,
  useApproveProposal, useRejectProposal, useCancelProposal,
  operationsKeys, Proposal, Evidence, AuditEvent,
  MeasuredFact, Hypothesis, ProposedAction,
} from '@/lib/queries/operations';

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

const RISK_BADGE: Record<string, 'danger' | 'coral' | 'warning' | 'neutral'> = {
  critical: 'danger', high: 'coral', medium: 'warning', low: 'neutral',
};
const riskBadge = (r?: string | null) => RISK_BADGE[(r ?? '').toLowerCase()] ?? 'neutral';

/** Relative expiry label (not live-ticking — SSE + query refetch keep it fresh). */
function expiryLabel(iso: string | null | undefined): { text: string; expired: boolean } {
  if (!iso) return { text: 'no expiry', expired: false };
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return { text: 'expired', expired: true };
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return { text: `expires in ${mins}m`, expired: false };
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return { text: `expires in ${hrs}h ${mins % 60}m`, expired: false };
  return { text: `expires in ${Math.floor(hrs / 24)}d`, expired: false };
}

const fmtDate = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—');

/** Provenance that is not first-party measurement — flag it as estimated. */
const ESTIMATED_SOURCES = new Set(['derived', 'inventory']);

// Audit event vocabulary → label + icon (backend services/operations/*.py).
const EVENT_META: Record<string, { label: string; icon: typeof Info; tone: string }> = {
  'run.created': { label: 'Run started', icon: FilePlus2, tone: 'text-blue-500' },
  'policy.invalid': { label: 'Blocked by policy', icon: ShieldAlert, tone: 'text-rose-500' },
  'finding.not_found': { label: 'Finding not found', icon: XCircle, tone: 'text-rose-500' },
  'finding.loaded': { label: 'Finding loaded', icon: Search, tone: 'text-ink-muted' },
  'finding.fresh': { label: 'Finding still valid', icon: CheckCircle2, tone: 'text-teal-500' },
  'finding.stale': { label: 'Finding stale', icon: TimerOff, tone: 'text-amber-500' },
  'evidence.gathered': { label: 'Evidence gathered', icon: Layers, tone: 'text-violet-500' },
  'proposal.drafted': { label: 'Proposal drafted', icon: FileText, tone: 'text-blue-500' },
  'recommendation.refused': { label: 'Recommendation refused', icon: Ban, tone: 'text-ink-muted' },
  'narrate.skipped': { label: 'AI narrative skipped', icon: Info, tone: 'text-ink-muted' },
  'narrate.fallback': { label: 'Deterministic narrative used', icon: Info, tone: 'text-amber-500' },
  'narrate.rejected': { label: 'Ungrounded narrative rejected', icon: ShieldCheck, tone: 'text-amber-500' },
  'narrate.applied': { label: 'AI narrative applied', icon: Sparkles, tone: 'text-violet-500' },
  'run.timeout': { label: 'Run timed out', icon: TimerOff, tone: 'text-rose-500' },
  'run.failed': { label: 'Run failed', icon: AlertTriangle, tone: 'text-rose-500' },
  'proposal.expired': { label: 'Proposal expired', icon: TimerOff, tone: 'text-ink-muted' },
  'approval.denied': { label: 'Approval denied', icon: ShieldAlert, tone: 'text-rose-500' },
  'approval.granted': { label: 'Approved', icon: CheckCircle2, tone: 'text-teal-500' },
  'approval.rejected': { label: 'Rejected', icon: XCircle, tone: 'text-rose-500' },
  'proposal.cancelled': { label: 'Cancelled', icon: Ban, tone: 'text-ink-muted' },
  'action.executed': { label: 'Draft written', icon: Send, tone: 'text-teal-600' },
};

function ago(iso: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Queue tabs. Only 'awaiting_approval' has a live list from /briefing; the rest
// carry counts from the run/proposal status maps (the endpoint returns no list
// for them), so those tabs show a count + an honest note rather than fake rows.
const TABS: { id: string; label: string; source: 'proposals' | 'runs' }[] = [
  { id: 'awaiting_approval', label: 'Awaiting approval', source: 'proposals' },
  { id: 'analyzing', label: 'Analyzing', source: 'runs' },
  { id: 'measuring', label: 'Measuring', source: 'runs' },
  { id: 'completed', label: 'Completed', source: 'runs' },
  { id: 'escalated', label: 'Escalated', source: 'runs' },
  { id: 'refused', label: 'Refused', source: 'runs' },
];

// ---------------------------------------------------------------------------
// Audit timeline (mirrors AuditTimeline.tsx for the operations event shape)
// ---------------------------------------------------------------------------

function OperationsAuditTimeline({ proposalId }: { proposalId: number }) {
  const { data, isLoading } = useProposalAudit(proposalId);
  const events: AuditEvent[] = data?.events ?? [];
  if (isLoading) return <Skeleton width="100%" height="120px" rounded="lg" />;
  if (events.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-semibold text-ink mb-3">Audit trail</h4>
      <ol className="relative border-s border-line ms-2">
        {events.map((e, i) => {
          const meta = EVENT_META[e.event_type] ?? { label: e.event_type, icon: Info, tone: 'text-ink-muted' };
          const Icon = meta.icon;
          return (
            <li key={i} className="mb-5 ms-5">
              <span className={`absolute -start-[9px] flex items-center justify-center w-[18px] h-[18px] rounded-full bg-surface ${meta.tone}`}>
                <Icon className="w-3.5 h-3.5" />
              </span>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-sm text-ink">{meta.label}</p>
                <span className="text-xs text-ink-muted shrink-0">{ago(e.created_at)}</span>
              </div>
              {e.actor && <p className="text-xs text-ink-muted mt-0.5">{e.actor}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recommendation detail
// ---------------------------------------------------------------------------

function EvidenceTable({ evidence }: { evidence: Evidence[] }) {
  const hasEstimated = evidence.some((e) => ESTIMATED_SOURCES.has((e.source_type ?? '').toLowerCase()));
  return (
    <div>
      {hasEstimated && (
        <StatusBanner variant="warning" className="mb-3">
          Estimated from seeded data — no POS/ERP connected. Values marked
          <Badge variant="warning" size="sm" className="mx-1">estimated</Badge>
          are derived, not measured from a live source of record.
        </StatusBanner>
      )}
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-start text-[11px] uppercase tracking-wide text-ink-muted border-b border-line">
              <th className="text-start font-medium px-3 py-2">Metric</th>
              <th className="text-start font-medium px-3 py-2">Value</th>
              <th className="text-start font-medium px-3 py-2">Unit</th>
              <th className="text-start font-medium px-3 py-2">Source</th>
              <th className="text-start font-medium px-3 py-2">Observed</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((e, i) => {
              const estimated = ESTIMATED_SOURCES.has((e.source_type ?? '').toLowerCase());
              return (
                <tr key={e.evidence_id ?? i} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 text-ink">{e.metric_name}</td>
                  <td className="px-3 py-2 text-ink tabular-nums">
                    {String(e.current_value ?? '—')}
                    {e.comparison_value != null && (
                      <span className="text-ink-muted"> vs {String(e.comparison_value)}
                        {e.comparison_period ? ` (${e.comparison_period})` : ''}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-ink-soft">{e.unit ?? '—'}</td>
                  <td className="px-3 py-2">
                    <span className="text-ink-soft">{e.source_type}</span>
                    {estimated && <Badge variant="warning" size="sm" className="ms-1.5">estimated</Badge>}
                    {e.source_reference && (
                      <span className="block text-xs text-ink-muted">{e.source_reference}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-muted">{fmtDate(e.observed_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Render calculated_parameters, giving _steps / _assumptions arrays a friendlier layout. */
function CalculatedParameters({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params);
  if (entries.length === 0) return null;
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => {
        const isList = (key.endsWith('_steps') || key.endsWith('_assumptions')) && Array.isArray(value);
        if (isList) {
          return (
            <div key={key}>
              <p className="text-xs font-medium text-ink-muted capitalize mb-1">{key.replace(/_/g, ' ')}</p>
              <ul className="space-y-1 ps-1">
                {(value as unknown[]).map((v, i) => (
                  <li key={i} className="text-sm text-ink-soft flex items-start gap-2">
                    <span className="mt-1.5 w-1 h-1 rounded-full bg-ink-muted shrink-0" />
                    {String(v)}
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        return (
          <div key={key} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink-muted capitalize">{key.replace(/_/g, ' ')}</span>
            <span className="text-ink font-medium tabular-nums text-end">
              {typeof value === 'object' ? JSON.stringify(value) : String(value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-ink">{title}</h4>
      {children}
    </div>
  );
}

function BulletList({ items, tone = 'text-ink-soft' }: { items: string[]; tone?: string }) {
  return (
    <ul className="space-y-1">
      {items.map((s, i) => (
        <li key={i} className={`text-sm ${tone} flex items-start gap-2`}>
          <span className="mt-1.5 w-1 h-1 rounded-full bg-current opacity-50 shrink-0" />{s}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Detail modal
// ---------------------------------------------------------------------------

function DetailModal({ proposal, onClose }: { proposal: Proposal; onClose: () => void }) {
  const { hasPermission, hasRole } = useAuth();
  const { show } = useToast();
  const { data, isLoading, isError } = useRun(proposal.run_id);
  const approve = useApproveProposal();
  const reject = useRejectProposal();
  const cancel = useCancelProposal();
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState('');

  const canApprove =
    hasPermission('can_manage_inventory') ||
    hasRole(['super_admin', 'regional_manager', 'store_manager']);

  // Full record (with recommendation/status) comes from the run fetch; fall back
  // to the lean queue item while it loads.
  const full = data?.proposals.find((p: Proposal) => p.id === proposal.id) ?? proposal;
  const run = data?.run;
  const rec = full.recommendation ?? null;
  const busy = approve.isPending || reject.isPending || cancel.isPending;
  const decided = full.status != null && full.status !== 'awaiting_approval';

  const onError = (e: unknown) => {
    if (e instanceof ApiError && e.status === 409) {
      show('This proposal changed since you loaded it — refresh and try again.', { variant: 'error' });
    } else {
      show(e instanceof ApiError ? e.message : 'Action failed', { variant: 'error' });
    }
  };

  const doApprove = () =>
    approve.mutate({ id: full.id, version: full.version }, {
      onSuccess: (r) => { show(`Approved — ${r.executed_ref ?? 'draft written'}.`, { variant: 'success' }); onClose(); },
      onError,
    });
  const doReject = () =>
    reject.mutate({ id: full.id, version: full.version, reason: reason.trim() }, {
      onSuccess: () => { show('Rejected.', { variant: 'info' }); setRejectOpen(false); onClose(); },
      onError,
    });
  const doCancel = () =>
    cancel.mutate({ id: full.id, version: full.version }, {
      onSuccess: () => { show('Cancelled.', { variant: 'info' }); onClose(); },
      onError,
    });

  const measuring = run && (run.status === 'measuring' || run.status === 'completed');

  return (
    <Modal open onClose={onClose} title={full.title} size="lg">
      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} width="100%" height="64px" rounded="lg" />)}
        </div>
      ) : isError || !rec ? (
        <div className="space-y-4">
          <StatusBanner variant="info">
            No detailed recommendation is attached to this proposal yet.
          </StatusBanner>
          {run?.refusal_reason && (
            <p className="text-sm text-ink-soft">Refusal reason: {run.refusal_reason}</p>
          )}
        </div>
      ) : (
        <div className="space-y-5 max-h-[70vh] overflow-y-auto pe-1">
          {/* Header badges */}
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="neutral" size="sm">{full.action_type}</Badge>
            <Badge variant={riskBadge(full.risk_level)} size="sm">risk: {full.risk_level ?? 'n/a'}</Badge>
            {full.required_approval_role && (
              <Badge variant="violet" size="sm">approver: {full.required_approval_role}</Badge>
            )}
            {full.status && <Badge variant="neutral" size="sm">{full.status}</Badge>}
            {rec.confidence != null && (
              <span className="text-xs text-ink-muted">confidence {(rec.confidence * 100).toFixed(0)}%</span>
            )}
          </div>

          {/* Honesty banners */}
          {rec.llm_available === false && (
            <StatusBanner variant="info">
              AI narrative unavailable — deterministic recommendation.
            </StatusBanner>
          )}

          {rec.executive_summary && (
            <p className="text-sm text-ink-soft leading-relaxed">{rec.executive_summary}</p>
          )}

          {/* Measured facts vs hypotheses — kept clearly separated */}
          {rec.measured_facts && rec.measured_facts.length > 0 && (
            <Section title="Measured facts">
              <div className="rounded-xl bg-teal-50/70 dark:bg-teal-500/10 p-3">
                <BulletList items={rec.measured_facts.map((f: MeasuredFact) => f.statement)} tone="text-teal-800 dark:text-teal-200" />
              </div>
            </Section>
          )}
          {rec.hypotheses && rec.hypotheses.length > 0 && (
            <Section title="Hypotheses (unproven)">
              <div className="rounded-xl bg-amber-50/70 dark:bg-amber-500/10 p-3">
                <ul className="space-y-1.5">
                  {rec.hypotheses.map((h: Hypothesis, i: number) => (
                    <li key={i} className="text-sm text-amber-900 dark:text-amber-200">
                      <span className="flex items-start gap-2">
                        <span className="mt-1.5 w-1 h-1 rounded-full bg-current opacity-50 shrink-0" />
                        <span>{h.statement}{h.check && <span className="block text-xs opacity-80">check: {h.check}</span>}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </Section>
          )}

          {/* Evidence */}
          {rec.evidence && rec.evidence.length > 0 && (
            <Section title="Evidence"><EvidenceTable evidence={rec.evidence} /></Section>
          )}

          {/* Proposed actions */}
          {rec.proposed_actions && rec.proposed_actions.length > 0 && (
            <Section title="Proposed action">
              {rec.proposed_actions.map((a: ProposedAction, i: number) => (
                <Card key={i} variant="solid" padding="md" className="space-y-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-ink">{a.title}</span>
                    <Badge variant="neutral" size="sm">{a.action_type}</Badge>
                    {a.risk_level && <Badge variant={riskBadge(a.risk_level)} size="sm">{a.risk_level}</Badge>}
                    {a.reversible != null && (
                      <Badge variant={a.reversible ? 'teal' : 'coral'} size="sm">
                        {a.reversible ? 'reversible' : 'irreversible'}
                      </Badge>
                    )}
                  </div>
                  {a.description && <p className="text-sm text-ink-soft">{a.description}</p>}
                  {a.expected_effect && (
                    <p className="text-sm text-ink-soft">
                      <span className="font-medium text-ink">Expected effect:</span> {a.expected_effect}
                      {a.expected_effect_basis && <span className="text-ink-muted"> ({a.expected_effect_basis})</span>}
                    </p>
                  )}
                  {a.calculated_parameters && Object.keys(a.calculated_parameters).length > 0 && (
                    <div className="rounded-lg bg-surface-2/60 p-3">
                      <CalculatedParameters params={a.calculated_parameters} />
                    </div>
                  )}
                  {/* Draft-only honesty label — never presented as a submitted order */}
                  <StatusBanner variant="info">
                    Internal draft — not submitted to any supplier.
                  </StatusBanner>
                </Card>
              ))}
            </Section>
          )}

          {/* Also render the proposal-level calculated_parameters if present */}
          {full.calculated_parameters && Object.keys(full.calculated_parameters).length > 0 && !rec.proposed_actions?.length && (
            <Section title="Calculated parameters">
              <div className="rounded-lg bg-surface-2/60 p-3">
                <CalculatedParameters params={full.calculated_parameters} />
              </div>
            </Section>
          )}

          {rec.risks && rec.risks.length > 0 && (
            <Section title="Risks"><BulletList items={rec.risks} tone="text-coral-700 dark:text-coral-300" /></Section>
          )}
          {rec.missing_data && rec.missing_data.length > 0 && (
            <Section title="Missing data"><BulletList items={rec.missing_data} /></Section>
          )}
          {rec.assumptions && rec.assumptions.length > 0 && (
            <Section title="Assumptions"><BulletList items={rec.assumptions} /></Section>
          )}

          {/* Approver requirement */}
          {rec.approval_requirement && (
            <Section title="Required approver">
              <p className="text-sm text-ink-soft">
                <span className="font-medium text-ink capitalize">
                  {rec.approval_requirement.required_role ?? full.required_approval_role ?? 'manager'}
                </span>
                {rec.approval_requirement.reason && <span> — {rec.approval_requirement.reason}</span>}
              </p>
            </Section>
          )}

          {/* Measurement plan */}
          {rec.measurement_plan && (
            <Section title="Measurement plan">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-ink-muted block text-xs">Metric</span>{rec.measurement_plan.metric_name ?? '—'}</div>
                <div><span className="text-ink-muted block text-xs">Baseline</span>
                  {String(rec.measurement_plan.baseline_value ?? '—')} {rec.measurement_plan.unit ?? ''}</div>
                <div><span className="text-ink-muted block text-xs">Window</span>{rec.measurement_plan.window_days ?? '—'} days</div>
                <div><span className="text-ink-muted block text-xs">Success criterion</span>{rec.measurement_plan.success_criterion ?? '—'}</div>
              </div>
            </Section>
          )}

          {/* Outcome panel */}
          {measuring && (
            <StatusBanner variant="success" title="Outcome tracking active">
              Baseline {String(rec.measurement_plan?.baseline_value ?? '—')} {rec.measurement_plan?.unit ?? ''}.
              The outcome is tracked automatically by the measure loop over the next
              {' '}{rec.measurement_plan?.window_days ?? '—'} days.
            </StatusBanner>
          )}

          {/* Audit timeline */}
          <OperationsAuditTimeline proposalId={full.id} />

          {/* Human controls */}
          {canApprove && !decided && (
            <div className="flex flex-wrap gap-2 pt-2 border-t border-line">
              <Button variant="primary" size="sm" disabled={busy} loading={approve.isPending} onClick={doApprove}>
                <CheckCircle2 className="w-4 h-4 me-1.5" /> Approve
              </Button>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => setRejectOpen(true)}>
                <XCircle className="w-4 h-4 me-1.5" /> Reject
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} loading={cancel.isPending} onClick={doCancel}>
                <Ban className="w-4 h-4 me-1.5" /> Cancel
              </Button>
            </div>
          )}
          {decided && (
            <p className="text-sm text-ink-muted pt-2 border-t border-line">
              This proposal is {full.status} — no further action available.
            </p>
          )}
        </div>
      )}

      {/* Reject reason modal */}
      <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject proposal" size="sm">
        <div className="space-y-3">
          <label className="text-sm text-ink-soft" htmlFor="reject-reason">
            Reason (recorded in the audit trail)
          </label>
          <textarea
            id="reject-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-teal-500/40"
            placeholder="Why is this being rejected?"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRejectOpen(false)}>Cancel</Button>
            <Button variant="danger" size="sm" disabled={!reason.trim() || reject.isPending}
              loading={reject.isPending} onClick={doReject}>
              Reject
            </Button>
          </div>
        </div>
      </Modal>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Queue card
// ---------------------------------------------------------------------------

function ProposalCard({ p, onOpen }: { p: Proposal; onOpen: () => void }) {
  const exp = expiryLabel(p.expires_at);
  return (
    <Card variant="glass" padding="md" hover="lift" className="cursor-pointer" onClick={onOpen}>
      <div className="flex items-start gap-4 flex-wrap sm:flex-nowrap">
        <div className="mt-1 p-2 rounded-xl bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300 shrink-0">
          <ClipboardCheck className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-ink">{p.title}</h3>
            <Badge variant="neutral" size="sm">{p.action_type}</Badge>
            <Badge variant={riskBadge(p.risk_level)} size="sm">{p.risk_level ?? 'n/a'}</Badge>
            {p.required_approval_role && <Badge variant="violet" size="sm">{p.required_approval_role}</Badge>}
          </div>
          <p className="text-xs text-ink-muted mt-1 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            <span className={exp.expired ? 'text-coral-600' : ''}>{exp.text}</span>
            <span className="text-ink-muted">· created {fmtDate(p.created_at)}</span>
          </p>
        </div>
        <Button variant="secondary" size="sm" className="shrink-0" onClick={(e) => { e.stopPropagation(); onOpen(); }}>
          Review
        </Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OperationsPage() {
  const qc = useQueryClient();
  const { data: briefing, isLoading, isError, refetch } = useBriefing();
  const { data: metrics } = useOperationsMetrics();
  const [tab, setTab] = useState('awaiting_approval');
  const [selected, setSelected] = useState<Proposal | null>(null);

  // Live: any run/proposal transition refetches the queue + metrics. Handlers are
  // memoized so useEventStream doesn't re-subscribe on every render.
  const eventHandlers = useMemo(
    () => ({ operations: () => { qc.invalidateQueries({ queryKey: operationsKeys.all }); } }),
    [qc],
  );
  const { isConnected } = useEventStream('/stream/operations', { eventHandlers });

  const countFor = (t: typeof TABS[number]) =>
    (t.source === 'proposals'
      ? briefing?.proposals_by_status?.[t.id]
      : briefing?.runs_by_status?.[t.id]) ?? 0;

  const awaiting = briefing?.awaiting_approval ?? [];

  return (
    <main className="space-y-6">
      <PageHeader
        title="Operations Copilot"
        description="Evidence-backed action proposals awaiting a human decision. Every draft is internal — nothing is sent to a supplier without your approval."
        icon={<ClipboardCheck className="w-6 h-6" />}
        actions={
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4 me-1.5" /> Refresh
          </Button>
        }
      />

      {/* Metrics row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Runs" value={metrics?.runs_total ?? 0} tone="teal" icon={<FlaskConical className="w-4 h-4" />} />
        <StatCard label="Awaiting / Approved" value={`${briefing?.proposals_by_status?.awaiting_approval ?? 0} / ${metrics?.approved ?? 0}`} tone="violet" icon={<CheckCircle2 className="w-4 h-4" />} />
        <StatCard label="Refused / Escalated" value={metrics?.refused_or_escalated ?? 0} tone="amber" icon={<ShieldAlert className="w-4 h-4" />} />
        <StatCard label="Executed drafts" value={metrics?.executed ?? 0} tone="teal" icon={<Send className="w-4 h-4" />}
          footnote={isConnected ? 'live' : 'reconnecting…'} />
      </div>

      {/* Queue tabs */}
      <div className="overflow-x-auto">
        <Tabs
          items={TABS.map((t) => ({
            id: t.id,
            label: t.label,
            badge: <span className="ms-1 text-xs text-ink-muted tabular-nums">{countFor(t)}</span>,
          }))}
          value={tab}
          onChange={setTab}
        />
      </div>

      {/* Queue body */}
      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} width="100%" height="88px" rounded="lg" />)}</div>
      ) : isError ? (
        <ErrorState title="Couldn't load the operations queue" description="The briefing endpoint failed." onRetry={() => refetch()} />
      ) : tab === 'awaiting_approval' ? (
        awaiting.length === 0 ? (
          <EmptyState title="Nothing awaiting approval" description="When the copilot drafts an action from a finding, it lands here for your decision." />
        ) : (
          <div className="space-y-3">
            {awaiting.map((p: Proposal) => <ProposalCard key={p.id} p={p} onOpen={() => setSelected(p)} />)}
          </div>
        )
      ) : (
        <Card variant="glass" padding="lg">
          <div className="flex items-center gap-3 text-ink-soft">
            <Beaker className="w-5 h-5 text-ink-muted" />
            <p className="text-sm">
              <span className="font-semibold text-ink tabular-nums">{countFor(TABS.find((t) => t.id === tab)!)}</span>
              {' '}run{countFor(TABS.find((t) => t.id === tab)!) === 1 ? '' : 's'} in <span className="font-medium">{TABS.find((t) => t.id === tab)!.label.toLowerCase()}</span>.
              Open items surface under <span className="font-medium">Awaiting approval</span> once a proposal is drafted.
            </p>
          </div>
        </Card>
      )}

      {selected && <DetailModal proposal={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
