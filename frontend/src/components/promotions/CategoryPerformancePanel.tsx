'use client';

import { TrendingUp, TrendingDown } from 'lucide-react';
import { Card, EmptyState, SkeletonText } from '@/components/ui';
import { CategoryPerformance } from './types';
import { formatCurrency } from './format';

interface CategoryPerformancePanelProps {
  categories: CategoryPerformance[];
  loading: boolean;
}

export function CategoryPerformancePanel({ categories, loading }: CategoryPerformancePanelProps) {
  const maxRevenue = Math.max(1, ...categories.map((c) => c.total_revenue));

  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-coral-100">
        <h2 className="text-lg font-semibold text-ink">Category Performance</h2>
        <p className="text-sm text-ink-muted mt-0.5">Revenue and momentum by category</p>
      </div>

      {loading ? (
        <div className="p-5">
          <SkeletonText lines={6} />
        </div>
      ) : categories.length === 0 ? (
        <EmptyState title="No category data" description="Sales-derived category performance is unavailable." />
      ) : (
        <div className="divide-y divide-coral-100/70">
          {categories.map((cat) => {
            const up = cat.growth_rate >= 0;
            return (
              <div key={cat.category} className="p-4 hover:bg-coral-50/40 transition-colors">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-medium text-ink">{cat.category}</span>
                  <span className={`flex items-center gap-1 text-sm font-medium ${up ? 'text-emerald-600' : 'text-rose-600'}`}>
                    {up ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                    {Math.abs(cat.growth_rate).toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between text-sm text-ink-muted mb-2">
                  <span>{formatCurrency(cat.total_revenue)}</span>
                  <span>~{cat.avg_discount.toFixed(0)}% avg discount</span>
                </div>
                <div className="h-1.5 bg-coral-100 rounded-full overflow-hidden">
                  <div
                    className="h-full sunset-warm rounded-full"
                    style={{ width: `${Math.min((cat.total_revenue / maxRevenue) * 100, 100)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
