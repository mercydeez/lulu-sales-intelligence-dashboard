'use client';

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { ChartFrame, singleLineTick } from '@/components/ui';
import { fetchStoreDistribution } from '@/lib/api';
import { StoreDistributionPoint } from '@/types';
import { CATEGORICAL, CHART, HBAR_MARGIN, Y_AXIS_CATEGORY_WIDTH, tooltipContent as tooltipStyle, tooltipLabelStyle } from '@/lib/chart';
import { formatCompact, formatCurrency, shortStoreLabel } from './format';

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
        <BarChart data={data} layout="vertical" margin={HBAR_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
          <XAxis type="number" stroke={CHART.axis} fontSize={12} tickFormatter={formatCompact} tickLine={false} axisLine={{ stroke: CHART.grid }} />
          <YAxis type="category" dataKey="store_name" width={Y_AXIS_CATEGORY_WIDTH} interval={0} tick={singleLineTick(shortStoreLabel)} tickLine={false} axisLine={false} />
          <Tooltip
            cursor={{ fill: 'rgba(255, 107, 92, 0.06)' }}
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
