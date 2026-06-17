'use client';

import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { AdminDashboard } from './types';

const CHART = { coral: '#ff6b5c', grid: 'rgba(30,27,46,0.08)', axis: '#8b8699' };
const tooltipStyle = { backgroundColor: '#fff', border: '1px solid #f1d9d2', borderRadius: '12px', color: '#1e1b2e' };

interface AdminTrendChartProps {
  dashboard: AdminDashboard | null;
  loading: boolean;
}

const fmtDate = (s: string) => {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

export function AdminTrendChart({ dashboard, loading }: AdminTrendChartProps) {
  const data = dashboard?.daily_trend ?? [];
  return (
    <ChartFrame
      title="Platform Sales Trend"
      subtitle="Units sold per day (recent history)"
      height={280}
      loading={loading}
      empty={!loading && data.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="adminTrend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={CHART.coral} stopOpacity={0.35} />
              <stop offset="95%" stopColor={CHART.coral} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmtDate} stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
          <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => fmtDate(String(l))} />
          <Area type="monotone" dataKey="sales" name="Units" stroke={CHART.coral} strokeWidth={2.5} fill="url(#adminTrend)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
