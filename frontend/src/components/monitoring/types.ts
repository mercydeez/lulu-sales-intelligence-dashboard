export interface HealthCheck {
  status: string;
  timestamp: string;
  version: string;
  environment: string;
  checks: {
    database: { status: string; sales_records?: number; streaming_records?: number; error?: string };
    redis: { status: string; connected_clients?: number; used_memory_human?: string; uptime_in_seconds?: number; error?: string };
    application: { status: string; uptime_seconds?: number; requests_in_progress?: number; total_requests?: number; error?: string };
  };
}

export interface SystemStats {
  timestamp: string;
  database: {
    total_sales: number;
    streaming_sales: number;
    active_stores: number;
    active_items: number;
    date_range: { start: string | null; end: string | null };
  };
  streaming: { last_hour_count: number; last_hour_avg_sales: number; last_generated: string | null };
  cache: { connected_clients: number; used_memory: string; total_keys: number };
}

export interface MetricsData {
  counters: Record<string, number>;
  gauges: Record<string, number>;
  histograms: Record<string, { sum: number; count: number; avg: number }>;
  requests_in_progress: number;
  uptime_seconds: number;
}
