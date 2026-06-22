'use client';

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { fetchStoreDistribution } from '@/lib/api';
import { StoreDistributionPoint } from '@/types';
import { SUNSET_COLORS, CHART, tooltipStyle, tooltipLabelStyle } from './chartTheme';
import { formatCompact, formatCurrency } from './format';

export function StoreDistributionPanel() {
  const [data, setData] = useState<StoreDistributionPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStoreDistribution()
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
  }, []);

  return (
    <ChartFrame
      title="Revenue by Store"
      subtitle="Total revenue contribution per store"
      height={320}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
          <YAxis type="category" dataKey="store_name" stroke={CHART.axis} fontSize={12} width={110} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255, 107, 92, 0.06)' }}
            contentStyle={tooltipStyle}
            labelStyle={tooltipLabelStyle}
            formatter={(value: number) => [formatCurrency(value), 'Revenue']}
          />
          <Bar dataKey="total_revenue" radius={[0, 6, 6, 0]} maxBarSize={26}>
            {data.map((entry, index) => (
              <Cell key={entry.store_id} fill={SUNSET_COLORS[index % SUNSET_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
