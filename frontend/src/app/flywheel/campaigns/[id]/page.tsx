'use client';

/**
 * Campaign detail = Live Control Centre (§20.6) + state history + measurement.
 *
 * LIVE MEANS LIVE. This page subscribes to `/stream/flywheel` via the shared
 * ref-counted EventStream hook and refetches on any event touching this
 * campaign. Every event it receives came from the transactional outbox, which
 * means it reflects COMMITTED state — the page can never show a redemption that
 * was rolled back.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  Activity, AlertTriangle, ArrowLeft, BarChart3, Loader2, Pause, Play,
  RefreshCw, Square,
} from 'lucide-react';
import {
  Badge, Button, Card, ErrorState, PageHeader, Skeleton,
} from '@/components/ui';
import { useEventStream } from '@/hooks/useEventStream';
import {
  LoopRing, Reveal, Stagger, StaggerItem, SyntheticBadge, stageForStatus,
} from '@/components/flywheel/motion';
import {
  STATUS_TONE, aed, activateCampaign, concludeCampaign, fetchCampaign,
  fetchLive, fetchOutcome, measureCampaign, pauseCampaign, pct, resumeCampaign,
} from '@/lib/flywheel';
import type { CampaignDetail, LiveMetrics, MeasurementResult } from '@/types/flywheel';

export default function CampaignPage() {
  const params = useParams();
  const id = Number(params?.id);

  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [live, setLive] = useState<LiveMetrics | null>(null);
  const [outcome, setOutcome] = useState<MeasurementResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    setError(null);
    try {
      const [d, l] = await Promise.all([fetchCampaign(id), fetchLive(id)]);
      setDetail(d);
      setLive(l);
      // The outcome only exists after measurement — a 404 here is normal, not
      // an error worth surfacing.
      try { setOutcome(await fetchOutcome(id)); } catch { setOutcome(null); }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the campaign');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  // Refetch when an event mentions THIS campaign. Filtering here (rather than
  // refetching on every Flywheel event) keeps an active tenant from hammering the
  // API while ten campaigns run.
  const handlers = useMemo(() => {
    const refresh = (payload: { campaign_id?: number }) => {
      if (!payload || payload.campaign_id === id || payload.campaign_id === undefined) void load();
    };
    return {
      'offer.redeemed': refresh,
      'offer.issued': refresh,
      'campaign.activated': refresh,
      'campaign.auto_paused': refresh,
      'campaign.measured': refresh,
      'inventory.decremented': refresh,
      'approval.decided': refresh,
    };
  }, [id, load]);

  const { isConnected } = useEventStream('/stream/flywheel', { eventHandlers: handlers });

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Action failed'); }
    finally { setBusy(false); }
  }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-96" /></div>;
  }
  if (error && !detail) {
    return <div className="p-6"><ErrorState title="Campaign unavailable" description={error} onRetry={load} /></div>;
  }
  if (!detail || !live) return null;

  const c = detail.campaign;
  const canActivate = c.status === 'APPROVED' || c.status === 'SCHEDULED';
  const canPause = c.status === 'ACTIVE';
  const canResume = c.status === 'PAUSED';
  const canConclude = ['ACTIVE', 'PAUSED'].includes(c.status);
  const canMeasure = ['COMPLETED', 'MEASURED'].includes(c.status);

  return (
    <div className="p-6">
      <Link href="/flywheel"
            className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-teal-700 dark:hover:text-teal-300">
        <ArrowLeft className="w-3.5 h-3.5" />Flywheel command centre
      </Link>

      <PageHeader
        eyebrow={`Campaign #${c.id} · ${c.objective.replace(/_/g, ' ')}`}
        title={c.name}
        description={`${c.starts_on} → ${c.ends_on} · ${c.channel} · max ${c.max_discount_pct}% discount, ${c.min_margin_pct}% margin floor`}
        icon={<Activity className="w-5 h-5" />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SyntheticBadge />
            <Badge variant={STATUS_TONE[c.status] ?? 'neutral'}>
              {c.status.replace(/_/g, ' ').toLowerCase()}
            </Badge>
            {isConnected && (
              <span className="inline-flex items-center gap-1.5 text-[11px] text-teal-700 dark:text-teal-300">
                <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-teal-500" />live
              </span>
            )}
            <Button variant="ghost" onClick={load} aria-label="Refresh"><RefreshCw className="w-4 h-4" /></Button>
          </div>
        }
      />

      {c.pause_reason && (
        <div role="alert" className="mb-5 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Campaign paused</p>
            <p className="mt-0.5 text-xs">{c.pause_reason}</p>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </div>
      )}

      {/* Controls */}
      <div className="mb-6 flex flex-wrap gap-2">
        {canActivate && (
          <Button variant="primary" disabled={busy} onClick={() => act(() => activateCampaign(id))}>
            {busy ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Play className="w-4 h-4 mr-1.5" />}
            Activate
          </Button>
        )}
        {canPause && (
          <Button variant="secondary" disabled={busy}
                  onClick={() => act(() => pauseCampaign(id, 'Paused manually by operator'))}>
            <Pause className="w-4 h-4 mr-1.5" />Pause
          </Button>
        )}
        {canResume && (
          <Button variant="primary" disabled={busy} onClick={() => act(() => resumeCampaign(id))}>
            <Play className="w-4 h-4 mr-1.5" />Resume
          </Button>
        )}
        {canConclude && (
          <Button variant="secondary" disabled={busy} onClick={() => act(() => concludeCampaign(id, false))}>
            <Square className="w-4 h-4 mr-1.5" />Complete
          </Button>
        )}
        {canMeasure && (
          <Button variant="primary" disabled={busy}
                  onClick={() => act(async () => { setOutcome(await measureCampaign(id)); })}>
            <BarChart3 className="w-4 h-4 mr-1.5" />Measure lift
          </Button>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Reveal>
          <Card padding="lg">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Loop position</h2>
            <div className="mt-4 flex justify-center">
              <LoopRing activeStage={stageForStatus(c.status)} size={210} />
            </div>
          </Card>
        </Reveal>

        <div className="space-y-6">
          <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StaggerItem>
              <Card padding="md">
                <p className="text-[11px] uppercase tracking-wider text-slate-400">Treatment</p>
                <p className="mt-1 font-mono text-2xl text-slate-900 dark:text-slate-100">
                  {(live.audience.treatment ?? 0).toLocaleString()}
                </p>
                <p className="text-[11px] text-slate-500">
                  vs {(live.audience.control ?? 0).toLocaleString()} control
                </p>
              </Card>
            </StaggerItem>
            <StaggerItem>
              <Card padding="md">
                <p className="text-[11px] uppercase tracking-wider text-slate-400">Offers issued</p>
                <p className="mt-1 font-mono text-2xl text-slate-900 dark:text-slate-100">
                  {(live.offers.issued ?? 0).toLocaleString()}
                </p>
                <p className="text-[11px] text-slate-500">
                  {(live.offers.redeemed ?? 0).toLocaleString()} redeemed
                </p>
              </Card>
            </StaggerItem>
            <StaggerItem>
              <Card padding="md">
                <p className="text-[11px] uppercase tracking-wider text-slate-400">Discount spent</p>
                <p className="mt-1 font-mono text-2xl text-amber-700 dark:text-amber-400">
                  {aed(live.redemptions.discount_aed, { compact: true })}
                </p>
                <p className="text-[11px] text-slate-500">
                  of {aed(live.budget.reserved_aed, { compact: true })} reserved
                </p>
              </Card>
            </StaggerItem>
            <StaggerItem>
              <Card padding="md">
                <p className="text-[11px] uppercase tracking-wider text-slate-400">Budget burn</p>
                <p className={`mt-1 font-mono text-2xl ${live.budget.burn_pct > 90
                  ? 'text-rose-600 dark:text-rose-400' : 'text-slate-900 dark:text-slate-100'}`}>
                  {live.budget.burn_pct.toFixed(0)}%
                </p>
                <div className="mt-2 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
                  <div className={`h-full rounded-full transition-[width] duration-500 ${
                    live.budget.burn_pct > 90 ? 'bg-rose-500' : 'bg-teal-500'}`}
                       style={{ width: `${Math.min(100, live.budget.burn_pct)}%` }} />
                </div>
              </Card>
            </StaggerItem>
          </Stagger>

          {live.guardrails.breaches.length > 0 && (
            <Reveal>
              <Card padding="lg" className="border-amber-300 dark:border-amber-500/40">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
                  <AlertTriangle className="w-4 h-4" />
                  Guardrail {live.guardrails.hard_breaches > 0 ? 'breaches' : 'warnings'}
                </h2>
                <ul className="mt-3 space-y-2">
                  {live.guardrails.breaches.map((breach, i) => (
                    <li key={i} className="rounded-lg bg-amber-50 p-3 text-xs dark:bg-amber-500/10">
                      <p className="font-medium text-amber-900 dark:text-amber-300">
                        {breach.breach.replace(/_/g, ' ').toLowerCase()}
                      </p>
                      <p className="mt-0.5 text-amber-800 dark:text-amber-400">{breach.detail}</p>
                    </li>
                  ))}
                </ul>
              </Card>
            </Reveal>
          )}

          {outcome && (
            <Reveal>
              <Card padding="lg">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Measured lift — treatment vs control
                </h2>

                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800/50">
                    <p className="text-[11px] text-slate-500">Treatment retention</p>
                    <p className="mt-1 font-mono text-xl text-slate-900 dark:text-slate-100">
                      {pct(outcome.treatment.retention_rate)}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      {outcome.treatment.retained}/{outcome.treatment.size}
                    </p>
                  </div>
                  <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800/50">
                    <p className="text-[11px] text-slate-500">Control retention</p>
                    <p className="mt-1 font-mono text-xl text-slate-900 dark:text-slate-100">
                      {pct(outcome.control.retention_rate)}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      {outcome.control.retained}/{outcome.control.size}
                    </p>
                  </div>
                  <div className={`rounded-lg p-4 ${outcome.incremental_retention >= 0
                    ? 'bg-teal-50 dark:bg-teal-500/10' : 'bg-rose-50 dark:bg-rose-500/10'}`}>
                    <p className="text-[11px] text-slate-500">Incremental (causal)</p>
                    <p className={`mt-1 font-mono text-xl ${outcome.incremental_retention >= 0
                      ? 'text-teal-700 dark:text-teal-300' : 'text-rose-700 dark:text-rose-400'}`}>
                      {outcome.incremental_retention >= 0 ? '+' : ''}
                      {pct(outcome.incremental_retention)}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      {outcome.incremental_customers_retained} customers
                    </p>
                  </div>
                </div>

                <dl className="mt-4 grid gap-3 sm:grid-cols-4 text-xs">
                  <div>
                    <dt className="text-slate-500">Incremental margin</dt>
                    <dd className="font-mono text-slate-900 dark:text-slate-100">
                      {aed(outcome.incremental_margin_aed)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Discount spend</dt>
                    <dd className="font-mono text-amber-700 dark:text-amber-400">
                      {aed(outcome.discount_spend_aed)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Cost / retained</dt>
                    <dd className="font-mono text-slate-900 dark:text-slate-100">
                      {outcome.cost_per_retained_aed ? aed(outcome.cost_per_retained_aed) : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Campaign ROI</dt>
                    <dd className="font-mono text-teal-700 dark:text-teal-300">
                      {outcome.campaign_roi ?? '—'}
                    </dd>
                  </div>
                </dl>

                {outcome.validity.length > 0 && (
                  <ul className="mt-4 space-y-1.5">
                    {outcome.validity.map((warning, i) => (
                      <li key={i} className="flex items-start gap-2 rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-900 dark:bg-amber-500/10 dark:text-amber-300">
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <span>{warning}</span>
                      </li>
                    ))}
                  </ul>
                )}

                <p className="mt-4 text-[11px] italic text-slate-400">{outcome.causal_note}</p>
              </Card>
            </Reveal>
          )}

          <Reveal>
            <Card padding="lg">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                State history
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Every transition, with who made it and why. Guardrail-driven changes are marked.
              </p>
              <ol className="mt-4 space-y-3">
                {detail.history.map((h, i) => (
                  <li key={i} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <span aria-hidden className={`mt-1 h-2 w-2 rounded-full ${
                        h.actor_kind === 'guardrail' ? 'bg-rose-500'
                          : h.actor_kind === 'system' ? 'bg-slate-400' : 'bg-teal-500'}`} />
                      {i < detail.history.length - 1 && (
                        <span aria-hidden className="mt-1 w-px flex-1 bg-slate-200 dark:bg-slate-700" />
                      )}
                    </div>
                    <div className="pb-3">
                      <p className="text-xs font-medium text-slate-900 dark:text-slate-100">
                        {h.from ? `${h.from.replace(/_/g, ' ')} → ` : ''}
                        {h.to.replace(/_/g, ' ')}
                        {h.actor_kind === 'guardrail' && (
                          <Badge variant="danger" className="ml-2">auto</Badge>
                        )}
                      </p>
                      {h.reason && (
                        <p className="mt-0.5 text-[11px] text-slate-500">{h.reason}</p>
                      )}
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        {new Date(h.at).toLocaleString()}
                        {h.actor && ` · ${h.actor}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          </Reveal>
        </div>
      </div>
    </div>
  );
}
