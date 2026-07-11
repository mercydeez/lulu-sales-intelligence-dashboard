'use client';

/**
 * "Today" — the role-configured homepage (Role Experience Engine, Wave 1).
 * This page has NO role-specific code: it renders the zone list from the
 * caller's /api/experience config. Zones answer the blueprint's five questions
 * (what matters / do first / approve / AI can do / cost of ignoring) and fetch
 * ONLY existing endpoints. A new role's homepage = a new config, not a new page.
 */
import { useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import Link from 'next/link';
import { useExperience, KpiDescriptor } from '@/contexts/ExperienceContext';
import { Button, ErrorState, SkeletonCard } from '@/components/ui';
import { apiGet } from '@/lib/apiClient';
import { useBriefing } from '@/lib/queries/briefing';
import { useDecisionTriage, type TriageDecision } from '@/lib/queries/decisions';
import { useInventorySummary } from '@/lib/queries/inventory';
import { useApprovalInbox } from '@/lib/queries/procurement';
import { registerWidgets, resolveWidget, type WidgetProps } from '@/components/copilot/registry';
// Side-effect import: the Copilot feed widgets (business_health, risks,
// opportunities/growth, recommendations) register before zones resolve.
import '@/components/copilot/feedWidgets';
import {
  Sparkles, ArrowRight, RefreshCw, Inbox, PackageX, TrendingUp, TrendingDown, Minus, AlertTriangle,
} from 'lucide-react';

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

const white = (o = 1): React.CSSProperties =>
  ({ color: `rgba(255,255,255,${o})`, WebkitTextFillColor: `rgba(255,255,255,${o})` });

export default function TodayPage() {
  const { config, loading } = useExperience();
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <main className="min-h-screen px-4 md:px-8 py-6 md:py-10">
      <div className="max-w-3xl mx-auto">
        {loading ? (
          <div className="space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
        ) : !config ? (
          <ErrorState title="Couldn't load your workspace" description="Your role experience is unavailable."
            onRetry={() => setReloadKey((k) => k + 1)} />
        ) : (
          <div key={reloadKey} className="space-y-6">
            {/* v2 homepage envelope with a v1 fallback, resolved against the open
                widget registry. Unknown types (widgets a build doesn't ship yet)
                degrade silently. Each zone reveals INDEPENDENTLY (its own on-mount
                animation) rather than through a parent stagger — the zones now
                re-render as their query hooks resolve, which would interrupt a
                parent-propagated stagger and leave later zones stuck hidden. */}
            {(config.homepage?.zones ?? config.zones).map((zone, i) => {
              const Zone = resolveWidget(zone.type);
              if (!Zone) return null;
              return (
                <div key={`${zone.type}-${i}`}>
                  <Zone config={config} spec={zone} />
                </div>
              );
            })}
            <div className="flex items-center justify-between pt-2">
              <p className="text-xs text-ink-muted flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-teal-500" />
                {config.persona.name} · {config.persona.title} — configured for your role
              </p>
              <Button variant="ghost" size="sm" onClick={() => setReloadKey((k) => k + 1)} aria-label="Refresh">
                <RefreshCw className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

// Homepage widgets share the registry's prop contract (config + zone spec).
type ZoneProps = WidgetProps;

type ZoneStatus = 'loading' | 'ok' | 'error';

/* Honest, recoverable failure for a single zone — never a silent skeleton and
   never a false "all clear" when the fetch actually failed. */
function ZoneError({ label, onRetry }: { label: string; onRetry: () => void }) {
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

/* ── Q1: What matters to me now? — the persona verdict ── */
function VerdictZone({ config }: ZoneProps) {
  const { data: b, isLoading, isError, refetch } = useBriefing();
  const status: ZoneStatus = isLoading ? 'loading' : isError ? 'error' : 'ok';
  const p = config.persona;
  const headline =
    status === 'ok' && b ? b.headline.summary
      : status === 'error' ? "I couldn't read your stores just now."
        : 'Reading your data…';
  return (
    <section className="hero-mesh relative overflow-hidden rounded-3xl p-6 md:p-8 shadow-elevated">
      <div className="relative z-10">
        <div className="flex items-center gap-2.5">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-white/15 ring-1 ring-white/25">
            <Sparkles className="w-4 h-4 text-white" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold" style={white()}>{p.name}</p>
            <p className="text-[11px]" style={white(0.7)}>{p.title}</p>
          </div>
        </div>
        <p className="mt-5 text-sm" style={white(0.75)}>{b?.greeting ?? 'Good day'} — {p.greeting}</p>
        <h1 className="mt-1 text-xl md:text-2xl font-semibold leading-snug max-w-[46ch]" style={white()}>
          {headline}
        </h1>
        {status === 'ok' && b?.tldr && <p className="mt-2 text-sm italic" style={white(0.75)}>{b.tldr}</p>}
        {status === 'error' && (
          <button onClick={() => refetch()}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-white/15 ring-1 ring-white/25 px-3 py-1.5 text-xs font-medium text-white hover:bg-white/25 transition">
            <RefreshCw className="w-3.5 h-3.5" /> Try again
          </button>
        )}
      </div>
    </section>
  );
}

/* ── Q-KPIs: the role's numbers, from descriptors ── */
type SourceData = Record<string, Record<string, unknown> | null>;

function formatKpi(v: unknown, format: KpiDescriptor['format']): { text: string; icon?: React.ReactNode } {
  if (v == null) return { text: '—' };
  if (format === 'aed') return { text: AED(Number(v)) };
  if (format === 'units') return { text: `${Number(v).toLocaleString()} units` };
  if (format === 'trend') {
    const s = String(v);
    const Icon = s === 'up' ? TrendingUp : s === 'down' ? TrendingDown : Minus;
    const cls = s === 'up' ? 'text-emerald-600' : s === 'down' ? 'text-rose-600' : 'text-ink-muted';
    return { text: s, icon: <Icon className={`w-4 h-4 ${cls}`} /> };
  }
  return { text: Number(v).toLocaleString() };
}

const SOURCE_ENDPOINTS: Record<KpiDescriptor['source'], string> = {
  kpis: '/api/kpis',
  decisions: '/api/decisions/summary',
  inventory: '/api/inventory/summary',
};

function KpiZone({ config }: ZoneProps) {
  const sources = Array.from(new Set(config.kpis.map((k) => k.source)));
  // One deduped query per distinct KPI source; useQueries handles the dynamic set.
  const results = useQueries({
    queries: sources.map((src) => ({
      queryKey: ['today', 'kpi-source', src] as const,
      queryFn: () => apiGet<Record<string, unknown>>(SOURCE_ENDPOINTS[src]),
      staleTime: 30000,
    })),
  });
  const data: SourceData = {};
  sources.forEach((src, i) => { data[src] = results[i].data ?? null; });

  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {config.kpis.map((kpi) => {
        const src = data[kpi.source];
        const { text, icon } = formatKpi(src ? src[kpi.field] : undefined, kpi.format);
        return (
          <div key={kpi.key} className="rounded-2xl bg-surface border border-line shadow-card p-3.5">
            <p className="text-[11px] uppercase tracking-widest text-ink-muted">{kpi.label}</p>
            <p className="mt-1 text-lg font-bold text-ink tabular-nums flex items-center gap-1.5">
              {icon}{text}
            </p>
          </div>
        );
      })}
    </section>
  );
}

/* ── Q2+Q3: decide first — top of the role-scoped triage ── */
const SEV_HEX: Record<string, string> = {
  critical: '#f43f5e', high: '#f97316', medium: '#f59e0b', low: 'var(--brand)',
};

function DecisionsZone({ spec }: ZoneProps) {
  const limit = Number(spec.props?.limit ?? 3);
  const title = String(spec.props?.title ?? 'Decide now');
  const { data: t, isLoading, isError, refetch } = useDecisionTriage();
  const status: ZoneStatus = isLoading ? 'loading' : isError ? 'error' : 'ok';
  const decisions: TriageDecision[] = t?.executive.decisions.slice(0, limit) ?? [];

  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted mb-3">{title}</p>
      {status === 'loading' ? (
        <SkeletonCard />
      ) : status === 'error' ? (
        <ZoneError label="Couldn't load your decisions" onRetry={() => refetch()} />
      ) : decisions.length === 0 ? (
        <div className="rounded-2xl bg-surface border border-line p-6 text-center">
          <Inbox className="w-6 h-6 text-teal-600 mx-auto mb-2" />
          <p className="text-sm font-medium text-ink">Nothing needs a decision right now.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {decisions.map((d, i) => (
            /* Link straight to where the item is acted on (a reorder → its exact
               PO with the item highlighted), so the item is never lost. */
            <Link key={d.id ?? i} href={d.href || '/decisions'}
              className="block rounded-2xl bg-surface border border-line shadow-card p-4 hover:bg-surface-2 transition-colors"
              style={{ borderInlineStartWidth: '3px', borderInlineStartColor: SEV_HEX[d.severity] ?? SEV_HEX.low }}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-[15px] font-semibold text-ink leading-snug">{d.problem}</p>
                  <p className="text-sm text-teal-700 mt-1">→ {d.recommended_action}</p>
                </div>
                <div className="text-end shrink-0">
                  <p className="text-lg font-bold text-ink tabular-nums leading-none">
                    {d.impact.aed != null ? AED(d.impact.aed) : d.impact.units != null ? `≈${d.impact.units.toLocaleString()}` : '—'}
                  </p>
                  <p className="text-[11px] text-ink-muted mt-1">
                    {d.impact.aed != null ? `per ${d.impact.per}` : d.impact.units != null ? `units / ${d.impact.per}` : ''}
                  </p>
                </div>
              </div>
            </Link>
          ))}
          <Link href="/decisions" className="inline-flex items-center gap-1 text-sm font-medium text-teal-600 hover:text-teal-700">
            All decisions <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}
    </section>
  );
}

/* ── Q3 (regional): PO approvals waiting ── */
function ApprovalsZone(_: ZoneProps) {
  const { data, isError, refetch } = useApprovalInbox();
  const count = data ? data.count : null;
  if (isError) return <ZoneError label="Couldn't check approvals" onRetry={() => refetch()} />;
  return (
    <section className="rounded-2xl bg-surface border border-line shadow-card p-5 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-teal-50 ring-1 ring-teal-100 shrink-0">
          <Inbox className="w-5 h-5 text-teal-600" />
        </span>
        <div>
          <p className="text-sm font-semibold text-ink">
            {count == null ? 'Checking approvals…'
              : count === 0 ? 'No purchase orders waiting on you'
              : `${count} purchase order${count === 1 ? '' : 's'} await your approval`}
          </p>
          <p className="text-xs text-ink-muted mt-0.5">Sage drafted each one with its evidence attached.</p>
        </div>
      </div>
      <Link href="/approvals"><Button size="sm" variant={count ? 'primary' : 'secondary'}>Review</Button></Link>
    </section>
  );
}

/* ── Q5 (store): stockouts right now ── */
function StockZone(_: ZoneProps) {
  const { data: summary, isError, refetch } = useInventorySummary();
  if (isError) return <ZoneError label="Couldn't check your shelves" onRetry={() => refetch()} />;
  const out = summary?.out_of_stock_count ?? 0;
  const low = summary?.low_stock_count;
  return (
    <section className={`rounded-2xl border shadow-card p-5 flex items-center justify-between gap-4 ${
      out > 0 ? 'bg-rose-50/50 border-rose-100' : 'bg-surface border-line'}`}>
      <div className="flex items-center gap-3 min-w-0">
        <span className={`flex items-center justify-center w-10 h-10 rounded-xl ring-1 shrink-0 ${
          out > 0 ? 'bg-rose-100 ring-rose-200' : 'bg-teal-50 ring-teal-100'}`}>
          <PackageX className={`w-5 h-5 ${out > 0 ? 'text-rose-600' : 'text-teal-600'}`} />
        </span>
        <div>
          <p className="text-sm font-semibold text-ink">
            {summary == null ? 'Checking your shelves…'
              : out === 0 && low ? `Nothing out of stock now — but ${low} item${low === 1 ? '' : 's'} running low`
              : out === 0 ? 'Nothing out of stock, nothing running low — you’re covered'
              : `${out} item${out === 1 ? '' : 's'} out of stock right now`}
          </p>
          <p className="text-xs text-ink-muted mt-0.5">
            {out === 0 && low ? 'These are the items your decisions above suggest reordering — act before they run out.'
              : 'Every stockout hour is lost revenue.'}
          </p>
        </div>
      </div>
      <Link href="/inventory"><Button size="sm" variant={out > 0 ? 'primary' : 'secondary'}>Open stock</Button></Link>
    </section>
  );
}

/* ── Q4: What can Sage do for me? — the role's configured one-tap actions ──
   Pure config: renders `config.quick_actions` (no new endpoint). Nothing
   configured → renders nothing (graceful). */
function QuickActionsWidget({ config, spec }: ZoneProps) {
  const actions = config.quick_actions ?? [];
  if (actions.length === 0) return null;
  const title = String(spec.props?.title ?? 'What Sage can do for you');
  return (
    <section>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted mb-3">{title}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {actions.map((a) => (
          <Link key={a.key} href={a.href}
            className="group flex items-center justify-between gap-3 rounded-2xl bg-surface border border-line shadow-card p-4 hover:bg-surface-2 transition-colors">
            <span className="flex items-center gap-3 min-w-0">
              <span className="flex items-center justify-center w-9 h-9 rounded-xl bg-teal-50 ring-1 ring-teal-100 shrink-0">
                <Sparkles className="w-4 h-4 text-teal-600" />
              </span>
              <span className="text-sm font-medium text-ink truncate">{a.label}</span>
            </span>
            <ArrowRight className="w-4 h-4 text-ink-muted group-hover:text-teal-600 transition-colors shrink-0" />
          </Link>
        ))}
      </div>
    </section>
  );
}

/* Register this surface's widgets into the open registry (runs once at module
   load). `briefing_hero` is a v2 semantic alias of the persona `verdict`. New
   feed-backed widgets (business_health, risks, growth, recommendations) register
   from the Copilot feed surface in a later phase; until then the backend can
   list them and they degrade gracefully. */
registerWidgets({
  verdict: VerdictZone,
  briefing_hero: VerdictZone,
  kpis: KpiZone,
  decisions: DecisionsZone,
  approvals: ApprovalsZone,
  stock: StockZone,
  quick_actions: QuickActionsWidget,
});
