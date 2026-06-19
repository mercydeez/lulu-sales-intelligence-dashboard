'use client';

import { useEffect, useState, useCallback } from 'react';
import { Brain, RefreshCw, TrendingUp } from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
} from 'recharts';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge, EmptyState, SkeletonText } from '@/components/ui';

interface Leader { model: string; tier: string; accuracy: number | null; mape: number | null; }
interface FeatureImp { feature: string; weight: number; }
interface HeatCell { store_id: number; store_name: string; accuracy: number | null; }
interface Classifier {
  model?: string; labels?: string[]; matrix?: number[][];
  precision?: number; recall?: number; accuracy?: number; f1?: number;
  threshold_units?: number; tested_days?: number;
}
interface Metrics {
  accuracy: number | null; selected_model: string | null; mape: number | null;
  leaderboard: Leader[]; forecast: { date: string; forecast: number }[];
  feature_importance: FeatureImp[]; classifier: Classifier; heatmap: HeatCell[];
  business_impact?: {
    horizon_days?: number;
    projected_units?: number; avg_unit_price_aed?: number; projected_revenue_aed?: number;
    revenue_formula?: string;
    risk_days_caught?: number; revenue_protected_aed?: number; protected_formula?: string;
  };
}

const MODEL_LABEL: Record<string, string> = {
  lightgbm: 'LightGBM (ML)', lstm: 'LSTM (Deep learning)', gru: 'GRU / RNN (Deep learning)',
  cnn: 'CNN (Deep learning)', seasonal_trend: 'Seasonal trend', seasonal_naive: 'Naive baseline',
};

function accColor(a: number | null): string {
  if (a === null) return '#d6d6cf';
  if (a >= 90) return '#639922';
  if (a >= 80) return '#97c459';
  if (a >= 70) return '#ef9f27';
  return '#e24b4a';
}

function health(a: number | null): { label: string; cls: string } {
  if (a === null) return { label: 'no data', cls: 'bg-surface-2 text-ink-muted' };
  if (a >= 90) return { label: 'healthy', cls: 'bg-teal-50 text-teal-700' };
  if (a >= 75) return { label: 'fair', cls: 'bg-amber-50 text-amber-700' };
  return { label: 'needs work', cls: 'bg-coral-50 text-coral-700' };
}

export default function ForecastLabPage() {
  const { authFetch } = useAuth();
  const [data, setData] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'exec' | 'tech'>('exec');

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch('/api/analytics/model-metrics?horizon=14');
      if (res.ok) setData(await res.json());
    } catch (e) {
      console.error('model-metrics failed', e);
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => { fetchMetrics(); }, [fetchMetrics]);

  const acc = data?.accuracy ?? null;
  const h = health(acc);
  const clf = data?.classifier ?? {};
  const hasClf = !!(clf.matrix && clf.matrix.length === 2);
  const bi = data?.business_impact;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Forecast Lab"
          description="How accurate our predictions are, and the models behind them"
          icon={<Brain className="w-5 h-5" />}
          actions={
            <div className="flex items-center gap-2">
              <div className="flex rounded-full border border-line overflow-hidden text-sm">
                <button
                  onClick={() => setView('exec')}
                  className={`px-3 py-1.5 ${view === 'exec' ? 'bg-primary-700 text-white' : 'text-ink-muted'}`}
                >Executive</button>
                <button
                  onClick={() => setView('tech')}
                  className={`px-3 py-1.5 ${view === 'tech' ? 'bg-primary-700 text-white' : 'text-ink-muted'}`}
                >Technical</button>
              </div>
              <Button variant="secondary" size="md" onClick={fetchMetrics} aria-label="Refresh">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          }
        />

        {loading ? (
          <Card variant="solid" padding="lg"><SkeletonText lines={8} /></Card>
        ) : !data ? (
          <Card variant="solid" padding="lg">
            <EmptyState icon={<Brain className="w-6 h-6" />} title="No model metrics yet"
              description="Once there is enough sales history, model accuracy and diagnostics appear here." />
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              <div className="bg-surface border border-line rounded-lg p-5" style={{ borderLeft: '3px solid #0f766e' }}>
                <div className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">Forecast accuracy</div>
                <div className="text-3xl font-semibold text-ink tabular-nums">{acc !== null ? `${acc}%` : '—'}</div>
                <span className={`inline-block mt-1 text-xs px-2 py-0.5 rounded-full ${h.cls}`}>{h.label}</span>
              </div>
              <div className="bg-surface border border-line rounded-lg p-5">
                <div className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">Model in use</div>
                <div className="text-xl font-medium text-ink">{MODEL_LABEL[data.selected_model || ''] || data.selected_model || '—'}</div>
                <div className="text-xs text-ink-muted mt-1">auto-picked by backtest</div>
              </div>
              <div className="bg-surface border border-line rounded-lg p-5">
                <div className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">Error (MAPE)</div>
                <div className="text-3xl font-semibold text-ink tabular-nums">{data.mape !== null ? `${data.mape}%` : '—'}</div>
                <div className="text-xs text-ink-muted mt-1">lower is better</div>
              </div>
            </div>

            {bi && bi.projected_revenue_aed != null && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
                <div className="bg-surface border border-line rounded-lg p-5" style={{ borderLeft: '3px solid #0f766e' }}>
                  <div className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">Projected revenue · next {bi.horizon_days}d</div>
                  <div className="text-3xl font-semibold text-ink tabular-nums">AED {Number(bi.projected_revenue_aed).toLocaleString()}</div>
                  <div className="text-xs text-ink-muted mt-1">How: {bi.revenue_formula}</div>
                </div>
                <div className="bg-surface border border-line rounded-lg p-5" style={{ borderLeft: '3px solid #d97706' }}>
                  <div className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">Revenue exposure caught</div>
                  <div className="text-3xl font-semibold text-ink tabular-nums">AED {Number(bi.revenue_protected_aed).toLocaleString()}</div>
                  <div className="text-xs text-ink-muted mt-1">How: {bi.protected_formula}</div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
              <Card variant="solid" padding="md">
                <h3 className="text-base font-medium text-ink mb-4">Which model won</h3>
                {data.leaderboard.length === 0 ? (
                  <p className="text-sm text-ink-muted">Not enough history to compare models yet.</p>
                ) : (
                  <div className="space-y-3">
                    {data.leaderboard.map((m) => (
                      <div key={m.model}>
                        <div className="flex justify-between text-sm mb-1">
                          <span className="text-ink-soft">{MODEL_LABEL[m.model] || m.model}</span>
                          <span className="text-ink tabular-nums">{m.accuracy ?? '—'}%</span>
                        </div>
                        <div className="h-1.5 bg-surface-2 rounded-full">
                          <div className="h-1.5 rounded-full" style={{ width: `${m.accuracy ?? 0}%`, background: accColor(m.accuracy) }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card variant="solid" padding="md">
                <h3 className="text-base font-medium text-ink mb-4">Accuracy by store</h3>
                {data.heatmap.length === 0 ? (
                  <p className="text-sm text-ink-muted">No per-store breakdown available yet.</p>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {data.heatmap.map((c) => (
                      <div key={c.store_id} className="rounded-md p-2 text-center" style={{ background: accColor(c.accuracy) + '22' }}>
                        <div className="text-[11px] text-ink-soft truncate">{c.store_name}</div>
                        <div className="text-sm font-medium tabular-nums" style={{ color: accColor(c.accuracy) }}>
                          {c.accuracy !== null ? `${c.accuracy}%` : '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>

            <div className="bg-surface-2 rounded-lg p-4 text-sm text-ink-soft leading-relaxed mb-4">
              <span className="font-medium text-ink">What this means: </span>
              Our demand predictions are right about {acc ?? '—'}% of the time, measured against real past sales the
              models never saw. The system automatically uses the best of several models
              ({MODEL_LABEL[data.selected_model || ''] || 'the top performer'} currently). Stores shaded amber or red
              are where forecasts need attention.
            </div>

            {view === 'tech' && (
              <div className="space-y-4">
                <Card variant="solid" padding="md">
                  <h3 className="text-base font-medium text-ink mb-1">Model comparison</h3>
                  <p className="text-xs text-ink-muted mb-3">Every model scored on the same held-out days. Higher accuracy / lower MAPE is better.</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-ink-muted border-b border-line">
                          <th className="py-2 font-medium">Model</th>
                          <th className="py-2 font-medium">Tier</th>
                          <th className="py-2 font-medium text-right">Accuracy</th>
                          <th className="py-2 font-medium text-right">MAPE</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.leaderboard.length === 0 ? (
                          <tr><td colSpan={4} className="py-3 text-ink-muted">Not enough history to compare models yet.</td></tr>
                        ) : data.leaderboard.map((m) => (
                          <tr key={m.model} className="border-b border-line/40">
                            <td className="py-2 text-ink">
                              {MODEL_LABEL[m.model] || m.model}
                              {m.model === data.selected_model && <span className="ml-2 text-xs text-teal-700">● winner</span>}
                            </td>
                            <td className="py-2 text-ink-muted uppercase text-xs">{m.tier}</td>
                            <td className="py-2 text-right tabular-nums">{m.accuracy ?? '—'}%</td>
                            <td className="py-2 text-right tabular-nums text-ink-muted">{m.mape ?? '—'}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>

                <Card variant="solid" padding="md">
                  <h3 className="text-base font-medium text-ink mb-1 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-primary-700" /> Demand forecast (next {data.forecast.length} days)
                  </h3>
                  <p className="text-xs text-ink-muted mb-3">Forward forecast from the winning model.</p>
                  <div style={{ width: '100%', height: 240 }}>
                    <ResponsiveContainer>
                      <LineChart data={data.forecast}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#5f6660' }} />
                        <YAxis tick={{ fontSize: 10, fill: '#5f6660' }} />
                        <Tooltip />
                        <Line type="monotone" dataKey="forecast" stroke="#0f766e" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Card>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <Card variant="solid" padding="md">
                    <h3 className="text-base font-medium text-ink mb-1">What drives demand</h3>
                    <p className="text-xs text-ink-muted mb-3">LightGBM feature importance (% of total).</p>
                    {data.feature_importance.length === 0 ? (
                      <p className="text-sm text-ink-muted">Available after the ML model is installed (rebuild backend).</p>
                    ) : (
                      <div style={{ width: '100%', height: 240 }}>
                        <ResponsiveContainer>
                          <BarChart data={data.feature_importance} layout="vertical" margin={{ left: 24 }}>
                            <XAxis type="number" tick={{ fontSize: 10, fill: '#5f6660' }} />
                            <YAxis type="category" dataKey="feature" width={110} tick={{ fontSize: 10, fill: '#5f6660' }} />
                            <Tooltip />
                            <Bar dataKey="weight" radius={[0, 4, 4, 0]}>
                              {data.feature_importance.map((_, i) => <Cell key={i} fill="#0f766e" />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </Card>

                  <Card variant="solid" padding="md">
                    <h3 className="text-base font-medium text-ink mb-1">Stockout-risk classifier</h3>
                    <p className="text-xs text-ink-muted mb-3">
                      Confusion matrix on held-out days {clf.model ? `(${clf.model})` : ''}.
                    </p>
                    {!hasClf ? (
                      <p className="text-sm text-ink-muted">Available after the ML model is installed (rebuild backend).</p>
                    ) : (
                      <>
                        <div className="grid grid-cols-3 gap-1 text-xs max-w-xs">
                          <div></div>
                          <div className="text-center text-ink-muted">Pred: Normal</div>
                          <div className="text-center text-ink-muted">Pred: Risk</div>
                          <div className="flex items-center text-ink-muted">Actual: Normal</div>
                          <div className="text-center py-3 rounded bg-teal-50 text-teal-700 font-medium tabular-nums">{clf.matrix![0][0]}</div>
                          <div className="text-center py-3 rounded bg-coral-50 text-coral-700 tabular-nums">{clf.matrix![0][1]}</div>
                          <div className="flex items-center text-ink-muted">Actual: Risk</div>
                          <div className="text-center py-3 rounded bg-coral-50 text-coral-700 tabular-nums">{clf.matrix![1][0]}</div>
                          <div className="text-center py-3 rounded bg-teal-50 text-teal-700 font-medium tabular-nums">{clf.matrix![1][1]}</div>
                        </div>
                        <div className="flex flex-wrap gap-2 mt-4">
                          <Badge variant="neutral" size="sm">Precision {clf.precision}%</Badge>
                          <Badge variant="neutral" size="sm">Recall {clf.recall}%</Badge>
                          <Badge variant="neutral" size="sm">Accuracy {clf.accuracy}%</Badge>
                          <Badge variant="neutral" size="sm">F1 {clf.f1}%</Badge>
                        </div>
                        <p className="text-xs text-ink-muted mt-3">
                          Of the days flagged as low-stock risk, {clf.precision}% really were — caught over {clf.tested_days} held-out days.
                        </p>
                      </>
                    )}
                  </Card>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
