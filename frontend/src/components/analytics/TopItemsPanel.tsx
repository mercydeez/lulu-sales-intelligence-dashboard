'use client';

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ChartFrame, singleLineTick } from '@/components/ui';
import { useTopItems } from '@/lib/queries/analytics';
import { TopItemPoint } from '@/types';
import { CHART, HBAR_MARGIN, Y_AXIS_CATEGORY_WIDTH, hbarHeight, tooltipContent as tooltipStyle, tooltipLabelStyle } from '@/lib/chart';
import { formatCompact, formatCurrency, axisItemLabel } from './format';

interface TopItemsPanelProps {
  limit?: number;
}

export function TopItemsPanel({ limit = 10 }: TopItemsPanelProps) {
  // Reactive data via TanStack Query (dedup, SWR, background refetch) — replaces
  // the hand-rolled useEffect+useState triad. Transport/auth stay in apiClient.
  const query = useTopItems(limit);
  const data: TopItemPoint[] = query.data ?? [];
  const loading = query.isLoading;
  const error = query.isError;

  const topThree = data.slice(0, 3).map((d) => axisItemLabel(d.item_name)).join(', ');

  return (
    <ChartFrame
      title={`Top ${limit} Items`}
      subtitle="Best-selling items by revenue"
      height={hbarHeight(data.length)}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
      ariaSummary={
        data.length
          ? `Horizontal bar chart of the top ${data.length} items by revenue. Leaders: ${topThree}.`
          : undefined
      }
      tableData={
        data.length
          ? {
              caption: `Top ${data.length} items by revenue`,
              columns: ['Item', 'Category', 'Revenue (AED)'],
              rows: data.map((d) => [axisItemLabel(d.item_name), d.category ?? '—', formatCurrency(d.total_revenue)]),
            }
          : undefined
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={HBAR_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="item_name" width={Y_AXIS_CATEGORY_WIDTH} interval={0} tick={singleLineTick(axisItemLabel)} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: 'rgb(var(--a-teal) / 0.06)' }}
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            formatter={(value: number, _name: string, props: { payload?: TopItemPoint }) => [
              formatCurrency(value),
              props.payload?.category ?? 'Revenue',
            ]}
          />
          <Bar dataKey="total_revenue" fill={CHART.teal} radius={[0, 6, 6, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
