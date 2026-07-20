'use client';

/**
 * Customer view (§20.8) + the live decision demo.
 *
 * Two jobs on one page, deliberately: browsing at-risk customers is only
 * interesting if you can immediately ask "so what would you offer THIS person,
 * and why?". The right-hand panel calls the real `/decisioning/evaluate`
 * endpoint — the same one a POS would call — and shows the answer including
 * every rejected alternative.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Loader2, RefreshCw, Sparkles, Users, Zap } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
} from '@/components/ui';
import { Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import {
  RISK_TONE, aed, evaluateDecision, fetchCustomer, fetchCustomers, pct, reasonText,
} from '@/lib/flywheel';
import type { CustomerDetail, EvaluateResult, FlywheelCustomer } from '@/types/flywheel';

export default function CustomersPage() {
  const [customers, setCustomers] = useState<FlywheelCustomer[]>([]);
  const [detail, setDetail] = useState<CustomerDetail | null>(null);
  const [decision, setDecision] = useState<EvaluateResult | null>(null);
  const [band, setBand] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (riskBand: string) => {
    setError(null);
    try {
      const result = await fetchCustomers({
        risk_band: riskBand || undefined, limit: 60,
      });
      setCustomers(result.customers);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load customers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(band); }, [band, load]);

  const select = useCallback(async (id: number) => {
    setDecision(null); setError(null);
    try { setDetail(await fetchCustomer(id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the customer'); }
  }, []);

  const evaluate = useCallback(async () => {
    if (!detail) return;
    setBusy(true); setError(null);
    try {
      setDecision(await evaluateDecision({
        customer_id: detail.customer.id,
        store_id: detail.customer.store_id,
        channel: 'email',
        issue_offer: false, // a preview must not consume a contact slot
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Evaluation failed');
    } finally {
      setBusy(false);
    }
  }, [detail]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-96" /></div>;
  }

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Customers at risk"
        description="Churn scores with the behaviour that produced them. Ask for a live next-best action on any customer."
        icon={<Users className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={() => load(band)} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {['', 'critical', 'high', 'medium', 'low'].map((b) => (
          <button
            key={b || 'all'} type="button" onClick={() => setBand(b)}
            aria-pressed={band === b}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline
                        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 ${
              band === b ? 'bg-teal-700 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            {b === '' ? 'All risk bands' : b}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span>{error}</span>
        </div>
      )}

      {customers.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={<Users className="w-6 h-6" />}
            title="No customers scored yet"
            description="Generate the synthetic customer layer and score churn risk from the Flywheel command centre."
            action={<Link href="/flywheel"><Button variant="primary">Go to Flywheel</Button></Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
          <Card padding="none" className="overflow-hidden">
            <ul className="divide-y divide-slate-100 dark:divide-slate-800 max-h-[70vh] overflow-y-auto">
              {customers.map((customer, i) => (
                <li key={customer.id}>
                  <button
                    type="button" onClick={() => select(customer.id)}
                    aria-current={detail?.customer.id === customer.id ? 'true' : undefined}
                    className={`w-full px-4 py-3 text-left transition-colors focus-visible:outline
                                focus-visible:outline-2 focus-visible:-outline-offset-2
                                focus-visible:outline-teal-600 ${
                      detail?.customer.id === customer.id
                        ? 'bg-teal-50/60 dark:bg-teal-500/5'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                          {customer.display_name}
                        </p>
                        <p className="truncate text-[11px] text-slate-500">
                          {customer.store_name} · {customer.loyalty_tier} · {customer.status}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="font-mono text-sm tabular-nums text-slate-900 dark:text-slate-100">
                          {customer.churn_probability !== null
                            ? pct(customer.churn_probability, 0) : '—'}
                        </span>
                        {customer.risk_band && (
                          <Badge variant={RISK_TONE[customer.risk_band] ?? 'neutral'}>
                            {customer.risk_band}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          <div className="space-y-4">
            {!detail ? (
              <Card padding="lg">
                <p className="text-sm text-slate-500">
                  Select a customer to see their behaviour, the drivers behind their risk score,
                  and what Flywheel would offer them right now.
                </p>
              </Card>
            ) : (
              <>
                <Reveal>
                  <Card padding="lg">
                    <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {detail.customer.display_name}
                    </h2>
                    <p className="text-[11px] text-slate-500">
                      {detail.customer.external_ref} · joined {detail.customer.enrolled_on}
                    </p>

                    {detail.churn && (
                      <>
                        <div className="mt-4 flex items-baseline gap-2">
                          <span className="font-mono text-3xl text-slate-900 dark:text-slate-100">
                            {pct(detail.churn.churn_probability, 0)}
                          </span>
                          <Badge variant={RISK_TONE[detail.churn.risk_band] ?? 'neutral'}>
                            {detail.churn.risk_band}
                          </Badge>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-400">
                          churn risk · {detail.churn.model_version} ({detail.churn.algorithm})
                        </p>

                        <h3 className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                          Why
                        </h3>
                        <ul className="mt-2 space-y-1.5">
                          {detail.churn.reason_codes.map((reason, i) => (
                            <li key={i} className="text-xs">
                              <span className="font-medium text-slate-700 dark:text-slate-300">
                                {reasonText(reason.code)}
                              </span>
                              {reason.detail && (
                                <span className="block text-[11px] text-slate-500">{reason.detail}</span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}

                    <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                      {detail.consents.map((consent) => (
                        <span key={consent.channel}
                              className={`rounded-full px-2 py-0.5 text-[10px] ${consent.granted
                                ? 'bg-teal-50 text-teal-700 dark:bg-teal-500/10 dark:text-teal-300'
                                : 'bg-slate-100 text-slate-400 line-through dark:bg-slate-800'}`}>
                          {consent.channel}
                        </span>
                      ))}
                      <span className="ml-auto text-[11px] text-slate-500">
                        {detail.contact_status.contacts_last_7_days} contact(s) this week
                      </span>
                    </div>
                  </Card>
                </Reveal>

                <Reveal delay={0.05}>
                  <Card padding="lg">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Live next-best action
                      </h3>
                      <Button variant="primary" onClick={evaluate} disabled={busy}>
                        {busy ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                              : <Zap className="w-4 h-4 mr-1.5" />}
                        Evaluate
                      </Button>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      Calls the same endpoint a checkout would. Preview mode — no offer is issued
                      and no contact slot is consumed.
                    </p>

                    {decision && (
                      <div className="mt-4">
                        <div className={`rounded-lg p-4 ${decision.action === 'NO_ACTION'
                          ? 'bg-slate-50 dark:bg-slate-800/50'
                          : 'bg-teal-50 dark:bg-teal-500/10'}`}>
                          <p className={`text-lg font-semibold ${decision.action === 'NO_ACTION'
                            ? 'text-slate-700 dark:text-slate-300'
                            : 'text-teal-800 dark:text-teal-300'}`}>
                            {decision.action.replace(/_/g, ' ').toLowerCase()}
                          </p>
                          {decision.eiv_aed && (
                            <p className="mt-0.5 font-mono text-xs text-slate-600 dark:text-slate-400">
                              EIV {aed(decision.eiv_aed)} AED
                              {decision.uplift !== undefined && ` · uplift ${(decision.uplift * 100).toFixed(2)}%`}
                            </p>
                          )}
                          <ul className="mt-2 space-y-1">
                            {decision.reason_codes.map((code) => (
                              <li key={code} className="text-xs text-slate-600 dark:text-slate-400">
                                {reasonText(code)}
                              </li>
                            ))}
                          </ul>
                        </div>

                        {(decision.rejected_actions?.length ?? 0) > 0 && (
                          <details className="mt-3 group">
                            <summary className="cursor-pointer text-xs font-medium text-slate-600 hover:text-teal-700 dark:text-slate-400 dark:hover:text-teal-300">
                              {decision.rejected_actions!.length} alternative(s) considered and refused
                            </summary>
                            <ul className="mt-2 space-y-1.5">
                              {decision.rejected_actions!.map((rejected, i) => (
                                <li key={i} className="rounded-lg bg-slate-50 p-2.5 text-[11px] dark:bg-slate-800/50">
                                  <span className="font-medium text-slate-700 dark:text-slate-300">
                                    {rejected.action.replace(/_/g, ' ').toLowerCase()}
                                    {rejected.discount_pct && rejected.discount_pct !== '0'
                                      ? ` at ${rejected.discount_pct}%` : ''}
                                  </span>
                                  <span className="block text-slate-500">
                                    {rejected.detail ?? reasonText(rejected.reason_code)}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </details>
                        )}

                        {decision.decision_id && (
                          <Link href={`/flywheel/decisions/${decision.decision_id}`}
                                className="mt-3 inline-block text-xs font-medium text-teal-700 hover:underline dark:text-teal-300">
                            Open the full decision trace →
                          </Link>
                        )}
                      </div>
                    )}
                  </Card>
                </Reveal>

                <Reveal delay={0.1}>
                  <Card padding="lg">
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      Recent activity
                    </h3>
                    <ul className="mt-3 space-y-1.5 max-h-64 overflow-y-auto">
                      {detail.events.slice(0, 20).map((event, i) => (
                        <li key={i} className="flex items-baseline justify-between gap-2 text-[11px]">
                          <span className="text-slate-600 dark:text-slate-400">
                            {event.type.replace(/_/g, ' ')}
                            {event.category && ` · ${event.category}`}
                          </span>
                          <span className="shrink-0 font-mono tabular-nums text-slate-500">
                            {event.units > 0 && `${event.units}u `}
                            {new Date(event.at).toLocaleDateString()}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </Card>
                </Reveal>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
