'use client';

import { useEffect, useState, useCallback } from 'react';
import { Brain, RefreshCw, TrendingUp } from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
  ComposedChart, Area, Legend, ReferenceLine,
} from 'recharts';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge, EmptyState, SkeletonText } from '@/components/ui';

interface Leader { model: string; tier: string; accuracy: number | null; mape: number | null; }
interface FeatureImp { feature: string; weight: number; }
interface HeatCell { store_id: number; store_name: string; accuracy: number | null; }
interface Classifier {
  model?: string; labels?: string[]; matrix?: number[][];
  precision?: number; recall?: number; accuracy?: number; f1?: number;
  threshold?: number; threshold_units?: number; tested_days?: number;
  roc?: { fpr: number; tpr: number }[]; roc_auc?: number | null;
  pr?: { recall: number; precision: number }[]; average_precision?: number | null;
}
interface Metrics {
  status?: string;
  accuracy: number | null; selected_model: string | null; mape: number | null;
  leaderboard: Leader[];
  forecast: { date: string; forecast: number; lower?: number; upper?: number }[];
  backtest: { date: string; actual: number; predicted: number }[];
  interval_pct?: number | null;
  accuracy_trend: { date: string; accuracy: number }[];
  category_heatmap: { store_id: number; store_name: string; category: string; accuracy: number | null }[];
  item_accuracy: { item_id: number; item_name: string; category: string; accuracy: number | null }[];
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
  cnn: 'CNN (Deep learning)', tcn: 'TCN (Deep learning)', transformer: 'Transformer (Deep learning)',
  nbeats: 'N-BEATS (Deep learning)', seasonal_trend: 'Seasonal trend', seasonal_naive: 'Naive baseline',
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
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

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

  // Models train off the request path; a cold scope returns status "warming".
  // Poll until the background trainer has cached the result.
  const warming = data?.status === 'warming';
  useEffect(() => {
    if (!warming) return;
    const t = setTimeout(fetchMetrics, 8000);
    return () => clearTimeout(t);
  }, [warming, data, fetchMetrics]);

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
        ) : warming ? (
          <Card variant="solid" padding="lg">
            <EmptyState
              icon={<RefreshCw className="w-6 h-6 animate-spin" />}
              title="Training models…"
              description="Forecast models are training in the background. This page refreshes automatically when they're ready (usually under a minute)." />
          </Card>
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

                {data.backtest.length > 0 && (
                  <Card variant="solid" padding="md">
                    <h3 className="text-base font-medium text-ink mb-1">Forecast vs actual</h3>
                    <p className="text-xs text-ink-muted mb-3">
                      The winning model&apos;s predictions on the last {data.backtest.length} days it never saw,
                      against what really happened. The closer the lines, the more we can trust the forward forecast.
                    </p>
                    <div style={{ width: '100%', height: 240 }}>
                      <ResponsiveContainer>
                        <LineChart data={data.backtest}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#5f6660' }} />
                          <YAxis tick={{ fontSize: 10, fill: '#5f6660' }} />
                          <Tooltip />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Line type="monotone" dataKey="actual" name="Actual" stroke="#0f766e" strokeWidth={2} dot={false} />
                          <Line type="monotone" dataKey="predicted" name="Predicted" stroke="#d97706" strokeWidth={2} strokeDasharray="5 4" dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </Card>
                )}

                <Card variant="solid" padding="md">
                  <h3 className="text-base font-medium text-ink mb-1 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-primary-700" /> Demand forecast (next {data.forecast.length} days)
                  </h3>
                  <p className="text-xs text-ink-muted mb-3">
                    Forward forecast from the winning model
                    {data.interval_pct ? `, shaded with the ${data.interval_pct}% prediction interval (from backtest error).` : '.'}
                  </p>
                  <div style={{ width: '100%', height: 240 }}>
                    <ResponsiveContainer>
                      <ComposedChart data={data.forecast.map((p) => ({ ...p, band: [p.lower ?? p.forecast, p.upper ?? p.forecast] }))}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#5f6660' }} />
                        <YAxis tick={{ fontSize: 10, fill: '#5f6660' }} />
                        <Tooltip />
                        <Area type="monotone" dataKey="band" name="Interval" stroke="none" fill="#0f766e" fillOpacity={0.12} />
                        <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#0f766e" strokeWidth={2} dot={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </Card>

                {data.accuracy_trend.length >= 2 && (() => {
                  const trend = data.accuracy_trend;
                  const delta = trend[trend.length - 1].accuracy - trend[0].accuracy;
                  const dir = delta > 2 ? 'improving' : delta < -2 ? 'declining' : 'stable';
                  const dirCls = dir === 'improving'
                    ? 'bg-teal-50 text-teal-700'
                    : dir === 'declining' ? 'bg-coral-50 text-coral-700' : 'bg-surface-2 text-ink-muted';
                  return (
                    <Card variant="solid" padding="md">
                      <h3 className="text-base font-medium text-ink mb-1 flex items-center gap-2">
                        Accuracy over time
                        <span className={`text-xs px-2 py-0.5 rounded-full ${dirCls}`}>
                          {dir} {delta > 0 ? '+' : ''}{delta.toFixed(1)}pts
                        </span>
                      </h3>
                      <p className="text-xs text-ink-muted mb-3">
                        The current model ({MODEL_LABEL[data.selected_model || ''] || data.selected_model})
                        scored on successive held-out windows — is accuracy holding up?
                      </p>
                      <div style={{ width: '100%', height: 220 }}>
                        <ResponsiveContainer>
                          <LineChart data={trend}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#5f6660' }} />
                            <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#5f6660' }} />
                            <Tooltip />
                            <Line type="monotone" dataKey="accuracy" name="Accuracy %" stroke="#0f766e" strokeWidth={2} dot={{ r: 3 }} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </Card>
                  );
                })()}

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
                      Confusion matrix on held-out days {clf.model ? `(${clf.model})` : ''}
                      {clf.threshold != null ? `, at the F1-tuned threshold ${clf.threshold}` : ''}.
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

                {(clf.roc?.length || clf.pr?.length) ? (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {clf.roc && clf.roc.length > 0 && (
                      <Card variant="solid" padding="md">
                        <h3 className="text-base font-medium text-ink mb-1 flex items-center gap-2">
                          ROC curve
                          {clf.roc_auc != null && (
                            <Badge variant="neutral" size="sm">AUC {clf.roc_auc}</Badge>
                          )}
                        </h3>
                        <p className="text-xs text-ink-muted mb-3">
                          True-positive vs false-positive rate across thresholds. Closer to the top-left is better; the dashed line is random.
                        </p>
                        <div style={{ width: '100%', height: 220 }}>
                          <ResponsiveContainer>
                            <LineChart data={clf.roc}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                              <XAxis type="number" dataKey="fpr" domain={[0, 1]} tick={{ fontSize: 10, fill: '#5f6660' }} label={{ value: 'FPR', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#5f6660' }} />
                              <YAxis type="number" dataKey="tpr" domain={[0, 1]} tick={{ fontSize: 10, fill: '#5f6660' }} />
                              <Tooltip />
                              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#c4c4bc" strokeDasharray="4 4" />
                              <Line type="monotone" dataKey="tpr" stroke="#0f766e" strokeWidth={2} dot={false} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </Card>
                    )}

                    {clf.pr && clf.pr.length > 0 && (
                      <Card variant="solid" padding="md">
                        <h3 className="text-base font-medium text-ink mb-1 flex items-center gap-2">
                          Precision-recall curve
                          {clf.average_precision != null && (
                            <Badge variant="neutral" size="sm">AP {clf.average_precision}</Badge>
                          )}
                        </h3>
                        <p className="text-xs text-ink-muted mb-3">
                          Precision vs recall across thresholds — the honest view when risk days are rare.
                        </p>
                        <div style={{ width: '100%', height: 220 }}>
                          <ResponsiveContainer>
                            <LineChart data={clf.pr}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#ececE6" />
                              <XAxis type="number" dataKey="recall" domain={[0, 1]} tick={{ fontSize: 10, fill: '#5f6660' }} label={{ value: 'Recall', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#5f6660' }} />
                              <YAxis type="number" dataKey="precision" domain={[0, 1]} tick={{ fontSize: 10, fill: '#5f6660' }} />
                              <Tooltip />
                              <Line type="monotone" dataKey="precision" stroke="#d97706" strokeWidth={2} dot={false} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </Card>
                    )}
                  </div>
                ) : null}

                {data.category_heatmap.length > 0 && (() => {
                  const cats = Array.from(new Set(data.category_heatmap.map((c) => c.category))).sort();
                  const stores = Array.from(
                    new Map(data.category_heatmap.map((c) => [c.store_id, c.store_name])).entries()
                  ).sort((a, b) => a[0] - b[0]);
                  const cell = new Map(
                    data.category_heatmap.map((c) => [`${c.store_id}|${c.category}`, c.accuracy])
                  );
                  const drillItems = selectedCategory
                    ? data.item_accuracy
                        .filter((it) => it.category === selectedCategory)
                        .sort((a, b) => (b.accuracy ?? -1) - (a.accuracy ?? -1))
                    : [];
                  return (
                    <Card variant="solid" padding="md">
                      <h3 className="text-base font-medium text-ink mb-1">Accuracy by store × category</h3>
                      <p className="text-xs text-ink-muted mb-3">
                        Forecast accuracy for each category in each store. Click a category to see the items behind it.
                      </p>
                      <div className="overflow-x-auto">
                        <table className="text-xs border-separate" style={{ borderSpacing: 2 }}>
                          <thead>
                            <tr>
                              <th className="text-left font-medium text-ink-muted px-2 sticky left-0 bg-surface">Category</th>
                              {stores.map(([sid, sname]) => (
                                <th key={sid} className="font-medium text-ink-muted px-1 whitespace-nowrap" title={sname}>
                                  {sname.replace(/^Lulu\s+/i, '').slice(0, 10)}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {cats.map((cat) => (
                              <tr key={cat}>
                                <td className="px-2 sticky left-0 bg-surface">
                                  <button
                                    onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                                    className={`text-left hover:underline ${selectedCategory === cat ? 'text-primary-700 font-medium' : 'text-ink-soft'}`}
                                  >
                                    {cat}
                                  </button>
                                </td>
                                {stores.map(([sid]) => {
                                  const a = cell.get(`${sid}|${cat}`) ?? null;
                                  return (
                                    <td key={sid} className="text-center rounded tabular-nums"
                                        style={{ background: accColor(a) + '33', color: a !== null ? '#3a3a34' : '#b6b6ae', minWidth: 36, padding: '6px 2px' }}
                                        title={`${cat} · ${a !== null ? a + '%' : 'no data'}`}>
                                      {a !== null ? a : '—'}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {selectedCategory && (
                        <div className="mt-4 border-t border-line pt-3">
                          <h4 className="text-sm font-medium text-ink mb-2">Items in {selectedCategory}</h4>
                          {drillItems.length === 0 ? (
                            <p className="text-xs text-ink-muted">No per-item accuracy available.</p>
                          ) : (
                            <div className="space-y-2 max-w-md">
                              {drillItems.map((it) => (
                                <div key={it.item_id}>
                                  <div className="flex justify-between text-xs mb-0.5">
                                    <span className="text-ink-soft">{it.item_name}</span>
                                    <span className="text-ink tabular-nums">{it.accuracy ?? '—'}%</span>
                                  </div>
                                  <div className="h-1.5 bg-surface-2 rounded-full">
                                    <div className="h-1.5 rounded-full" style={{ width: `${it.accuracy ?? 0}%`, background: accColor(it.accuracy) }} />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </Card>
                  );
                })()}
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
