'use client';

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ChartFrame, singleLineTick } from '@/components/ui';
import { fetchTopItems } from '@/lib/api';
import { TopItemPoint } from '@/types';
import { CHART, HBAR_MARGIN, Y_AXIS_CATEGORY_WIDTH, hbarHeight, tooltipContent as tooltipStyle, tooltipLabelStyle } from '@/lib/chart';
import { formatCompact, formatCurrency, axisItemLabel } from './format';

interface TopItemsPanelProps {
  limit?: number;
}

export function TopItemsPanel({ limit = 10 }: TopItemsPanelProps) {
  const [data, setData] = useState<TopItemPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchTopItems(limit)
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
  }, [limit]);

  return (
    <ChartFrame
      title={`Top ${limit} Items`}
      subtitle="Best-selling items by revenue"
      height={hbarHeight(data.length)}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
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
