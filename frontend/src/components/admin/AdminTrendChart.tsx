'use client';

import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { CHART, CHART_MARGIN, Y_AXIS_WIDTH, gridProps, axisProps, tooltipContent, tooltipLabelStyle } from '@/lib/chart';
import { AdminDashboard } from './types';

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
        <AreaChart data={data} margin={CHART_MARGIN}>
          <defs>
            <linearGradient id="adminTrend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={CHART.teal} stopOpacity={0.35} />
              <stop offset="95%" stopColor={CHART.teal} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="date" tickFormatter={fmtDate} {...axisProps} fontSize={12} minTickGap={24} />
          <YAxis {...axisProps} width={Y_AXIS_WIDTH} fontSize={12} />
          <Tooltip contentStyle={tooltipContent} labelStyle={tooltipLabelStyle} labelFormatter={(l) => fmtDate(String(l))} />
          <Area type="monotone" dataKey="sales" name="Units" stroke={CHART.teal} strokeWidth={2.5} fill="url(#adminTrend)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
