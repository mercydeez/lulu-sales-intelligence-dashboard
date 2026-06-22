'use client';

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { fetchTopItems } from '@/lib/api';
import { TopItemPoint } from '@/types';
import { CHART, tooltipStyle, tooltipLabelStyle } from './chartTheme';
import { formatCompact, formatCurrency, shortItemLabel } from './format';

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
      height={360}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
          <YAxis type="category" dataKey="item_name" stroke={CHART.axis} fontSize={11} width={140} interval={0} tickFormatter={shortItemLabel} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(45, 212, 191, 0.06)' }}
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
