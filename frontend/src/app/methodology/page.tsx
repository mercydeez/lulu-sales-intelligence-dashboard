'use client';

import { useEffect, useState } from 'react';
import { PageHeader, Card, Badge, Stagger, RevealItem } from '@/components/ui';
import { LineChart, Moon, CalendarDays, Info } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// E7-2 — the public accuracy publication. Every number here is measured, and the
// ones we could not measure say so instead of being filled in.
interface Methodology {
  status: 'ready' | 'warming';
  reason?: string;
  forecasting_version?: string;
  baseline_model?: string;
  baseline_mape?: number | null;
  baseline_wape?: number | null;
  selected_model?: string | null;
  selected_model_mape?: number | null;
  selected_model_wape?: number | null;
  wape_improvement_vs_baseline_pct?: number | null;
  ramadan_accuracy?: number | null;
  ramadan_mape?: number | null;
  ramadan_wape?: number | null;
  ramadan_eval_days?: number;
  ramadan_accuracy_reason?: string;
  calendar_feature_summary?: {
    uses_uae_calendar?: boolean;
    uses_weather_features?: boolean;
    lunar_dates_approximate?: boolean;
  };
  methodology_note?: string;
  dataset?: string;
  checked_at?: string;
}

const RAMADAN_REASON: Record<string, string> = {
  no_ramadan_dates_in_backtest_window:
    'No Ramadan days fell inside the back-test window, so we have not measured Ramadan-window accuracy on this dataset. We will not extrapolate a seasonal claim from a season we did not measure.',
  no_backtest_window: 'There is no back-test window yet on this dataset.',
  not_computed: 'Not yet computed on this dataset.',
  insufficient_history: 'Not enough history on this dataset to measure a Ramadan window.',
};

function Metric({ label, value, suffix = '%', hint }: {
  label: string; value: number | null | undefined; suffix?: string; hint?: string;
}) {
  return (
    <div className="rounded-lg bg-surface-2/60 p-4">
      <div className="text-[11px] font-mono uppercase tracking-wide text-ink-muted">{label}</div>
      <div className="text-2xl font-semibold text-ink tabular-nums">
        {value === null || value === undefined ? '—' : `${value}${suffix}`}
      </div>
      {hint && <div className="text-[11px] text-ink-muted mt-1">{hint}</div>}
    </div>
  );
}

export default function MethodologyPage() {
  const [data, setData] = useState<Methodology | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/monitoring/forecast-methodology`, { cache: 'no-store' });
        if (!alive) return;
        if (!res.ok) { setFailed(true); return; }
        setData(await res.json());
      } catch {
        if (alive) setFailed(true);
      }
    })();
    return () => { alive = false; };
  }, []);

  const cal = data?.calendar_feature_summary;
  const ramadanMeasured = data?.ramadan_accuracy !== null && data?.ramadan_accuracy !== undefined;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Forecast methodology & accuracy"
          description="How we forecast UAE retail demand, what we score ourselves against, and the error rate we actually measure."
          icon={<LineChart className="w-5 h-5" />}
        />

        <div className="rounded-xl bg-teal-50 border border-teal-200 p-3 mb-6 text-sm text-teal-900">
          We publish our error rate, not a claim. Every figure below is measured against
          held-out actuals; anything we have not measured is shown as “—” with the reason.
        </div>

        <Stagger className="space-y-4">
          {failed && (
            <RevealItem>
              <Card padding="lg">
                <p className="text-sm text-ink-soft">
                  The accuracy service is unreachable right now. Rather than show a stale number, we show nothing.
                </p>
              </Card>
            </RevealItem>
          )}

          {data?.status === 'warming' && (
            <RevealItem>
              <Card padding="lg">
                <div className="flex items-center gap-2 mb-2">
                  <Info className="w-4 h-4 text-teal-600" />
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Warming up</h3>
                </div>
                <p className="text-sm text-ink-soft">{data.reason}</p>
              </Card>
            </RevealItem>
          )}

          {data?.status === 'ready' && (
            <>
              <RevealItem>
                <Card padding="lg">
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">
                      Measured error
                    </h3>
                    <Badge variant="neutral">{data.forecasting_version}</Badge>
                  </div>
                  <p className="text-sm text-ink-soft mb-4">
                    We score the selected model against a <strong>seasonal-naive</strong> baseline —
                    “the same weekday, a week ago”. If a model cannot beat that, it has earned nothing.
                    Lower error is better.
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <Metric label="Model WAPE" value={data.selected_model_wape} hint="weighted abs. % error" />
                    <Metric label="Baseline WAPE" value={data.baseline_wape} hint={data.baseline_model} />
                    <Metric label="Model MAPE" value={data.selected_model_mape} />
                    <Metric
                      label="Improvement"
                      value={data.wape_improvement_vs_baseline_pct}
                      hint="error reduction vs baseline"
                    />
                  </div>
                </Card>
              </RevealItem>

              <RevealItem>
                <Card padding="lg">
                  <div className="flex items-center gap-2 mb-3">
                    <Moon className="w-4 h-4 text-teal-600" />
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">
                      Ramadan-window accuracy
                    </h3>
                  </div>

                  {ramadanMeasured ? (
                    <>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
                        <Metric label="Ramadan accuracy" value={data.ramadan_accuracy} />
                        <Metric label="Ramadan WAPE" value={data.ramadan_wape} />
                        <Metric label="Days evaluated" value={data.ramadan_eval_days} suffix="" />
                      </div>
                      <p className="text-xs text-ink-muted">
                        Measured only on days that actually fell inside Ramadan.
                      </p>
                    </>
                  ) : (
                    <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-900">
                      <strong>Not measured on this dataset.</strong>{' '}
                      {RAMADAN_REASON[data.ramadan_accuracy_reason ?? 'not_computed'] ??
                        'Ramadan-window accuracy has not been measured.'}
                    </div>
                  )}
                </Card>
              </RevealItem>

              <RevealItem>
                <Card padding="lg">
                  <div className="flex items-center gap-2 mb-3">
                    <CalendarDays className="w-4 h-4 text-teal-600" />
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">
                      Features & caveats
                    </h3>
                  </div>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {cal?.uses_uae_calendar && (
                      <Badge variant="success">UAE retail calendar (Ramadan / Eid / DSF)</Badge>
                    )}
                    <Badge variant="neutral">
                      Weather features: {cal?.uses_weather_features ? 'on' : 'neutral'}
                    </Badge>
                    {cal?.lunar_dates_approximate && (
                      <Badge variant="amber">Lunar dates approximate</Badge>
                    )}
                    <Badge variant="neutral">No LLM in the forecast path</Badge>
                  </div>
                  <p className="text-sm text-ink-soft">{data.methodology_note}</p>
                </Card>
              </RevealItem>

              <RevealItem>
                <Card padding="lg">
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-2">
                    What this page is, and is not
                  </h3>
                  <ul className="text-sm text-ink-soft space-y-1.5 list-disc ms-5">
                    <li>Figures are computed on the <strong>{data.dataset}</strong> — not on any customer&apos;s data.</li>
                    <li>No customer revenue, store, product or volume appears here, by construction.</li>
                    <li>
                      A per-tenant accuracy report is available inside the product (Forecast Lab), scoped to
                      that tenant&apos;s own data.
                    </li>
                    <li>Lunar dates are approximate until confirmed against official UAE sources.</li>
                  </ul>
                  {data.checked_at && (
                    <p className="text-xs text-ink-faint mt-3">
                      Reported live from the running system · {new Date(data.checked_at).toLocaleString()}
                    </p>
                  )}
                </Card>
              </RevealItem>
            </>
          )}
        </Stagger>
      </div>
    </main>
  );
}
