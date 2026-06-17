'use client';

import { useEffect, useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import { Card, Badge, Skeleton, EmptyState } from '@/components/ui';
import { fetchTrend } from '@/lib/api';
import { TrendPoint } from '@/types';
import { CHART, tooltipStyle, tooltipLabelStyle } from './chartTheme';
import { formatCompact, formatCurrency, formatDateShort } from './format';

interface SalesTrendPanelProps {
  days: number;
}

export function SalesTrendPanel({ days }: SalesTrendPanelProps) {
  const [data, setData] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetchTrend(days, true)
      .then((res) => {
        if (!cancelled) setData(res.data ?? []);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  // Transition point between history and the 7-day forecast tail.
  const lastHistoricalIndex = data.findIndex((d) => d.sales === null) - 1;
  const transitionDate = lastHistoricalIndex >= 0 ? data[lastHistoricalIndex]?.date : null;

  const totalHistorical = data.reduce((sum, d) => sum + (d.sales ?? 0), 0);
  const totalForecast = data.reduce((sum, d) => sum + (d.forecast ?? 0), 0);
  const historicalDays = data.filter((d) => d.sales != null).length;

  return (
    <Card variant="glass" padding="md">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-coral-100 text-coral-600">
            <TrendingUp className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink">Sales Trend &amp; Forecast</h3>
            <p className="text-sm text-ink-muted">Last {days} days of revenue with a 7-day projection</p>
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-2">
          <Badge variant="coral" size="sm">Historical</Badge>
          <Badge variant="violet" size="sm">Forecast</Badge>
        </div>
      </div>

      <div className="h-[300px]">
        {loading ? (
          <Skeleton width="100%" height="100%" rounded="lg" />
        ) : error || data.length === 0 ? (
          <EmptyState title="No trend data" description="Historical sales are unavailable for this selection." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="trendSales" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.coral} stopOpacity={0.35} />
                  <stop offset="95%" stopColor={CHART.coral} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="trendForecast" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.violet} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={CHART.violet} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="date" tickFormatter={formatDateShort} stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
              <YAxis stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={tooltipLabelStyle}
                labelFormatter={(label) => formatDateShort(String(label))}
                formatter={(value: number, name: string) => [formatCurrency(value), name === 'sales' ? 'Historical' : 'Forecast']}
              />
              {transitionDate && (
                <ReferenceLine x={transitionDate} stroke={CHART.violet} strokeDasharray="5 5" label={{ value: 'Forecast →', fill: CHART.violet, fontSize: 11, position: 'top' }} />
              )}
              <Area type="monotone" dataKey="sales" stroke={CHART.coral} strokeWidth={2.5} fill="url(#trendSales)" connectNulls={false} dot={false} />
              <Area type="monotone" dataKey="forecast" stroke={CHART.violet} strokeWidth={2.5} strokeDasharray="5 5" fill="url(#trendForecast)" connectNulls={false} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {!loading && !error && data.length > 0 && (
        <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-coral-100">
          <div className="text-center">
            <div className="text-xl font-bold text-ink">{formatCurrency(totalHistorical)}</div>
            <div className="text-xs text-ink-muted">Total Historical</div>
          </div>
          <div className="text-center">
            <div className="text-xl font-bold text-violet-600">{formatCurrency(totalForecast)}</div>
            <div className="text-xs text-ink-muted">7-Day Forecast</div>
          </div>
          <div className="text-center">
            <div className="text-xl font-bold text-teal-600">{formatCurrency(historicalDays > 0 ? totalHistorical / historicalDays : 0)}</div>
            <div className="text-xs text-ink-muted">Daily Average</div>
          </div>
        </div>
      )}
    </Card>
  );
}
