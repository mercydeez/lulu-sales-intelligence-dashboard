'use client';

import { useEffect, useState } from 'react';
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { Target } from 'lucide-react';
import { Card, Select, Badge, Skeleton, EmptyState, StatCard } from '@/components/ui';
import { fetchBacktest, fetchStores, fetchItems } from '@/lib/api';
import { BacktestResult, Store, Item } from '@/types';
import { CHART, tooltipContent as tooltipStyle, tooltipLabelStyle } from '@/lib/chart';
import { formatDateShort } from './format';

interface ForecastPanelProps {
  /** Store to select on first load — typically the user's first accessible store. */
  defaultStoreId?: number;
}

const HOLDOUT_OPTIONS = [14, 28, 56];

export function ForecastPanel({ defaultStoreId = 1 }: ForecastPanelProps) {
  const [stores, setStores] = useState<Store[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [storeId, setStoreId] = useState<number>(defaultStoreId);
  const [itemId, setItemId] = useState<number>(1);
  const [holdoutDays, setHoldoutDays] = useState<number>(28);

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selector options (best-effort — falls back to numeric ids if unavailable).
  useEffect(() => {
    fetchStores().then(setStores).catch(() => setStores([]));
    fetchItems().then(setItems).catch(() => setItems([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchBacktest({ store_id: storeId, item_id: itemId, holdout_days: holdoutDays })
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch(() => {
        if (!cancelled) setError('Backtest unavailable — not enough historical data for this selection.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [storeId, itemId, holdoutDays]);

  const beatsBaseline =
    result?.mape != null && result?.baseline_mape != null && result.mape <= result.baseline_mape;

  return (
    <div className="space-y-6">
      <Card variant="glass" padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-emerald-100 text-emerald-600">
              <Target className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-ink">Forecast Accuracy Backtest</h3>
              <p className="text-sm text-ink-muted">
                The model trains with the last {holdoutDays} days held out, then is scored against what actually
                happened. Lower MAPE is better; the baseline simply repeats the value from 7 days earlier.
              </p>
            </div>
          </div>
          {result?.model_version && <Badge variant="violet" size="sm">{result.model_version}</Badge>}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
          <Select
            label="Store"
            value={storeId}
            onChange={(e) => setStoreId(Number(e.target.value))}
          >
            {stores.length === 0 && <option value={storeId}>Store {storeId}</option>}
            {stores.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </Select>
          <Select
            label="Item"
            value={itemId}
            onChange={(e) => setItemId(Number(e.target.value))}
          >
            {items.length === 0 && <option value={itemId}>Item {itemId}</option>}
            {items.map((i) => (
              <option key={i.id} value={i.id}>{i.name}</option>
            ))}
          </Select>
          <Select
            label="Holdout window"
            value={holdoutDays}
            onChange={(e) => setHoldoutDays(Number(e.target.value))}
          >
            {HOLDOUT_OPTIONS.map((d) => (
              <option key={d} value={d}>{d} days</option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-6">
          <StatCard
            tone={beatsBaseline ? 'teal' : 'amber'}
            label="Model MAPE"
            value={result?.mape != null ? `${result.mape}%` : '—'}
            loading={loading}
            footnote={beatsBaseline ? 'Beats the baseline' : 'Above baseline'}
          />
          <StatCard
            tone="violet"
            label="Seasonal-Naive Baseline"
            value={result?.baseline_mape != null ? `${result.baseline_mape}%` : '—'}
            loading={loading}
            footnote="Repeat value from 7 days ago"
          />
        </div>

        <div className="h-[300px]">
          {loading ? (
            <Skeleton width="100%" height="100%" rounded="lg" />
          ) : error || !result || result.points.length === 0 ? (
            <EmptyState title="No backtest" description={error ?? 'Not enough history for this selection.'} />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={result.points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="date" tickFormatter={formatDateShort} stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} minTickGap={20} />
                <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelStyle={tooltipLabelStyle}
                  labelFormatter={(label) => formatDateShort(String(label))}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="actual" name="Actual" stroke={CHART.coral} strokeWidth={2.5} dot={false} />
                <Line type="monotone" dataKey="predicted" name="Predicted" stroke={CHART.violet} strokeWidth={2.5} strokeDasharray="5 5" dot={false} />
                <Line type="monotone" dataKey="baseline" name="Baseline" stroke={CHART.axis} strokeWidth={1.5} strokeDasharray="2 4" dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </Card>
    </div>
  );
}
