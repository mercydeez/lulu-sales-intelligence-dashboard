'use client';

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { ChartFrame } from '@/components/ui';
import { useCategoryBreakdown } from '@/lib/queries/analytics';
import { CategoryBreakdownPoint } from '@/types';
import { CATEGORICAL, topNWithOther, tooltipContent as tooltipStyle } from '@/lib/chart';
import { formatCurrency } from './format';

export function CategoryDonut() {
  const query = useCategoryBreakdown();
  const data: CategoryBreakdownPoint[] = query.data ?? [];
  const loading = query.isLoading;
  const error = query.isError;

  // 7 + "Other": one full palette cycle — 20+ raw categories repeat the 8-hue
  // palette and their legend overflows (clips) the card bottom.
  const slices = topNWithOther(data, 7, 'percentage', 'category', ['total_revenue']);

  return (
    <ChartFrame
      title="Category Mix"
      subtitle="Share of revenue by product category"
      height={320}
      loading={loading}
      empty={!loading && (error || data.length === 0)}
      ariaSummary={data.length ? `Donut chart of revenue share across ${data.length} product categories.` : undefined}
      tableData={data.length ? {
        caption: 'Revenue share by category',
        columns: ['Category', 'Share', 'Revenue (AED)'],
        rows: data.map((d) => [d.category, `${Math.round(d.percentage)}%`, formatCurrency(d.total_revenue)]),
      } : undefined}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={slices}
            cx="50%"
            cy="50%"
            innerRadius={62}
            outerRadius={104}
            paddingAngle={2}
            dataKey="percentage"
            nameKey="category"
          >
            {data.map((entry, index) => (
              <Cell key={entry.category} fill={CATEGORICAL[index % CATEGORICAL.length]} />
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
