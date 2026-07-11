'use client';

import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { ChartFrame, singleLineTick } from '@/components/ui';
import {
  CATEGORICAL, CHART, CHART_MARGIN, HBAR_MARGIN, Y_AXIS_WIDTH, Y_AXIS_CATEGORY_WIDTH,
  hbarHeight, topNWithOther, tooltipContent as tooltipStyle, tooltipLabelStyle,
} from '@/lib/chart';
import { formatCompact, formatDateShort, axisItemLabel } from '@/components/analytics/format';
import { ReportDailyPoint, ReportCategory, ReportTopItem } from './types';

const fmtUnits = (v: number) => `${formatCompact(v)} u`;

export function ReportTrendPanel({ data, loading }: { data: ReportDailyPoint[]; loading: boolean }) {
  return (
    <ChartFrame title="Daily Units & Transactions" subtitle="Volume across the selected period" height={320} loading={loading} empty={!loading && data.length === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={CHART_MARGIN}>
          <defs>
            <linearGradient id="reportUnits" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={CHART.teal} stopOpacity={0.35} />
              <stop offset="95%" stopColor={CHART.teal} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={formatDateShort} stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis width={Y_AXIS_WIDTH} stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} labelFormatter={(l) => formatDateShort(String(l))}
            formatter={(value: number, name: string) => [formatCompact(value), name === 'sales' ? 'Units' : 'Transactions']} />
          <Area type="monotone" dataKey="sales" stroke={CHART.teal} strokeWidth={2.5} fill="url(#reportUnits)" dot={false} />
          <Area type="monotone" dataKey="transactions" stroke={CHART.violet} strokeWidth={2} fillOpacity={0} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function ReportCategoryPanel({ data, loading }: { data: ReportCategory[]; loading: boolean }) {
  // 7 + "Other": caps the palette cycle and keeps the legend to two rows —
  // the raw category list (20+) repeated colors and overflowed the card.
  const slices = topNWithOther(data, 7, 'percentage', 'category', ['sales']);
  return (
    <ChartFrame title="Units by Category" subtitle="Share of volume by product category" height={320} loading={loading} empty={!loading && data.length === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={slices} cx="50%" cy="50%" innerRadius={62} outerRadius={104} paddingAngle={2} dataKey="percentage" nameKey="category">
            {slices.map((entry, i) => <Cell key={entry.category} fill={CATEGORICAL[i % CATEGORICAL.length]} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} formatter={(_v: number, _n: string, p: { payload?: ReportCategory }) => [fmtUnits(p.payload?.sales ?? 0), p.payload?.category ?? '']} />
          <Legend verticalAlign="bottom" height={36} iconType="circle" formatter={(value) => <span className="text-xs text-ink-soft">{value}</span>} />
        </PieChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function ReportTopItemsPanel({ data, loading }: { data: ReportTopItem[]; loading: boolean }) {
  return (
    <ChartFrame title="Top Items" subtitle="Best-selling items by units" height={hbarHeight(data.length)} loading={loading} empty={!loading && data.length === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={HBAR_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="item_name" width={Y_AXIS_CATEGORY_WIDTH} interval={0} tick={singleLineTick(axisItemLabel)} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: 'rgb(var(--a-teal) / 0.06)' }} contentStyle={tooltipStyle} formatter={(value: number, _n: string, p: { payload?: ReportTopItem }) => [fmtUnits(value), p.payload?.category ?? 'Units']} />
          <Bar dataKey="total_sales" fill={CHART.teal} radius={[0, 6, 6, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
