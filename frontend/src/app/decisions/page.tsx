'use client';

/**
 * AI Decision Center (blueprint E3-2) — triage, not a list.
 * Sage reads the whole queue and hands the executive only the 3 calls that need
 * them, routing the rest to regional managers, store managers, or its own
 * automation — each with a plain-language reason. Cognitive load: ~3 cards, not 55.
 * Every card still carries problem, AED impact (derived; units where returns have
 * no price), evidence, confidence, action, and expected outcome. Approve/dismiss
 * reuse the findings endpoints so the measure loop proves whether it worked.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import {
  Button, ErrorState, SkeletonCard, Stagger, RevealItem, useToast,
} from '@/components/ui';
import { apiGet, apiPost, ApiError } from '@/lib/apiClient';
import { acceptFindingAction, resolveFinding, acknowledgeFinding } from '@/lib/api';
import {
  Sparkles, RefreshCw, Inbox, CheckCircle2, ArrowRight, Wand2, MapPin, Store, Bot,
  ThumbsUp, X, Scale, ChevronDown, Timer,
} from 'lucide-react';

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

interface Impact { aed: number | null; units: number | null; per: string | null; basis: string }
interface Confidence { score: number; level: 'high' | 'medium' | 'low'; factors: string[] }
interface Fact { label: string; value: string }
interface Decided {
  accepted_by: string | null; accepted_at: string | null;
  outcome_status: 'pending' | 'improved' | 'unchanged' | 'worsened';
  metric_before: number | null; metric_after: number | null; measured_at: string | null;
}
interface Decision {
  id: number | null; kind: 'finding' | 'reorder'; rule: string; severity: string;
  state: 'pending' | 'decided'; problem: string; detail: string;
  entity_name: string | null; entity_id?: string | null; category: string | null;
  region?: string; routing_reason?: string;
  impact: Impact; confidence: Confidence; evidence: Fact[];
  recommended_action: string; action_type: string | null; expected_outcome: string;
  detected_at: string | null; href: string; decision?: Decided;
}
interface RegionGroup { name: string; count: number; aed: number; decisions: Decision[] }
interface Lane {
  key: 'regional' | 'store' | 'automate'; label: string; reason: string;
  count: number; aed: number; decisions: Decision[]; automate: boolean; groups?: RegionGroup[];
}
interface Triage {
  total: number; at_stake_aed_per_week: number; routed_count: number;
  executive: { reason: string; decisions: Decision[]; more: { count: number; aed: number; decisions: Decision[] } };
  lanes: Lane[];
}
interface DecidedResponse { decisions: Decision[]; count: number }

const SEV_HEX: Record<string, string> = {
  critical: '#f43f5e', high: '#f97316', medium: '#f59e0b', low: '#0f766e',
};
const SEV_TEXT: Record<string, string> = {
  critical: 'text-rose-600', high: 'text-orange-600', medium: 'text-amber-600', low: 'text-teal-600',
};
const sevBar = (sev: string): React.CSSProperties => ({
  borderInlineStartWidth: '3px', borderInlineStartColor: SEV_HEX[sev] ?? SEV_HEX.low,
});
const CONF_PILL: Record<string, string> = {
  high: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  medium: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  low: 'bg-surface-2 text-ink-muted ring-1 ring-line',
};
const OUTCOME_BADGE: Record<string, { text: string; cls: string }> = {
  pending: { text: 'Measuring…', cls: 'bg-surface-2 text-ink-muted ring-1 ring-line' },
  improved: { text: 'Worked — metric recovered', cls: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' },
  unchanged: { text: 'No change yet', cls: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200' },
  worsened: { text: 'Worsened', cls: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200' },
};
const LANE_ICON = { regional: MapPin, store: Store, automate: Bot } as const;

export default function DecisionsPage() {
  const { user } = useAuth();
  const { show } = useToast();
  const [tab, setTab] = useState<'pending' | 'decided'>('pending');
  const [triage, setTriage] = useState<Triage | null>(null);
  const [decided, setDecided] = useState<DecidedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  // Single-slot undo for the last dismissal (acknowledge() reopens it server-side).
  const [undoable, setUndoable] = useState<{ id: number; problem: string } | null>(null);

  const fetchAll = useCallback(async () => {
    const [t, d] = await Promise.all([
      apiGet<Triage>('/api/decisions/triage'),
      apiGet<DecidedResponse>('/api/decisions?state=decided'),
    ]);
    setTriage(t); setDecided(d);
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null); setUndoable(null);
    try { await fetchAll(); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Failed to load decisions'); }
    finally { setLoading(false); }
  }, [fetchAll]);
  useEffect(() => { load(); }, [load]);

  // After acting, silently re-triage so the next-ranked decision promotes in.
  const refresh = useCallback(() => { fetchAll().catch(() => {}); }, [fetchAll]);

  const act = async (d: Decision, kind: 'approve' | 'dismiss' | 'draft') => {
    if (d.id == null) return;
    setBusy(d.id);
    try {
      if (kind === 'approve') {
        await acceptFindingAction(d.id);
        show('Decision recorded — Sage will measure the outcome and report back.', { variant: 'success' });
      } else if (kind === 'dismiss') {
        await resolveFinding(d.id);
        setUndoable({ id: d.id, problem: d.problem }); // the undo bar carries the message
      } else {
        await apiPost(`/api/action-drafts/from-finding/${d.id}`);
        show('Draft created — review and approve it in Action Drafts.', { variant: 'success', title: 'Sage drafted the action' });
      }
      if (kind !== 'draft') refresh();
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Action failed', { variant: 'error' });
    } finally { setBusy(null); }
  };

  const undoDismiss = async () => {
    if (!undoable) return;
    const { id } = undoable;
    setBusy(id);
    try {
      await acknowledgeFinding(id); // reopens: back into the pending queue
      setUndoable(null);
      show('Reopened — back in your queue.', { variant: 'info' });
      refresh();
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Undo failed', { variant: 'error' });
    } finally { setBusy(null); }
  };

  const cardProps = (d: Decision) => ({
    d, busy: busy === d.id,
    onApprove: () => act(d, 'approve'), onDismiss: () => act(d, 'dismiss'), onDraft: () => act(d, 'draft'),
  });
  const firstName = (user?.email ?? '').split('@')[0].split(/[._-]/)[0];
  const exec = triage?.executive.decisions ?? [];

  return (
    <main className="min-h-screen px-4 md:px-8 py-6 md:py-10">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-6">
          <div className="flex items-start gap-3">
            <span className="flex items-center justify-center w-10 h-10 rounded-2xl sunset-gradient shadow-sunset shrink-0 mt-0.5">
              <Scale className="w-5 h-5 text-white" />
            </span>
            <div>
              <h1 className="text-xl font-bold text-ink">Decision Center</h1>
              <p className="text-sm text-ink-muted mt-0.5 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-teal-500" /> Sage triages every decision so you only read what needs you.
              </p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={load} aria-label="Refresh decisions">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>

        {/* Tabs */}
        <div className="inline-flex rounded-xl bg-surface-2 p-1 mb-6">
          {([['pending', 'Needs decision'], ['decided', `Decided${decided?.count ? ` (${decided.count})` : ''}`]] as const).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                tab === key ? 'bg-surface text-ink shadow-card' : 'text-ink-muted hover:text-ink'}`}>
              {label}
            </button>
          ))}
        </div>

        {/* Undo bar — the last dismissal stays reversible until the next reload */}
        {undoable && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl bg-surface border border-line shadow-card px-4 py-2.5">
            <p className="text-sm text-ink-soft min-w-0 truncate">
              Dismissed <span className="font-medium text-ink">“{undoable.problem}”</span> — Sage will flag it again only if it recurs.
            </p>
            <Button variant="ghost" size="sm" onClick={undoDismiss} disabled={busy === undoable.id}>
              Undo
            </Button>
          </div>
        )}

        {loading ? (
          <div className="space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
        ) : error ? (
          <ErrorState title="Couldn't load your decisions" description={error} onRetry={load} />
        ) : tab === 'pending' ? (
          !triage || triage.total === 0 ? (
            <InboxZero firstName={firstName} />
          ) : (
            <Stagger className="space-y-8">
              {/* ── The triage summary: the 80% cut, made visible ── */}
              <RevealItem>
                <TriageBanner t={triage} />
              </RevealItem>

              {/* ── Decide now: your 3 calls ── */}
              <RevealItem>
                <SectionLabel icon={<Scale className="w-3.5 h-3.5" />}>
                  Decide now — your {exec.length === 1 ? 'call' : `${exec.length} calls`}
                </SectionLabel>
                <div className="space-y-4">
                  {exec.map((d) => <PendingCard key={d.id ?? d.problem} {...cardProps(d)} />)}
                </div>
                {triage.executive.more.count > 0 && (
                  <MoreStrategic more={triage.executive.more} cardProps={cardProps} />
                )}
              </RevealItem>

              {/* ── Sage routed the rest ── */}
              {triage.lanes.length > 0 && (
                <RevealItem>
                  <SectionLabel icon={<Sparkles className="w-3.5 h-3.5" />}>
                    Sage routed the other {triage.routed_count}
                  </SectionLabel>
                  <div className="space-y-3">
                    {triage.lanes.map((lane) => <LaneRow key={lane.key} lane={lane} cardProps={cardProps} />)}
                  </div>
                </RevealItem>
              )}
            </Stagger>
          )
        ) : (
          (decided?.decisions.length ?? 0) === 0 ? (
            <div className="rounded-2xl bg-surface border border-line p-8 text-center">
              <Timer className="w-8 h-8 text-ink-muted mx-auto mb-2" />
              <p className="text-sm font-medium text-ink">No decisions recorded yet</p>
              <p className="text-sm text-ink-muted mt-1">Approve a recommendation and Sage will measure whether it worked.</p>
            </div>
          ) : (
            <Stagger className="space-y-4">
              {decided!.decisions.map((d) => <RevealItem key={d.id}><DecidedCard d={d} /></RevealItem>)}
            </Stagger>
          )
        )}

        <p className="text-xs text-ink-muted text-center pt-8">
          Sage routes by scope and impact — chain-wide calls to you, store performance to regional managers, replenishment to stores, and repeatable low-risk actions to its own automation. Every figure is derived; nothing is estimated without showing its basis.
        </p>
      </div>
    </main>
  );
}

/* ── The triage funnel: 55 → 3 for you + routed ── */
function TriageBanner({ t }: { t: Triage }) {
  const execN = t.executive.decisions.length;
  return (
    <div className="rounded-2xl hero-mesh relative overflow-hidden p-5 md:p-6 shadow-elevated">
      <div className="pointer-events-none absolute -top-10 -right-8 w-40 h-40 rounded-full bg-white/10 blur-2xl" />
      <div className="relative z-10">
        <p className="text-sm" style={{ color: 'rgba(255,255,255,0.8)', WebkitTextFillColor: 'rgba(255,255,255,0.8)' }}>
          <Sparkles className="w-4 h-4 inline -mt-0.5 me-1" />
          Sage read {t.total} open decision{t.total === 1 ? '' : 's'} this morning.
        </p>
        <div className="mt-3 flex items-end flex-wrap gap-x-8 gap-y-3">
          <div>
            <p className="text-4xl font-bold leading-none" style={{ color: '#fff', WebkitTextFillColor: '#fff' }}>{execN}</p>
            <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.75)', WebkitTextFillColor: 'rgba(255,255,255,0.75)' }}>need your decision</p>
          </div>
          <div className="h-9 w-px bg-white/20" />
          <div>
            <p className="text-2xl font-semibold leading-none" style={{ color: 'rgba(255,255,255,0.92)', WebkitTextFillColor: 'rgba(255,255,255,0.92)' }}>{t.routed_count}</p>
            <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.75)', WebkitTextFillColor: 'rgba(255,255,255,0.75)' }}>routed for you</p>
          </div>
          {t.at_stake_aed_per_week > 0 && (
            <div className="ms-auto text-end">
              <p className="text-lg font-semibold tabular-nums leading-none" style={{ color: '#fff', WebkitTextFillColor: '#fff' }}>{AED(t.at_stake_aed_per_week)}</p>
              <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.75)', WebkitTextFillColor: 'rgba(255,255,255,0.75)' }}>/week at stake</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Delegation lane: collapsed summary + why + expand ── */
function LaneRow({ lane, cardProps }: { lane: Lane; cardProps: (d: Decision) => PendingCardProps }) {
  const [open, setOpen] = useState(false);
  const Icon = LANE_ICON[lane.key];
  const tint = lane.automate ? 'bg-violet-50 ring-violet-200 text-violet-700' : 'bg-teal-50 ring-teal-100 text-teal-700';
  return (
    <div className="rounded-2xl bg-surface border border-line overflow-hidden">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 p-4 text-start hover:bg-surface-2 transition-colors">
        <span className={`flex items-center justify-center w-10 h-10 rounded-xl ring-1 shrink-0 ${tint}`}>
          <Icon className="w-5 h-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-semibold text-ink">{lane.label}</p>
            <span className="text-xs font-medium text-ink-muted bg-surface-2 rounded-full px-2 py-0.5">
              {lane.count} decision{lane.count === 1 ? '' : 's'}
            </span>
            {lane.aed > 0 && <span className="text-xs font-semibold text-ink tabular-nums">{AED(lane.aed)}/wk</span>}
            {lane.automate && <span className="text-[11px] font-medium text-violet-700 bg-violet-100 rounded-full px-2 py-0.5">automatable</span>}
          </div>
          <p className="text-xs text-ink-muted mt-0.5 line-clamp-1">{lane.reason}</p>
          {lane.groups && lane.groups.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {lane.groups.map((g) => (
                <span key={g.name} className="text-[11px] text-ink-soft bg-surface-2 rounded-md px-1.5 py-0.5">
                  {g.name} <span className="font-semibold">{g.count}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <ChevronDown className={`w-4 h-4 text-ink-muted shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-line p-4 bg-surface-2/40 space-y-4">
          <p className="text-xs text-ink-muted">{lane.reason}</p>
          {lane.automate && (
            <div className="flex items-center justify-between gap-3 rounded-xl bg-violet-50 ring-1 ring-violet-200 p-3">
              <p className="text-xs text-violet-800">
                Today Sage <strong>drafts</strong> these for one-click approval. Turn on automation and it places them itself, within your limits.
              </p>
              <Link href="/action-drafts"><Button size="sm" variant="secondary">See drafts</Button></Link>
            </div>
          )}
          {lane.groups ? (
            lane.groups.map((g) => (
              <div key={g.name}>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted mb-2">
                  {g.name} · {g.count} · {AED(g.aed)}/wk
                </p>
                <div className="space-y-3">
                  {g.decisions.map((d) => <PendingCard key={d.id ?? d.problem} {...cardProps(d)} compact />)}
                </div>
              </div>
            ))
          ) : (
            <div className="space-y-3">
              {lane.decisions.map((d) => <PendingCard key={d.id ?? d.problem} {...cardProps(d)} compact />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MoreStrategic({ more, cardProps }: { more: { count: number; aed: number; decisions: Decision[] }; cardProps: (d: Decision) => PendingCardProps }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 rounded-xl bg-surface border border-line px-4 py-2.5 text-start hover:bg-surface-2 transition-colors">
        <ChevronDown className={`w-4 h-4 text-ink-muted transition-transform ${open ? 'rotate-180' : ''}`} />
        <span className="text-sm text-ink-soft">
          <span className="font-semibold text-ink">{more.count} more chain-wide issue{more.count === 1 ? '' : 's'}</span> to review when you can
        </span>
        {more.aed > 0 && <span className="ms-auto text-xs font-semibold text-ink tabular-nums">{AED(more.aed)}/wk</span>}
      </button>
      {open && (
        <div className="mt-3 space-y-4">
          {more.decisions.map((d) => <PendingCard key={d.id ?? d.problem} {...cardProps(d)} />)}
        </div>
      )}
    </div>
  );
}

function SectionLabel({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted mb-3">
      {icon}{children}
    </p>
  );
}

function ImpactBlock({ impact, compact }: { impact: Impact; compact?: boolean }) {
  const big = compact ? 'text-xl' : 'text-2xl';
  return (
    <div className="text-end shrink-0" title={impact.basis}>
      {impact.aed != null ? (
        <>
          <p className={`${big} font-bold text-ink tabular-nums leading-none`}>{AED(impact.aed)}</p>
          <p className="text-[11px] text-ink-muted mt-1">per {impact.per} at stake</p>
        </>
      ) : impact.units != null ? (
        <>
          <p className={`${big} font-bold text-ink tabular-nums leading-none`}>≈{impact.units.toLocaleString()}</p>
          <p className="text-[11px] text-ink-muted mt-1">units per {impact.per}</p>
        </>
      ) : (
        <>
          <p className={`${big} font-bold text-ink-muted leading-none`}>—</p>
          <p className="text-[11px] text-ink-muted mt-1">no derivable figure</p>
        </>
      )}
    </div>
  );
}

function CardShell({ d, compact, children }: { d: Decision; compact?: boolean; children: React.ReactNode }) {
  return (
    <div className={`rounded-2xl bg-surface border border-line shadow-card ${compact ? 'p-4' : 'p-5'}`} style={sevBar(d.severity)}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[11px] font-bold uppercase tracking-wide ${SEV_TEXT[d.severity] ?? 'text-teal-600'}`}>{d.severity}</span>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${CONF_PILL[d.confidence.level]}`}>
              {d.confidence.level} confidence
            </span>
            {d.entity_name && <span className="text-xs text-ink-muted">· {d.entity_name}</span>}
          </div>
          <h3 className={`mt-1.5 font-semibold text-ink leading-snug ${compact ? 'text-[15px]' : 'text-[17px]'}`}>{d.problem}</h3>
          <p className="mt-1 text-sm text-ink-soft leading-relaxed">{d.detail}</p>
        </div>
        <ImpactBlock impact={d.impact} compact={compact} />
      </div>

      {d.routing_reason && (
        <p className="mt-2.5 text-xs text-ink-muted flex items-start gap-1.5">
          <ArrowRight className="w-3 h-3 mt-0.5 shrink-0 text-teal-500" />{d.routing_reason}
        </p>
      )}

      {d.evidence.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {d.evidence.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2 py-1 text-xs text-ink-soft">
              <span className="text-ink-muted">{f.label}</span>
              <span className="font-semibold text-ink tabular-nums">{f.value}</span>
            </span>
          ))}
        </div>
      )}

      <div className="mt-3.5 rounded-xl bg-teal-50/70 ring-1 ring-teal-100 p-3.5">
        <p className="text-sm text-teal-900">
          <Sparkles className="w-3.5 h-3.5 inline -mt-0.5 me-1 text-teal-600" />
          <span className="font-semibold">Sage recommends:</span> {d.recommended_action}
        </p>
        <p className="mt-1.5 text-[13px] text-teal-800/90">
          <span className="font-medium">Expected outcome:</span> {d.expected_outcome}
        </p>
      </div>

      <details className="mt-2.5 group">
        <summary className="flex items-center gap-1 text-xs text-ink-muted cursor-pointer select-none hover:text-ink w-fit">
          <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" />
          Why this confidence &amp; impact
        </summary>
        <div className="mt-2 ps-4 space-y-1">
          {d.confidence.factors.map((f, i) => (
            <p key={i} className="text-xs text-ink-soft flex items-start gap-1.5">
              <CheckCircle2 className="w-3 h-3 text-teal-500 mt-0.5 shrink-0" />{f}
            </p>
          ))}
          <p className="text-xs text-ink-muted">Impact basis: {d.impact.basis}.</p>
        </div>
      </details>

      {children}
    </div>
  );
}

interface PendingCardProps {
  d: Decision; busy: boolean; compact?: boolean;
  onApprove: () => void; onDismiss: () => void; onDraft: () => void;
}
function PendingCard({ d, busy, compact, onApprove, onDismiss, onDraft }: PendingCardProps) {
  return (
    <CardShell d={d} compact={compact}>
      <div className="mt-4 flex items-center gap-2 flex-wrap">
        {d.kind === 'finding' ? (
          <>
            <Button size="sm" onClick={onApprove} disabled={busy}>
              <ThumbsUp className="w-3.5 h-3.5 me-1.5" /> Approve
            </Button>
            <Button size="sm" variant="secondary" onClick={onDraft} disabled={busy}>
              <Wand2 className="w-3.5 h-3.5 me-1.5" /> Draft the action
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismiss} disabled={busy}>
              <X className="w-3.5 h-3.5 me-1.5" /> Dismiss
            </Button>
          </>
        ) : (
          <Link href={d.href}>
            <Button size="sm">Review &amp; approve order <ArrowRight className="w-3.5 h-3.5 ms-1.5" /></Button>
          </Link>
        )}
      </div>
    </CardShell>
  );
}

function DecidedCard({ d }: { d: Decision }) {
  const o = d.decision;
  const badge = OUTCOME_BADGE[o?.outcome_status ?? 'pending'];
  return (
    <CardShell d={d}>
      <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
        <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${badge.cls}`}>
          {badge.text}
          {o?.outcome_status === 'improved' && o.metric_before != null && (
            <span className="ms-1 tabular-nums">({(o.metric_before * 100).toFixed(1)}% → recovered)</span>
          )}
        </span>
        {o?.accepted_at && (
          <span className="text-[11px] text-ink-muted">
            Approved {o.accepted_by ? `by ${o.accepted_by} ` : ''}on {String(o.accepted_at).slice(0, 10)}
          </span>
        )}
      </div>
    </CardShell>
  );
}

function InboxZero({ firstName }: { firstName: string }) {
  return (
    <div className="rounded-2xl bg-surface border border-line p-10 text-center">
      <span className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-teal-50 ring-1 ring-teal-100 mb-3">
        <Inbox className="w-6 h-6 text-teal-600" />
      </span>
      <h3 className="text-lg font-semibold text-ink">
        Inbox zero{firstName ? `, ${firstName.charAt(0).toUpperCase()}${firstName.slice(1)}` : ''}.
      </h3>
      <p className="text-sm text-ink-muted mt-1 max-w-sm mx-auto">
        Sage watches your stores continuously and will queue the next decision — with its AED impact, evidence, and the right owner — the moment something needs attention.
      </p>
    </div>
  );
}
