'use client';

/**
 * Incrementality — the proof-of-value surface.
 *
 * THE ONE NUMBER THIS PAGE EXISTS FOR: incremental gross margin per AED of
 * promo spend, net of VAT, measured against a held-out control. Everything else
 * is context for it.
 *
 * TWO DESIGN RULES THAT ARE NOT NEGOTIABLE HERE.
 *
 * 1. "Not yet significant" is styled as a NORMAL state, never as an error or a
 *    warning. A campaign that has not accumulated evidence has not done anything
 *    wrong. Styling it as a problem trains operators to stop campaigns the
 *    moment they look good — which is the precise behaviour the anytime-valid
 *    interval was adopted to make safe. A red badge here would undo the
 *    statistics.
 *
 * 2. Every probability is shown WITH its interval. A point estimate of +2.1%
 *    and a point estimate of +2.1% [-4.0%, +8.2%] must never look alike; the
 *    second one says almost nothing and the UI has to admit that.
 *
 * The interval is a CONFIDENCE SEQUENCE — valid at every sample size at once —
 * so refreshing this page as often as you like does not inflate the error rate.
 * That property is stated on the page because it changes how it should be used.
 */
import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, RefreshCw, ShieldCheck, TrendingUp } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import {
  aed, fetchCampaigns, fetchCampaignReadout, fetchIncrementality,
  fetchReadoutHistory, pct, READOUT_TONE, recomputeReadout,
} from '@/lib/flywheel';
import type {
  CampaignReadout, CampaignSummary, IncrementalitySummary, ReadoutPoint,
} from '@/types/flywheel';

/** Bar showing where an interval sits relative to zero.
 *
 *  Rendered as a proportion of a fixed visual range rather than auto-scaled:
 *  an auto-scaled axis makes a tiny, uncertain effect look decisive, which is
 *  the most common way an honest chart misleads. */
function IntervalBar({ lower, upper, estimate }: {
  lower: number | null; upper: number | null; estimate: number;
}) {
  if (lower === null || upper === null) {
    return (
      <div className="text-xs text-ink-muted italic">
        interval not yet computable
      </div>
    );
  }
  const RANGE = 0.4; // ±40 percentage points of visual span
  const toPct = (v: number) => ((Math.max(-RANGE, Math.min(RANGE, v)) + RANGE) / (2 * RANGE)) * 100;
  const left = toPct(lower);
  const right = toPct(upper);
  const mid = toPct(estimate);
  const excludesZero = lower > 0 || upper < 0;

  return (
    <div className="w-full">
      <div className="relative h-6 rounded bg-surface-2 overflow-hidden">
        {/* zero line — the only reference that matters */}
        <div className="absolute inset-y-0 w-px bg-ink-muted" style={{ left: '50%' }} />
        <div
          className={`absolute inset-y-1 rounded ${excludesZero ? 'bg-signal-up' : 'bg-surface-3'}`}
          style={{ left: `${left}%`, width: `${Math.max(1, right - left)}%` }}
        />
        <div
          className={`absolute inset-y-0 w-0.5 ${excludesZero ? 'bg-signal-up' : 'bg-ink-muted'}`}
          style={{ left: `${mid}%` }}
        />
      </div>
      <div className="flex justify-between text-[11px] text-ink-muted mt-1 tabular-nums">
        <span>{(lower * 100).toFixed(1)}%</span>
        <span className="font-medium text-ink">{(estimate * 100).toFixed(2)}%</span>
        <span>{(upper * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
}

export default function IncrementalityPage() {
  const [summary, setSummary] = useState<IncrementalitySummary | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [readout, setReadout] = useState<CampaignReadout | null>(null);
  const [series, setSeries] = useState<ReadoutPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, c] = await Promise.all([fetchIncrementality(), fetchCampaigns()]);
      setSummary(s);
      const list = c?.campaigns ?? [];
      setCampaigns(list);
      if (list.length && selected === null) setSelected(list[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load incrementality');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    (async () => {
      try {
        const [r, h] = await Promise.all([
          fetchCampaignReadout(selected),
          fetchReadoutHistory(selected),
        ]);
        if (cancelled) return;
        setReadout(r);
        setSeries(h?.series ?? []);
      } catch {
        if (!cancelled) { setReadout(null); setSeries([]); }
      }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  const recompute = async () => {
    if (selected === null) return;
    setBusy(true);
    try {
      await recomputeReadout(selected);
      const [r, h] = await Promise.all([
        fetchCampaignReadout(selected), fetchReadoutHistory(selected),
      ]);
      setReadout(r);
      setSeries(h?.series ?? []);
      setSummary(await fetchIncrementality());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Recompute failed');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-96" /></div>;
  }
  if (error && !summary) {
    return <div className="p-6"><ErrorState title="Incrementality unavailable" description={error} onRetry={load} /></div>;
  }

  const point = readout?.readout ?? null;
  const interp = readout?.interpretation ?? null;

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Incrementality"
        description="What the programme actually earned, measured against a held-out control. Gross figures are shown separately and are not the contribution."
        icon={<TrendingUp className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      {/* ── THE HEADLINE ───────────────────────────────────────────────── */}
      <Reveal>
        <Card padding="lg" className="mb-6">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <div className="text-xs uppercase tracking-wide text-ink-muted mb-1">
                Incremental margin per AED spent
              </div>
              <div className="text-4xl font-semibold tabular-nums">
                {summary?.margin_per_aed_spent
                  ? `${aed(summary.margin_per_aed_spent)}`
                  : <span className="text-ink-muted text-2xl">not yet measurable</span>}
              </div>
              <div className="text-sm text-ink-muted mt-2 max-w-xl">
                Net of VAT, against control. {summary?.margin_per_aed_spent
                  ? 'Every dirham of promo spend returned this much incremental gross margin.'
                  : 'No campaign has both spend and a measurable control outcome yet.'}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
              <div>
                <div className="text-ink-muted">Incremental margin</div>
                <div className="text-lg font-medium tabular-nums">
                  {aed(summary?.incremental_margin_aed)} AED
                </div>
              </div>
              <div>
                <div className="text-ink-muted">Total spend</div>
                <div className="text-lg font-medium tabular-nums">
                  {aed(summary?.total_spend_aed)} AED
                </div>
              </div>
              <div>
                <div className="text-ink-muted">Proven positive</div>
                <div className="text-lg font-medium tabular-nums">{summary?.proven_positive ?? 0}</div>
              </div>
              <div>
                <div className="text-ink-muted">Still measuring</div>
                <div className="text-lg font-medium tabular-nums">{summary?.inconclusive ?? 0}</div>
              </div>
            </div>
          </div>
          {summary?.proven_negative ? (
            <div className="mt-4 flex items-start gap-2 text-sm text-rose-600">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>
                {summary.proven_negative} campaign(s) measured a NEGATIVE effect — the treated
                group did worse than control. Investigate before repeating them.
              </span>
            </div>
          ) : null}
          <div className="mt-4 pt-4 border-t border-line text-xs text-ink-muted">
            {summary?.note}
          </div>
        </Card>
      </Reveal>

      {/* ── PER-CAMPAIGN ───────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 mb-4">
        {campaigns.map((c) => (
          <Button
            key={c.id}
            variant={selected === c.id ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setSelected(c.id)}
          >
            {c.name}
          </Button>
        ))}
      </div>

      {selected === null ? (
        <Card padding="lg">
          <EmptyState title="No campaigns" description="Create a campaign to measure it." />
        </Card>
      ) : (
        <div className="space-y-4">
          <Reveal>
            <Card padding="lg" className="mb-4">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={READOUT_TONE[interp?.state ?? 'not_measurable']}>
                      {interp?.headline ?? 'Not yet measured'}
                    </Badge>
                    {readout?.preregistration ? (
                      <Badge variant="teal">
                        <ShieldCheck className="w-3 h-3 me-1 inline" />pre-registered
                      </Badge>
                    ) : (
                      <Badge variant="amber">not pre-registered</Badge>
                    )}
                  </div>
                  <p className="text-sm text-ink-muted max-w-2xl">
                    {interp?.detail ?? 'The scheduler measures hourly. No readout has been produced yet.'}
                  </p>
                </div>
                <Button variant="ghost" size="sm" onClick={recompute} disabled={busy}>
                  {busy ? 'Measuring…' : 'Recompute now'}
                </Button>
              </div>

              {point ? (
                <>
                  <div className="mb-5">
                    <div className="text-xs uppercase tracking-wide text-ink-muted mb-2">
                      Effect on retention, with anytime-valid interval
                    </div>
                    <IntervalBar
                      lower={point.ci_lower}
                      upper={point.ci_upper}
                      estimate={point.incremental_retention}
                    />
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <div className="text-ink-muted">Treatment</div>
                      <div className="tabular-nums">
                        {point.treatment_converted}/{point.treatment_n}
                        <span className="text-ink-muted ms-1">
                          ({point.treatment_n ? pct(point.treatment_converted / point.treatment_n) : '—'})
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="text-ink-muted">Control (held out)</div>
                      <div className="tabular-nums">
                        {point.control_converted}/{point.control_n}
                        <span className="text-ink-muted ms-1">
                          ({point.control_n ? pct(point.control_converted / point.control_n) : '—'})
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="text-ink-muted">Incremental margin</div>
                      <div className="tabular-nums">{aed(point.incremental_margin_aed)} AED</div>
                    </div>
                    <div>
                      <div className="text-ink-muted">Margin per AED</div>
                      <div className="tabular-nums">
                        {point.margin_per_aed_spent ? aed(point.margin_per_aed_spent) : '—'}
                      </div>
                    </div>
                  </div>

                  {point.validity_warnings?.length ? (
                    <div className="mt-5 pt-4 border-t border-line space-y-2">
                      {point.validity_warnings.map((w, i) => (
                        <div key={i} className="flex items-start gap-2 text-sm text-amber-600">
                          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                          <span>{w}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  title="No readout yet"
                  description="This is normal early in a campaign. The scheduler measures hourly, or recompute now."
                />
              )}
            </Card>
          </Reveal>

          {/* ── EVIDENCE OVER TIME ─────────────────────────────────────── */}
          {series.length > 1 ? (
            <Reveal>
              <Card padding="lg">
                <div className="mb-3">
                  <h3 className="font-medium">How the evidence accumulated</h3>
                  <p className="text-sm text-ink-muted">
                    The interval is valid at every point below simultaneously — it was
                    safe to watch it narrow, and safe to stop whenever.
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHead>
                      <TableRow>
                        <Th>Window end</Th><Th>Arms (T/C)</Th><Th>Effect</Th>
                        <Th>Interval</Th><Th>Evidence (log-e)</Th><Th>Verdict</Th>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {series.slice().reverse().map((p) => (
                        <TableRow key={p.window_end}>
                          <Td className="tabular-nums">{p.window_end}</Td>
                          <Td className="tabular-nums">{p.treatment_n}/{p.control_n}</Td>
                          <Td className="tabular-nums">{(p.incremental_retention * 100).toFixed(2)}%</Td>
                          <Td className="tabular-nums text-ink-muted">
                            {p.ci_lower !== null && p.ci_upper !== null
                              ? `[${(p.ci_lower * 100).toFixed(1)}, ${(p.ci_upper * 100).toFixed(1)}]`
                              : '—'}
                          </Td>
                          <Td className="tabular-nums">
                            {p.log_e_value !== null ? p.log_e_value.toFixed(2) : '—'}
                          </Td>
                          <Td>
                            <Badge variant={p.is_significant ? 'success' : 'neutral'}>
                              {p.is_significant ? 'conclusive' : 'measuring'}
                            </Badge>
                          </Td>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </Card>
            </Reveal>
          ) : null}
        </div>
      )}

      <div className="mt-6 flex items-start gap-2 text-xs text-ink-muted max-w-3xl">
        <Activity className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          Intervals are empirical-Bernstein confidence sequences, valid under continuous
          monitoring and optional stopping. A conventional fixed-horizon interval read this
          way would report an effect that is not there in roughly one campaign in three.
        </span>
      </div>
    </div>
  );
}
