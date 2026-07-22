'use client';

/**
 * Decision Trace (§20.7) — the full explainability surface.
 *
 * The claim this page has to make good on: *the selected action is reproducible
 * from its stored inputs*. So it does not just narrate the decision — it shows
 * the REPLAY, where the backend recomputes EIV from the persisted terms and
 * reports whether it still matches what was recorded.
 *
 * The rejected alternatives are given equal weight to the selection. Knowing a
 * 20% discount was considered and refused for breaching the margin floor is
 * more useful to an operator than knowing a reminder was chosen.
 */
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, CheckCircle2, ScrollText, XCircle } from 'lucide-react';
import { Badge, Card, ErrorState, PageHeader, Skeleton } from '@/components/ui';
import { EivWaterfall, Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchDecisionTrace, pct, reasonText } from '@/lib/flywheel';
import type { DecisionTrace } from '@/types/flywheel';

export default function DecisionTracePage() {
  const params = useParams();
  const id = Number(params?.id);
  const [trace, setTrace] = useState<DecisionTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    setError(null);
    try { setTrace(await fetchDecisionTrace(id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the decision'); }
    finally { setLoading(false); }
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-96" /></div>;
  }
  if (error || !trace) {
    return <div className="p-6"><ErrorState title="Decision unavailable" description={error ?? 'Not found'} onRetry={load} /></div>;
  }

  const b = trace.eiv_breakdown;
  const num = (v: string | undefined) => Number.parseFloat(v ?? '0') || 0;

  const waterfall = [
    { label: 'Expected retained value', value: num(b.expected_retained_value_aed), kind: 'benefit' as const },
    { label: 'Expected incremental margin', value: num(b.expected_margin_aed), kind: 'benefit' as const },
    { label: 'Discount cost', value: num(b.less_discount_cost_aed), kind: 'cost' as const },
    { label: 'Communication cost', value: num(b.less_comms_cost_aed), kind: 'cost' as const },
    { label: 'Fulfilment cost', value: num(b.less_fulfilment_cost_aed), kind: 'cost' as const },
    { label: 'Procurement cost', value: num(b.less_procurement_cost_aed), kind: 'cost' as const },
    { label: 'Stockout-risk penalty', value: num(b.less_stockout_penalty_aed), kind: 'cost' as const },
    { label: 'Expected incremental value (EIV)', value: num(b.eiv_aed), kind: 'net' as const },
  ];

  const inv = trace.inventory_snapshot as Record<string, number>;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <Link href="/flywheel/customers"
            className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted hover:text-teal-700 dark:hover:text-teal-300">
        <ArrowLeft className="w-3.5 h-3.5" />Customers
      </Link>

      <PageHeader
        eyebrow={`Decision #${trace.decision.id} · ${new Date(trace.decision.decided_at).toLocaleString()}`}
        title={trace.decision.action_type.replace(/_/g, ' ').toLowerCase()}
        description={`${trace.decision.customer_name ?? `Customer ${trace.decision.customer_id}`}${
          trace.decision.store_name ? ` at ${trace.decision.store_name}` : ''}${
          trace.decision.item_name ? ` · ${trace.decision.item_name}` : ''}`}
        icon={<ScrollText className="w-5 h-5" />}
        actions={<SyntheticBadge />}
      />

      {/* Reproducibility — the headline claim, verified. */}
      <Reveal>
        <div className={`mb-6 flex items-start gap-3 rounded-lg border p-4 ${
          trace.reproducibility.matches
            ? 'border-teal-300 bg-teal-50 dark:border-teal-600/40 dark:bg-teal-500/10'
            : 'border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10'
        }`}>
          {trace.reproducibility.matches
            ? <CheckCircle2 className="w-5 h-5 shrink-0 text-teal-700 dark:text-teal-300" />
            : <XCircle className="w-5 h-5 shrink-0 text-amber-700 dark:text-amber-400" />}
          <div>
            <p className="text-sm font-medium text-ink">
              {trace.reproducibility.matches
                ? 'Reproducible from stored inputs'
                : 'Recomputation differs from the recorded value'}
            </p>
            <p className="mt-0.5 text-xs text-ink-soft">
              Recomputing EIV from the persisted terms gives{' '}
              <span className="font-mono">{aed(trace.reproducibility.recomputed_eiv_aed)}</span> AED
              against a recorded{' '}
              <span className="font-mono">{aed(trace.reproducibility.recorded_eiv_aed)}</span> AED
              {!trace.reproducibility.matches && (
                <> — a delta of <span className="font-mono">{aed(trace.reproducibility.delta_aed)}</span> AED</>
              )}
              . Policy version {trace.policy_version}.
            </p>
          </div>
        </div>
      </Reveal>

      <div className="grid gap-6 lg:grid-cols-2">
        <Reveal>
          <Card padding="lg" className="h-full">
            <h2 className="text-sm font-semibold text-ink">
              How the value was calculated
            </h2>
            <p className="mt-1 text-xs text-ink-muted">
              Benefits multiply <em>uplift</em>, never churn probability — which is why a
              high-risk customer with no persuadability yields nothing.
            </p>
            <div className="mt-4">
              <EivWaterfall terms={waterfall} />
            </div>
          </Card>
        </Reveal>

        <div className="space-y-6">
          <Reveal delay={0.05}>
            <Card padding="lg">
              <h2 className="text-sm font-semibold text-ink">
                What the models proposed
              </h2>
              <dl className="mt-4 grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-surface-2 p-3">
                  <dd className="font-mono text-lg text-ink">
                    {pct(trace.model_inputs.churn_probability, 0)}
                  </dd>
                  <dt className="text-[11px] text-ink-muted">churn risk</dt>
                </div>
                <div className="rounded-lg bg-surface-2 p-3">
                  <dd className={`font-mono text-lg ${trace.model_inputs.uplift >= 0
                    ? 'text-teal-700 dark:text-teal-300' : 'text-rose-600 dark:text-rose-400'}`}>
                    {(trace.model_inputs.uplift * 100).toFixed(2)}%
                  </dd>
                  <dt className="text-[11px] text-ink-muted">uplift</dt>
                </div>
                <div className="rounded-lg bg-surface-2 p-3">
                  <dd className="font-mono text-lg text-ink">
                    {pct(trace.model_inputs.redemption_probability, 0)}
                  </dd>
                  <dt className="text-[11px] text-ink-muted">redemption</dt>
                </div>
              </dl>
              <p className="mt-3 text-[11px] text-ink-muted">
                {trace.model_inputs.churn_model ?? 'unknown model'}
                {trace.model_inputs.algorithm && ` (${trace.model_inputs.algorithm})`}
                {' · '}models propose only — this decision was made by a deterministic service.
              </p>
            </Card>
          </Reveal>

          <Reveal delay={0.1}>
            <Card padding="lg">
              <h2 className="text-sm font-semibold text-ink">
                Price & cost at the moment of decision
              </h2>
              <dl className="mt-3 space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Unit price</dt>
                  <dd className="font-mono">{aed(trace.price_snapshot.unit_price_aed)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Unit cost</dt>
                  <dd className="font-mono">{aed(trace.price_snapshot.unit_cost_aed)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-muted">Discount applied</dt>
                  <dd className="font-mono">{trace.price_snapshot.discount_pct}%</dd>
                </div>
              </dl>
              <p className="mt-3 text-[11px] italic text-ink-muted">{trace.price_snapshot.note}</p>
            </Card>
          </Reveal>
        </div>
      </div>

      {Object.keys(inv ?? {}).length > 0 && (
        <Reveal delay={0.1}>
          <Card padding="lg" className="mt-6">
            <h2 className="text-sm font-semibold text-ink">
              Stock available to promise
            </h2>
            <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-3 font-mono text-xs">
              {([
                ['on hand', inv.on_hand, ''],
                ['incoming', inv.incoming, '+'],
                ['reservations', inv.hard_reservations, '−'],
                ['allocations', inv.soft_allocations, '−'],
                ['safety stock', inv.safety_stock, '−'],
                ['demand buffer', inv.demand_buffer, '−'],
              ] as const).map(([label, value, sign]) => (
                <span key={label} className="flex items-baseline gap-1">
                  {sign && <span className="text-ink-muted">{sign}</span>}
                  <span className="rounded bg-surface-2 px-2 py-1">
                    {value ?? 0} <span className="text-ink-muted">{label}</span>
                  </span>
                </span>
              ))}
              <span className="text-ink-muted">=</span>
              <span className="rounded bg-teal-100 px-2.5 py-1 font-semibold text-teal-800 dark:bg-teal-500/20 dark:text-teal-300">
                {inv.atp_units ?? 0} available
              </span>
            </div>
          </Card>
        </Reveal>
      )}

      <Reveal delay={0.15}>
        <Card padding="lg" className="mt-6">
          <h2 className="text-sm font-semibold text-ink">
            Why this action
          </h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {trace.reason_codes.map((code) => (
              <li key={code}>
                <Badge variant="teal">{reasonText(code)}</Badge>
              </li>
            ))}
          </ul>

          {trace.rejected_actions.length > 0 && (
            <>
              <h3 className="mt-6 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Considered and refused ({trace.rejected_actions.length})
              </h3>
              <ul className="mt-3 space-y-2">
                {trace.rejected_actions.map((rejected, i) => (
                  <li key={i}
                      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-line p-3 text-xs">
                    <span className="font-medium text-ink-soft">
                      {rejected.action.replace(/_/g, ' ').toLowerCase()}
                      {rejected.discount_pct && rejected.discount_pct !== '0'
                        ? ` at ${rejected.discount_pct}%` : ''}
                    </span>
                    <Badge variant="neutral">{reasonText(rejected.reason_code)}</Badge>
                    {rejected.detail && (
                      <span className="w-full text-[11px] text-ink-muted">{rejected.detail}</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </Reveal>
    </div>
  );
}
