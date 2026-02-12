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

export interface DashboardMetrics {
  total_sales_today: number;
  total_sales_week: number;
  total_sales_month: number;
  average_daily_sales: number;
  sales_trend: 'up' | 'down' | 'stable';
  streaming_records_count: number;
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
