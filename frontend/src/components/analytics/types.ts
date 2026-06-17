// Shape returned by GET /api/kpis (backend KPIResponse). Kept local to the
// analytics screen since it is richer than the shared DashboardMetrics type.
export interface AnalyticsKpis {
  total_historical_records: number;
  total_streaming_records: number;
  total_sales_today: number;
  total_sales_week: number;
  total_sales_month: number;
  average_daily_sales: number;
  total_revenue_today: number;
  total_revenue_week: number;
  total_revenue_month: number;
  average_daily_revenue: number;
  unique_stores: number;
  unique_items: number;
  data_range_start: string | null;
  data_range_end: string | null;
  last_stream_timestamp: string | null;
  sales_trend: 'up' | 'down' | 'stable';
  revenue_trend: 'up' | 'down' | 'stable';
}

export type DateRange = '7d' | '30d' | '90d';

export const RANGE_DAYS: Record<DateRange, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};
