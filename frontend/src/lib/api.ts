import {
  Sale, SalesAggregation, DashboardMetrics, Prediction, Store, Item, BacktestResult, TrendPoint,
  StoreDistributionPoint, CategoryBreakdownPoint, TopItemPoint, RevenueProjection,
  Finding, FindingsSummary,
} from '@/types';
import { apiRequest, clearApiCache } from './apiClient';

// Per-endpoint cache TTLs in milliseconds. Caching, auth, refresh-retry and
// error handling all live in apiClient now; this module just maps the typed
// endpoints to a TTL.
const CACHE_TTL: Record<string, number> = {
  'kpis': 15000,              // 15 seconds
  'sales': 10000,             // 10 seconds
  'stores': 300000,           // 5 minutes (rarely changes)
  'items': 300000,            // 5 minutes
  'metrics': 30000,           // 30 seconds
  'predictions': 60000,       // 1 minute
  'aggregated': 30000,        // 30 seconds
  'inventory': 30000,         // 30 seconds
  'promotions': 60000,        // 1 minute
  'alerts': 30000,            // 30 seconds
  'default': 20000            // 20 seconds default
};

// Thin wrapper kept so the typed functions below read unchanged.
async function cachedFetch<T>(
  endpoint: string,
  ttlKey: string,
  params?: Record<string, unknown>,
): Promise<T> {
  return apiRequest<T>(endpoint, { params, ttl: CACHE_TTL[ttlKey] ?? CACHE_TTL.default });
}

/** Clear cached responses (delegates to the shared user-aware cache). */
export function clearCache(pattern?: string): void {
  clearApiCache(pattern);
}

// ============================================================================
// API FUNCTIONS WITH CACHING
// ============================================================================

export async function fetchSales(params?: {
  start_date?: string;
  end_date?: string;
  store_id?: number;
  item_id?: number;
  streaming_only?: boolean;
  limit?: number;
}): Promise<Sale[]> {
  return cachedFetch<Sale[]>('/api/sales/', 'sales', params as Record<string, unknown>);
}

export async function fetchAggregatedSales(params?: {
  start_date?: string;
  end_date?: string;
}): Promise<SalesAggregation[]> {
  return cachedFetch<SalesAggregation[]>('/api/sales/aggregated', 'aggregated', params as Record<string, unknown>);
}

export async function fetchMetrics(): Promise<DashboardMetrics> {
  return cachedFetch<DashboardMetrics>('/api/sales/metrics', 'metrics');
}

export async function fetchPredictions(days: number = 30): Promise<Prediction[]> {
  return cachedFetch<Prediction[]>('/api/sales/predictions', 'predictions', { days });
}

export async function fetchStores(): Promise<Store[]> {
  return cachedFetch<Store[]>('/api/sales/stores', 'stores');
}

export async function fetchItems(): Promise<Item[]> {
  return cachedFetch<Item[]>('/api/sales/items', 'items');
}

export async function fetchKPIs(): Promise<DashboardMetrics> {
  return cachedFetch<DashboardMetrics>('/api/kpis', 'kpis');
}

/** Forward revenue projection (B1.7) — the forecasting engine valued at the
 *  average unit price, scoped to the caller's tenant + stores. */
export async function fetchRevenueProjection(horizon: number = 14): Promise<RevenueProjection> {
  return cachedFetch<RevenueProjection>('/api/kpis/projection', 'predictions', { horizon });
}

export async function fetchTrend(days: number = 30, includeForecast: boolean = true): Promise<{ data: TrendPoint[] }> {
  return cachedFetch<{ data: TrendPoint[] }>('/api/analytics/trend', 'aggregated', {
    days,
    include_forecast: includeForecast,
  });
}

export async function fetchBacktest(params?: {
  store_id?: number;
  item_id?: number;
  holdout_days?: number;
}): Promise<BacktestResult> {
  return cachedFetch<BacktestResult>('/api/sales/predictions/backtest', 'predictions', params as Record<string, unknown>);
}

export async function fetchStoreDistribution(): Promise<{ data: StoreDistributionPoint[]; total: number }> {
  return cachedFetch<{ data: StoreDistributionPoint[]; total: number }>('/api/analytics/stores', 'aggregated');
}

export async function fetchCategoryBreakdown(): Promise<{ data: CategoryBreakdownPoint[]; total: number }> {
  return cachedFetch<{ data: CategoryBreakdownPoint[]; total: number }>('/api/analytics/categories', 'aggregated');
}

export async function fetchTopItems(limit: number = 10): Promise<{ data: TopItemPoint[] }> {
  return cachedFetch<{ data: TopItemPoint[] }>('/api/analytics/top-items', 'aggregated', { limit });
}

// ============================================================================
// DIAGNOSTICS / FINDINGS (A3) — live ops data, never cached.
// ============================================================================
export async function fetchFindings(params?: {
  status?: string; severity?: string; category?: string; limit?: number;
}): Promise<{ data: Finding[]; count: number }> {
  return apiRequest('/api/findings', { params: params as Record<string, unknown> });
}

export async function fetchFindingsSummary(): Promise<FindingsSummary> {
  return apiRequest('/api/findings/summary');
}

export async function acknowledgeFinding(id: number): Promise<{ id: number; status: string }> {
  return apiRequest(`/api/findings/${id}/acknowledge`, { method: 'POST' });
}

export async function resolveFinding(id: number): Promise<{ id: number; status: string }> {
  return apiRequest(`/api/findings/${id}/resolve`, { method: 'POST', body: {} });
}
