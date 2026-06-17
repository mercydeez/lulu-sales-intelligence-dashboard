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
      <div className="glass rounded-xl p-6 h-[400px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl"></div>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="glass rounded-xl p-6 h-[400px] flex items-center justify-center">
        <p className="text-slate-400 text-sm">{error ?? 'No backtest data'}</p>
      </div>
    );
  }

  const beatsBaseline =
    result.mape !== null && result.baseline_mape !== null && result.mape <= result.baseline_mape;

  return (
    <div className="glass rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <Target className="w-5 h-5 text-emerald-500" />
          Forecast Accuracy ({result.holdout_days}-day backtest)
        </h3>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-800 border border-slate-600 text-slate-400">
          {result.model_version}
        </span>
      </div>

      {/* MAPE stat row */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="rounded-lg bg-slate-800/60 p-3 text-center">
          <div className={`text-2xl font-bold ${beatsBaseline ? 'text-emerald-400' : 'text-amber-400'}`}>
            {result.mape !== null ? `${result.mape}%` : '—'}
          </div>
          <div className="text-xs text-slate-400">Model MAPE</div>
        </div>
        <div className="rounded-lg bg-slate-800/60 p-3 text-center">
          <div className="text-2xl font-bold text-slate-300">
            {result.baseline_mape !== null ? `${result.baseline_mape}%` : '—'}
          </div>
          <div className="text-xs text-slate-400">Seasonal-Naive Baseline</div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={result.points}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tickFormatter={formatDate} stroke="#94a3b8" fontSize={12} />
          <YAxis stroke="#94a3b8" fontSize={12} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
            labelFormatter={(label) => formatDate(String(label))}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="actual" name="Actual" stroke="#06b6d4" strokeWidth={2} dot={false} />
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke="#8b5cf6"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <p className="text-xs text-slate-500 mt-3">
        The model is trained with the last {result.holdout_days} days held out, then scored against what
        actually happened. Lower MAPE is better; the baseline simply repeats the value from 7 days earlier.
      </p>
    </div>
  );
}
