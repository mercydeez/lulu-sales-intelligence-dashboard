'use client';

import { useEffect, useState } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { fetchCategoryBreakdown } from '@/lib/api';
import { CategoryBreakdownPoint } from '@/types';
import { SUNSET_COLORS, tooltipStyle } from './chartTheme';
import { formatCurrency } from './format';

export function CategoryDonut() {
  const [data, setData] = useState<CategoryBreakdownPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchCategoryBreakdown()
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
      title="Category Mix"
      subtitle="Share of revenue by product category"
      height={320}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={62}
            outerRadius={104}
            paddingAngle={2}
            dataKey="percentage"
            nameKey="category"
          >
            {data.map((entry, index) => (
              <Cell key={entry.category} fill={SUNSET_COLORS[index % SUNSET_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(_value: number, _name: string, props: { payload?: CategoryBreakdownPoint }) => [
              formatCurrency(props.payload?.total_revenue ?? 0),
              props.payload?.category ?? '',
            ]}
          />
          <Legend
            verticalAlign="bottom"
            height={36}
            iconType="circle"
            formatter={(value) => <span className="text-xs text-ink-soft">{value}</span>}
          />
        </PieChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
