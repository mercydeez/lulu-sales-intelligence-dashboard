'use client';

import { DollarSign, TrendingUp, CalendarDays, ShoppingCart, Store, Activity } from 'lucide-react';
import { StatCard } from '@/components/ui';
import { useSalesTrend } from '@/lib/queries/analytics';
import type { TrendPoint } from '@/types';
import { formatCurrency, formatCompact } from './format';
import { AnalyticsKpis } from './types';

interface AnalyticsKpiCardsProps {
  kpis: AnalyticsKpis | null;
  loading: boolean;
}

function trendOf(t?: 'up' | 'down' | 'stable'): 'up' | 'down' | 'flat' {
  if (t === 'up') return 'up';
  if (t === 'down') return 'down';
  return 'flat';
}

export function AnalyticsKpiCards({ kpis, loading }: AnalyticsKpiCardsProps) {
  // Real daily-revenue micro-trend for the KPI sparklines (last ~14 days of
  // actuals). Dedups with SalesTrendPanel's identical query via TanStack Query.
  const { data: trend } = useSalesTrend(30, false);
  const revenueSeries = ((trend ?? []) as TrendPoint[])
    .map((d) => d.sales)
    .filter((v): v is number => v != null)
    .slice(-14);
  const spark = revenueSeries.length >= 2 ? revenueSeries : undefined;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-8">
      <StatCard
        variant="gradient"
        tone="coral"
        label="Revenue (7d)"
        value={loading ? '—' : formatCurrency(kpis?.total_revenue_week ?? 0)}
        icon={<DollarSign className="w-5 h-5" />}
        footnote="Trailing 7 days"
        loading={loading}
      />
      <StatCard
        tone="violet"
        label="Revenue (30d)"
        value={loading ? '—' : formatCurrency(kpis?.total_revenue_month ?? 0)}
        icon={<CalendarDays className="w-5 h-5" />}
        trend={trendOf(kpis?.revenue_trend)}
        trendLabel={kpis?.revenue_trend === 'stable' ? 'steady' : 'wk/wk'}
        sparkline={spark}
        loading={loading}
      />
      <StatCard
        tone="teal"
        label="Avg Daily Revenue"
        value={loading ? '—' : formatCurrency(kpis?.average_daily_revenue ?? 0)}
        icon={<TrendingUp className="w-5 h-5" />}
        sparkline={spark}
        loading={loading}
      />
      <StatCard
        tone="amber"
        label="Units Sold (7d)"
        value={loading ? '—' : formatCompact(kpis?.total_sales_week ?? 0)}
        icon={<ShoppingCart className="w-5 h-5" />}
        trend={trendOf(kpis?.sales_trend)}
        trendLabel={kpis?.sales_trend === 'stable' ? 'steady' : 'wk/wk'}
        loading={loading}
      />
      <StatCard
        tone="coral"
        label="Active Stores"
        value={loading ? '—' : (kpis?.unique_stores ?? 0)}
        icon={<Store className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="teal"
        label="Live Events"
        value={loading ? '—' : formatCompact(kpis?.total_streaming_records ?? 0)}
        icon={<Activity className="w-5 h-5" />}
        footnote="Generated this session"
        loading={loading}
      />
    </div>
  );
}
