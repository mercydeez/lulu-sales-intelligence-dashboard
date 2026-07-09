'use client';

import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { ShoppingCart, Receipt, Package, TrendingUp, Store } from 'lucide-react';
import {
  Card, StatCard, ChartFrame, Table, TableHead, TableBody, TableRow, Th, Td, Badge, SkeletonText, EmptyState,
  singleLineTick,
} from '@/components/ui';
import {
  CATEGORICAL as SUNSET_COLORS, CHART, CHART_MARGIN, HBAR_MARGIN, Y_AXIS_WIDTH, Y_AXIS_CATEGORY_WIDTH,
  hbarHeight, topNWithOther, tooltipContent as tooltipStyle, tooltipLabelStyle,
} from '@/lib/chart';
import { formatCompact, formatDateShort, axisItemLabel } from '@/components/analytics/format';
import { ReportKpis, ReportDailyPoint, ReportCategory, ReportStore, ReportTopItem } from './types';

const fmtUnits = (v: number) => `${formatCompact(v)} u`;

export function ReportKpiCards({ kpis, loading }: { kpis: ReportKpis | null; loading: boolean }) {
  // Coerce defensively — cached API responses can deliver numbers as strings.
  const growth = Number(kpis?.sales_growth ?? 0);
  const avgBasket = Number(kpis?.avg_basket_size ?? 0);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard variant="gradient" tone="coral" label="Units Sold" value={loading ? '—' : formatCompact(kpis?.total_sales ?? 0)} icon={<ShoppingCart className="w-5 h-5" />} footnote="Selected period" loading={loading} />
      <StatCard tone="teal" label="Transactions" value={loading ? '—' : formatCompact(kpis?.total_transactions ?? 0)} icon={<Receipt className="w-5 h-5" />} loading={loading} />
      <StatCard tone="violet" label="Avg Basket" value={loading ? '—' : `${avgBasket.toFixed(1)} u`} icon={<Package className="w-5 h-5" />} footnote="Units per transaction" loading={loading} />
      <StatCard tone="amber" label="Period Growth" value={loading ? '—' : `${growth >= 0 ? '+' : ''}${growth.toFixed(1)}%`} icon={<TrendingUp className="w-5 h-5" />} trend={growth >= 0 ? 'up' : 'down'} trendLabel="vs prev" loading={loading} />
    </div>
  );
}

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
          <XAxis dataKey="date" tickFormatter={formatDateShort} stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
          <YAxis width={Y_AXIS_WIDTH} stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
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
            {slices.map((entry, i) => <Cell key={entry.category} fill={SUNSET_COLORS[i % SUNSET_COLORS.length]} />)}
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
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
          <YAxis type="category" dataKey="item_name" width={Y_AXIS_CATEGORY_WIDTH} interval={0} tick={singleLineTick(axisItemLabel)} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: 'rgba(15,118,110,0.06)' }} contentStyle={tooltipStyle} formatter={(value: number, _n: string, p: { payload?: ReportTopItem }) => [fmtUnits(value), p.payload?.category ?? 'Units']} />
          <Bar dataKey="total_sales" fill={CHART.teal} radius={[0, 6, 6, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function ReportStoreTable({ data, loading }: { data: ReportStore[]; loading: boolean }) {
  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-line flex items-center gap-2">
        <Store className="w-5 h-5 text-violet-500" />
        <div>
          <h3 className="text-lg font-semibold text-ink">Store Performance</h3>
          <p className="text-sm text-ink-muted mt-0.5">Units and transactions per store</p>
        </div>
      </div>
      {loading ? (
        <div className="p-5"><SkeletonText lines={5} /></div>
      ) : data.length === 0 ? (
        <EmptyState title="No store data" description="No store performance for this selection." />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>#</Th><Th>Store</Th><Th>Location</Th><Th className="text-end">Units</Th><Th className="text-end">Transactions</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.map((s, i) => (
              <TableRow key={s.store_id}>
                <Td><span className="inline-flex w-7 h-7 items-center justify-center rounded-lg sunset-gradient text-white text-xs font-bold">{i + 1}</span></Td>
                <Td className="font-medium">{s.store_name}</Td>
                <Td className="text-ink-soft">{s.location}</Td>
                <Td className="text-end font-semibold">{formatCompact(s.sales)}</Td>
                <Td className="text-end text-ink-soft">{formatCompact(s.transactions)}</Td>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
