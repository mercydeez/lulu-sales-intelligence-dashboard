'use client';

import { useEffect, useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { TrendingUp } from 'lucide-react';
import { fetchTrend } from '@/lib/api';
import { CHART, gridProps, axisProps, tooltipContent, tooltipLabelStyle } from '@/lib/chart';
import { Reveal } from '@/components/ui';

interface TrendDataPoint {
  date: string;
  sales: number | null;
  forecast: number | null;
}

interface SalesTrendChartProps {
  days?: number;
}

export default function SalesTrendChart({ days = 30 }: SalesTrendChartProps) {
  const [data, setData] = useState<TrendDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const result = await fetchTrend(days, true);
        setData(result.data);
      } catch (error) {
        console.error('Error fetching trend data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [days]);

  const formatDate = (dateStr: string) => {
    if (!mounted) return dateStr;
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toString();
  };

  // Find the transition point between historical and forecast.
  const lastHistoricalIndex = data.findIndex(d => d.sales === null) - 1;
  const lastHistoricalDate = lastHistoricalIndex >= 0 ? data[lastHistoricalIndex]?.date : null;

  if (loading) {
    return (
      <div className="bg-surface border border-line rounded-2xl shadow-card p-6 h-[400px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl" />
      </div>
    );
  }

  const historical = data.filter(d => d.sales);
  const totalHistorical = historical.reduce((sum, d) => sum + (d.sales || 0), 0);
  const totalForecast = data.filter(d => d.forecast).reduce((sum, d) => sum + (d.forecast || 0), 0);
  const dailyAvg = historical.length > 0 ? Math.round(totalHistorical / historical.length) : 0;

  return (
    <Reveal className="bg-surface border border-line rounded-2xl shadow-card p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-50 ring-1 ring-teal-100">
            <TrendingUp className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink">Sales Trend &amp; Forecast</h3>
            <p className="text-xs text-ink-muted">Historical units with 7-day prediction</p>
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-3 h-0.5 rounded-full" style={{ background: CHART.teal }} />
            <span className="text-ink-muted">Historical</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-0.5 rounded-full border-t-2 border-dashed" style={{ borderColor: CHART.violet }} />
            <span className="text-ink-muted">Forecast</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="trendSalesFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={CHART.teal} stopOpacity={0.28} />
                <stop offset="95%" stopColor={CHART.teal} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="trendForecastFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={CHART.violet} stopOpacity={0.2} />
                <stop offset="95%" stopColor={CHART.violet} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="date" tickFormatter={formatDate} {...axisProps} minTickGap={24} />
            <YAxis tickFormatter={formatNumber} {...axisProps} width={44} />
            <Tooltip
              contentStyle={tooltipContent}
              labelStyle={tooltipLabelStyle}
              labelFormatter={(label) => formatDate(String(label))}
              formatter={(value: number, name: string) => [
                `${formatNumber(value)} units`,
                name === 'sales' ? 'Historical' : 'Forecast',
              ]}
            />
            {lastHistoricalDate && (
              <ReferenceLine
                x={lastHistoricalDate}
                stroke={CHART.violet}
                strokeDasharray="5 5"
                label={{ value: 'Forecast →', fill: CHART.violet, fontSize: 11, position: 'top' }}
              />
            )}
            <Area
              type="monotone"
              dataKey="sales"
              stroke={CHART.teal}
              strokeWidth={2.5}
              fill="url(#trendSalesFill)"
              dot={false}
              activeDot={{ r: 5, fill: CHART.teal, stroke: '#ffffff', strokeWidth: 2 }}
              connectNulls={false}
              animationDuration={900}
            />
            <Area
              type="monotone"
              dataKey="forecast"
              stroke={CHART.violet}
              strokeWidth={2.5}
              strokeDasharray="5 5"
              fill="url(#trendForecastFill)"
              dot={false}
              activeDot={{ r: 5, fill: CHART.violet, stroke: '#ffffff', strokeWidth: 2 }}
              connectNulls={false}
              animationDuration={900}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Stats Footer — all values are UNITS (volume), never AED. */}
      <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-line">
        <div className="text-center">
          <div className="text-2xl font-bold text-ink tabular-nums">{formatNumber(totalHistorical)}</div>
          <div className="text-xs text-ink-muted">Total Historical</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold tabular-nums" style={{ color: CHART.violet }}>{formatNumber(totalForecast)}</div>
          <div className="text-xs text-ink-muted">7-Day Forecast</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold tabular-nums" style={{ color: CHART.teal }}>{formatNumber(dailyAvg)}</div>
          <div className="text-xs text-ink-muted">Daily Average</div>
        </div>
      </div>
    </Reveal>
  );
}
