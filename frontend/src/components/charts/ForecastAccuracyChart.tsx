'use client';

import { useEffect, useState } from 'react';
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { Target } from 'lucide-react';
import { fetchBacktest } from '@/lib/api';
import { BacktestResult } from '@/types';
import { CHART, CHART_MARGIN, Y_AXIS_WIDTH, gridProps, axisProps, tooltipContent, tooltipLabelStyle } from '@/lib/chart';
import { Reveal } from '@/components/ui';

interface ForecastAccuracyChartProps {
  storeId?: number;
  itemId?: number;
  holdoutDays?: number;
}

export default function ForecastAccuracyChart({
  storeId = 1,
  itemId = 1,
  holdoutDays = 28,
}: ForecastAccuracyChartProps) {
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchBacktest({ store_id: storeId, item_id: itemId, holdout_days: holdoutDays });
        if (!cancelled) setResult(data);
      } catch (err) {
        if (!cancelled) setError('Backtest unavailable — not enough historical data');
        console.error('Error fetching backtest:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [storeId, itemId, holdoutDays]);

  const formatDate = (dateStr: string) =>
    new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

  if (loading) {
    return (
      <div className="bg-surface border border-line rounded-xl shadow-card p-6 h-[400px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl" />
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="bg-surface border border-line rounded-xl shadow-card p-6 h-[400px] flex items-center justify-center">
        <p className="text-ink-muted text-sm">{error ?? 'No backtest data'}</p>
      </div>
    );
  }

  const beatsBaseline =
    result.mape !== null && result.baseline_mape !== null && result.mape <= result.baseline_mape;

  return (
    <Reveal className="bg-surface border border-line rounded-xl shadow-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-ink flex items-center gap-2">
          <Target className="w-5 h-5 text-teal-600" />
          Forecast Accuracy ({result.holdout_days}-day backtest)
        </h3>
        <span className="text-xs px-2 py-1 rounded-full bg-surface-2 border border-line text-ink-muted">
          {result.model_version}
        </span>
      </div>

      {/* MAPE stat row — lower is better; green when the model beats the naive baseline. */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className={`rounded-lg p-3 text-center border ${beatsBaseline ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'}`}>
          <div className="text-2xl font-bold tabular-nums" style={{ color: beatsBaseline ? CHART.emerald : CHART.amber }}>
            {result.mape !== null ? `${result.mape}%` : '—'}
          </div>
          <div className="text-xs text-ink-muted">Model MAPE</div>
        </div>
        <div className="rounded-lg bg-surface-2 border border-line p-3 text-center">
          <div className="text-2xl font-bold text-ink-soft tabular-nums">
            {result.baseline_mape !== null ? `${result.baseline_mape}%` : '—'}
          </div>
          <div className="text-xs text-ink-muted">Seasonal-Naive Baseline</div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={result.points} margin={CHART_MARGIN}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" tickFormatter={formatDate} {...axisProps} minTickGap={20} />
          <YAxis {...axisProps} width={Y_AXIS_WIDTH} />
          <Tooltip
            contentStyle={tooltipContent}
            labelStyle={tooltipLabelStyle}
            labelFormatter={(label) => formatDate(String(label))}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="actual" name="Actual" stroke={CHART.teal} strokeWidth={2.5} dot={false} animationDuration={900} />
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke={CHART.violet}
            strokeWidth={2.5}
            strokeDasharray="5 5"
            dot={false}
            animationDuration={900}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <p className="text-xs text-ink-muted mt-3">
        The model is trained with the last {result.holdout_days} days held out, then scored against what
        actually happened. Lower MAPE is better; the baseline simply repeats the value from 7 days earlier.
      </p>
    </Reveal>
  );
}
