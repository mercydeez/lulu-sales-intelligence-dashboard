// NOTE: the /api/reports/sales endpoint aggregates SUM(sales) which is *units*
// (the Kaggle demand dataset has no price column), NOT AED revenue. We therefore
// label these figures as units — unlike the Analytics screen, which multiplies by
// unit_price_aed for revenue. See CLAUDE.md "Known traps".

export interface ReportKpis {
  total_sales: number; // units
  total_transactions: number;
  avg_basket_size: number; // units per transaction
  sales_growth: number; // % vs previous period
}

export interface ReportDailyPoint {
  date: string;
  sales: number;
  transactions: number;
}

export interface ReportCategory {
  category: string;
  sales: number;
  transactions: number;
  percentage: number;
}

export interface ReportStore {
  store_id: number;
  store_name: string;
  location: string;
  sales: number;
  transactions: number;
}

export interface ReportTopItem {
  item_id: number;
  item_name: string;
  category: string;
  total_sales: number;
}

export interface SalesReport {
  period: { days: number; start_date?: string; end_date?: string };
  kpis: ReportKpis;
  daily_sales: ReportDailyPoint[];
  category_breakdown: ReportCategory[];
  store_performance: ReportStore[];
  top_items: ReportTopItem[];
}

export type ReportRange = '7d' | '30d' | '90d';
export const REPORT_RANGE_DAYS: Record<ReportRange, number> = { '7d': 7, '30d': 30, '90d': 90 };
