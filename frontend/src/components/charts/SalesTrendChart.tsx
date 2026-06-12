'use client';

import { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine
} from 'recharts';
import { TrendingUp, Calendar, Target } from 'lucide-react';
import { fetchTrend } from '@/lib/api';

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

  // Find the transition point between historical and forecast
  const lastHistoricalIndex = data.findIndex(d => d.sales === null) - 1;
  const lastHistoricalDate = lastHistoricalIndex >= 0 ? data[lastHistoricalIndex]?.date : null;

  if (loading) {
    return (
      <div className="glass rounded-2xl p-6 h-[400px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl"></div>
      </div>
    );
  }

  return (
    <div className="glass rounded-2xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-cyan-500/20">
            <TrendingUp className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Sales Trend & Forecast</h3>
            <p className="text-xs text-slate-400">Historical data with 7-day prediction</p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-cyan-400"></div>
            <span className="text-slate-400">Historical</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-purple-400 border-2 border-dashed border-purple-400"></div>
            <span className="text-slate-400">Forecast</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="forecastGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis 
              dataKey="date" 
              tickFormatter={formatDate}
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
            />
            <YAxis 
              stroke="#64748b"
              fontSize={12}
              tickFormatter={formatNumber}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #475569',
                borderRadius: '12px',
                color: '#f8fafc'
              }}
              labelFormatter={(label) => formatDate(label)}
              formatter={(value: number, name: string) => [
                formatNumber(value),
                name === 'sales' ? 'Historical Sales' : 'Forecasted Sales'
              ]}
            />
            {lastHistoricalDate && (
              <ReferenceLine 
                x={lastHistoricalDate} 
                stroke="#8b5cf6" 
                strokeDasharray="5 5"
                label={{ value: 'Forecast →', fill: '#8b5cf6', fontSize: 12, position: 'top' }}
              />
            )}
            <Line
              type="monotone"
              dataKey="sales"
              stroke="#06b6d4"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: '#06b6d4', stroke: '#0f172a', strokeWidth: 2 }}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="forecast"
              stroke="#8b5cf6"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={false}
              activeDot={{ r: 6, fill: '#8b5cf6', stroke: '#0f172a', strokeWidth: 2 }}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Stats Footer */}
      <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-slate-700/50">
        <div className="text-center">
          <div className="text-2xl font-bold text-white">
            {formatNumber(data.filter(d => d.sales).reduce((sum, d) => sum + (d.sales || 0), 0))}
          </div>
          <div className="text-xs text-slate-400">Total Historical</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-purple-400">
            {formatNumber(data.filter(d => d.forecast).reduce((sum, d) => sum + (d.forecast || 0), 0))}
          </div>
          <div className="text-xs text-slate-400">7-Day Forecast</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-emerald-400">
            {data.length > 0 ? formatNumber(Math.round(data.filter(d => d.sales).reduce((sum, d) => sum + (d.sales || 0), 0) / data.filter(d => d.sales).length)) : 0}
          </div>
          <div className="text-xs text-slate-400">Daily Average</div>
        </div>
      </div>
    </div>
  );
}
