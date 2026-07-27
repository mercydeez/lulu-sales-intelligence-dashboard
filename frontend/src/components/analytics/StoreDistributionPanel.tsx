'use client';

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { ChartFrame, singleLineTick } from '@/components/ui';
import { useStoreDistribution } from '@/lib/queries/analytics';
import { StoreDistributionPoint } from '@/types';
import { CATEGORICAL, CHART, HBAR_MARGIN, Y_AXIS_CATEGORY_WIDTH, tooltipContent as tooltipStyle, tooltipLabelStyle } from '@/lib/chart';
import { formatCompact, formatCurrency, shortStoreLabel } from './format';

export function StoreDistributionPanel() {
  const query = useStoreDistribution();
  const data: StoreDistributionPoint[] = query.data ?? [];
  const loading = query.isLoading;
  const error = query.isError;

  return (
    <ChartFrame
      title="Revenue by Store"
      subtitle="Total revenue contribution per store"
      height={320}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
      ariaSummary={data.length ? `Bar chart of revenue across ${data.length} stores.` : undefined}
      tableData={data.length ? {
        caption: 'Revenue by store',
        columns: ['Store', 'Revenue (AED)'],
        rows: data.map((d) => [shortStoreLabel(d.store_name), formatCurrency(d.total_revenue)]),
      } : undefined}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={HBAR_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="store_name" width={Y_AXIS_CATEGORY_WIDTH} interval={0} tick={singleLineTick(shortStoreLabel)} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: 'rgb(var(--a-teal) / 0.06)' }}
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            formatter={(value: number) => [formatCurrency(value), 'Revenue']}
          />
          <Bar dataKey="total_revenue" radius={[0, 6, 6, 0]} maxBarSize={26}>
            {data.map((entry, index) => (
              <Cell key={entry.store_id} fill={CATEGORICAL[index % CATEGORICAL.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
