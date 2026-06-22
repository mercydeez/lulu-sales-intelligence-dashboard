export interface Sale {
  id: number;
  date: string;
  store_id: number;
  item_id: number;
  sales: number;
  is_streaming: boolean;
  created_at: string;
}

export interface SalesAggregation {
  date: string;
  total_sales: number;
  store_id?: number;
  item_id?: number;
}

export interface Prediction {
  prediction_date: string;
  predicted_sales: number;
  confidence_lower: number;
  confidence_upper: number;
}

export interface BacktestPoint {
  date: string;
  actual: number;
  predicted: number;
  baseline: number;
}

export interface BacktestResult {
  model_version: string;
  holdout_days: number;
  mape: number | null;
  baseline_mape: number | null;
  points: BacktestPoint[];
}

export interface TrendPoint {
  date: string;
  sales: number | null;
  forecast: number | null;
}

export interface DashboardMetrics {
  total_sales_today: number;
  total_sales_week: number;
  total_sales_month: number;
  average_daily_sales: number;
  sales_trend: 'up' | 'down' | 'stable';
  streaming_records_count: number;
}

export interface RevenueProjectionPoint {
  date: string;
  units: number;
  revenue: number;
  revenue_lower: number;
  revenue_upper: number;
}

export interface RevenueProjection {
  horizon_days: number;
  currency: string;
  model_version: string;
  projected_units: number;
  projected_revenue: number;
  avg_daily_units: number;
  avg_daily_revenue: number;
  daily: RevenueProjectionPoint[];
  status: 'ready' | 'insufficient_history';
}

// These three mirror /api/analytics/{stores,categories,top-items}, whose money
// field is AED revenue. The field is `total_revenue` (AED) per the units/AED
// convention — never `total_sales` (which denotes units elsewhere).
export interface StoreDistributionPoint {
  store_id: number;
  store_name: string;
  total_revenue: number;
  percentage: number;
}

export interface CategoryBreakdownPoint {
  category: string;
  total_revenue: number;
  percentage: number;
}

export interface TopItemPoint {
  item_id: number;
  item_name: string;
  category: string;
  total_revenue: number;
}

export interface StreamEvent {
  event_type: string;
  data: Sale;
  timestamp: string;
}

export interface Store {
  id: number;
  name: string;
  location: string | null;
}

export interface Item {
  id: number;
  name: string;
  category: string | null;
}
