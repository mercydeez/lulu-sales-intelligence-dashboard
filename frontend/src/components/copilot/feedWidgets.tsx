'use client';

/**
 * Sage Copilot feed widgets (Phase 2b) — the proactive layer's presentational
 * surface. Each widget reads ONE shared fetch of `/api/ai/copilot/feed`
 * (useCopilotFeed dedupes; see that file) and follows the `/today` zone
 * conventions: honest empty states, recoverable per-zone errors, VOLUME in
 * units / VALUE in AED, never mixed.
 *
 * Status colors carry state WITH a text label and icon — never color alone.
 */
import Link from 'next/link';
import {
  HeartPulse, ShieldAlert, TrendingUp, Lightbulb, ArrowRight, RefreshCw,
  AlertTriangle, Inbox, CheckCircle2,
} from 'lucide-react';
import { Button, SkeletonCard } from '@/components/ui';
import { registerWidgets, type WidgetProps } from '@/components/copilot/registry';
import { useCopilotFeed, type BusinessHealth, type FeedAction, type FeedOpportunity, type FeedRisk } from '@/components/copilot/useCopilotFeed';

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

const SEV_HEX: Record<string, string> = {
  critical: '#f43f5e', high: '#f97316', medium: '#f59e0b', low: 'var(--brand)',
};

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted mb-3">{children}</p>;
}

/* Honest, recoverable failure for a single zone (mirrors /today's ZoneError). */
function FeedError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <div className="rounded-2xl bg-surface border border-line shadow-card p-5 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-amber-50 ring-1 ring-amber-100 shrink-0">
          <AlertTriangle className="w-5 h-5 text-amber-600" />
        </span>
        <div>
          <p className="text-sm font-semibold text-ink">{label}</p>
          <p className="text-xs text-ink-muted mt-0.5">A quick retry usually clears it.</p>
        </div>
      </div>
      <Button size="sm" variant="secondary" onClick={onRetry}>
        <RefreshCw className="w-4 h-4 me-1.5" /> Retry
      </Button>
    </div>
  );
}

function EmptyCard({ message }: { message: string }) {
  return (
    <div className="rounded-2xl bg-surface border border-line p-6 text-center">
      <Inbox className="w-6 h-6 text-teal-600 mx-auto mb-2" />
      <p className="text-sm font-medium text-ink">{message}</p>
    </div>
  );
}

/* ── Business health — a status meter, labeled (state is never color-alone) ── */

const HEALTH_META: Record<BusinessHealth['overall'], { label: string; bar: string; chip: string }> = {
  strong:    { label: 'Strong',          bar: 'bg-emerald-500', chip: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  steady:    { label: 'Steady',          bar: 'bg-teal-500',    chip: 'bg-teal-50 text-teal-700 ring-teal-200' },
  attention: { label: 'Needs attention', bar: 'bg-amber-500',   chip: 'bg-amber-50 text-amber-700 ring-amber-200' },
  critical:  { label: 'Critical',        bar: 'bg-rose-500',    chip: 'bg-rose-50 text-rose-700 ring-rose-200' },
};

export function BusinessHealthWidget({ spec }: WidgetProps) {
  const { feed, status, refresh } = useCopilotFeed();
  const title = String(spec.props?.title ?? 'Business health');
  if (status === 'loading') return <section><SectionTitle>{title}</SectionTitle><SkeletonCard /></section>;
  if (status === 'error' || !feed) {
    return <section><SectionTitle>{title}</SectionTitle><FeedError label="Couldn't read your business health" onRetry={refresh} /></section>;
  }
  const h = feed.business_health;
  const meta = HEALTH_META[h.overall] ?? HEALTH_META.steady;
  const pct = Math.round(h.score * 100);
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      <div className="rounded-2xl bg-surface border border-line shadow-card p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-teal-50 ring-1 ring-teal-100 shrink-0">
              <HeartPulse className="w-5 h-5 text-teal-600" />
            </span>
            <span className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold ring-1 ${meta.chip}`}>
              {meta.label}
            </span>
          </div>
          <p className="text-lg font-bold text-ink tabular-nums leading-none">
            {pct}<span className="text-xs font-medium text-ink-muted">/100</span>
          </p>
        </div>
        {/* Thin meter, rounded data-end; the label above carries the state. */}
        <div className="mt-4 h-2 rounded-full bg-surface-2 overflow-hidden" role="meter"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={`Business health: ${meta.label}, ${pct} of 100`}>
          <div className={`h-full rounded-full ${meta.bar}`} style={{ width: `${pct}%` }} />
        </div>
        <ul className="mt-4 space-y-1.5">
          {h.factors.map((f, i) => (
            <li key={i} className="text-sm text-ink-muted flex items-start gap-2">
              <span className="mt-[7px] w-1 h-1 rounded-full bg-ink-muted shrink-0" aria-hidden />
              {f}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ── Risks — decision-shaped cards (severity striped, deep-linked) ── */

export function RisksWidget({ spec }: WidgetProps) {
  const { feed, status, refresh } = useCopilotFeed();
  const title = String(spec.props?.title ?? 'Risks Sage is watching');
  if (status === 'loading') return <section><SectionTitle>{title}</SectionTitle><SkeletonCard /></section>;
  if (status === 'error' || !feed) {
    return <section><SectionTitle>{title}</SectionTitle><FeedError label="Couldn't load your risks" onRetry={refresh} /></section>;
  }
  const risks = feed.risks;
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      {risks.length === 0 ? (
        <div className="rounded-2xl bg-surface border border-line p-6 text-center">
          <CheckCircle2 className="w-6 h-6 text-emerald-600 mx-auto mb-2" />
          <p className="text-sm font-medium text-ink">No critical risks open beyond your decisions above.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {risks.map((r: FeedRisk, i) => (
            <Link key={r.id ?? i} href={r.href || '/decisions'}
              className="block rounded-2xl bg-surface border border-line shadow-card p-4 hover:bg-surface-2 transition-colors"
              style={{ borderInlineStartWidth: '3px', borderInlineStartColor: SEV_HEX[r.severity] ?? SEV_HEX.low }}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[15px] font-semibold text-ink leading-snug flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4 text-ink-muted shrink-0" aria-hidden />
                    {r.problem}
                  </p>
                  {r.recommended_action && <p className="text-sm text-teal-700 mt-1">→ {r.recommended_action}</p>}
                </div>
                <div className="text-end shrink-0">
                  <p className="text-lg font-bold text-ink tabular-nums leading-none">
                    {r.impact.aed != null ? AED(r.impact.aed) : r.impact.units != null ? `≈${r.impact.units.toLocaleString()}` : '—'}
                  </p>
                  <p className="text-[11px] text-ink-muted mt-1">
                    {r.impact.aed != null ? `per ${r.impact.per}` : r.impact.units != null ? `units / ${r.impact.per}` : ''}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── Opportunities — grounded positives, measured vs estimated made visible ── */

function ConfidencePill({ confidence }: { confidence: number | null }) {
  if (confidence == null) return null;
  // Mirrors the backend's documented split: 0.85 measured fact / 0.55 estimate.
  const measured = confidence >= 0.75;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${
      measured ? 'bg-teal-50 text-teal-700 ring-teal-200' : 'bg-surface-2 text-ink-muted ring-line'}`}>
      {measured ? 'Measured' : 'Estimate'} · {Math.round(confidence * 100)}%
    </span>
  );
}

export function OpportunitiesWidget({ spec }: WidgetProps) {
  const { feed, status, refresh } = useCopilotFeed();
  const title = String(spec.props?.title ?? 'Growth openings');
  if (status === 'loading') return <section><SectionTitle>{title}</SectionTitle><SkeletonCard /></section>;
  if (status === 'error' || !feed) {
    return <section><SectionTitle>{title}</SectionTitle><FeedError label="Couldn't load your opportunities" onRetry={refresh} /></section>;
  }
  const opportunities = feed.opportunities;
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      {opportunities.length === 0 ? (
        <EmptyCard message="No grounded growth openings right now — Sage only lists what the data supports." />
      ) : (
        <div className="space-y-3">
          {opportunities.map((o: FeedOpportunity, i) => (
            <Link key={i} href={o.deep_link || '/value'}
              className="group block rounded-2xl bg-surface border border-line shadow-card p-4 hover:bg-surface-2 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[15px] font-semibold text-ink leading-snug flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-emerald-600 shrink-0" aria-hidden />
                    {o.title}
                  </p>
                  <p className="text-sm text-ink-muted mt-1">{o.reason}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <ConfidencePill confidence={o.confidence} />
                    {o.evidence.map((e, j) => (
                      <span key={j} className="text-[11px] text-ink-muted">
                        {e.label}: <span className="font-medium text-ink">{e.value}</span>
                      </span>
                    ))}
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-ink-muted group-hover:text-teal-600 transition-colors shrink-0 mt-1" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── Recommendations — reshaped decisions with priority + evidence ── */

const PRIORITY_CHIP: Record<FeedAction['priority'], string> = {
  urgent: 'bg-rose-50 text-rose-700 ring-rose-200',
  high: 'bg-orange-50 text-orange-700 ring-orange-200',
  normal: 'bg-teal-50 text-teal-700 ring-teal-200',
  low: 'bg-surface-2 text-ink-muted ring-line',
};

export function RecommendationsWidget({ spec }: WidgetProps) {
  const { feed, status, refresh } = useCopilotFeed();
  const title = String(spec.props?.title ?? 'Sage recommends');
  if (status === 'loading') return <section><SectionTitle>{title}</SectionTitle><SkeletonCard /></section>;
  if (status === 'error' || !feed) {
    return <section><SectionTitle>{title}</SectionTitle><FeedError label="Couldn't load Sage's recommendations" onRetry={refresh} /></section>;
  }
  const actions = feed.recommended_actions;
  return (
    <section>
      <SectionTitle>{title}</SectionTitle>
      {actions.length === 0 ? (
        <EmptyCard message="Nothing to recommend right now — that's an honest all-clear." />
      ) : (
        <div className="space-y-3">
          {actions.map((a: FeedAction, i) => (
            <Link key={i} href={a.deep_link || '/decisions'}
              className="group block rounded-2xl bg-surface border border-line shadow-card p-4 hover:bg-surface-2 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[15px] font-semibold text-ink leading-snug flex items-center gap-2">
                    <Lightbulb className="w-4 h-4 text-ink-muted shrink-0" aria-hidden />
                    {a.title}
                  </p>
                  <p className="text-sm text-ink-muted mt-1">{a.reason}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 capitalize ${
                      PRIORITY_CHIP[a.priority] ?? PRIORITY_CHIP.normal}`}>
                      {a.priority}
                    </span>
                    {a.evidence.slice(0, 3).map((e, j) => (
                      <span key={j} className="text-[11px] text-ink-muted">
                        {e.label}: <span className="font-medium text-ink">{e.value}</span>
                      </span>
                    ))}
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-ink-muted group-hover:text-teal-600 transition-colors shrink-0 mt-1" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

/* Register into the open registry at module load (same trick as /today's own
   registerWidgets). `growth` is the doc's §3.2 alias for `opportunities`. */
registerWidgets({
  business_health: BusinessHealthWidget,
  risks: RisksWidget,
  opportunities: OpportunitiesWidget,
  growth: OpportunitiesWidget,
  recommendations: RecommendationsWidget,
});
