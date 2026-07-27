import { Package, CheckCircle, TrendingDown, AlertTriangle, TrendingUp, Truck } from 'lucide-react';
import { StatCard } from '@/components/ui';
import { InventorySummary } from './types';
import { formatNumber } from './format';

export interface StockSummary {
  inStock: number;
  lowStock: number;
  outOfStock: number;
  overStock: number;
}

export interface InventorySummaryCardsProps {
  summary: InventorySummary | null;
  stockSummary: StockSummary;
  pendingProcurement: number;
}

export default function InventorySummaryCards({ summary, stockSummary, pendingProcurement }: InventorySummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
      <StatCard label="Total Items" tone="coral" icon={<Package className="w-5 h-5" />} value={formatNumber(summary?.total_items || 0)} />
      <StatCard label="In Stock" tone="teal" icon={<CheckCircle className="w-5 h-5" />} value={stockSummary.inStock} />
      <StatCard label="Low Stock" tone="amber" icon={<TrendingDown className="w-5 h-5" />} value={summary?.low_stock_count ?? stockSummary.lowStock} />
      <StatCard label="Out of Stock" tone="coral" icon={<AlertTriangle className="w-5 h-5" />} value={summary?.out_of_stock_count ?? stockSummary.outOfStock} />
      <StatCard label="Overstocked" tone="violet" icon={<TrendingUp className="w-5 h-5" />} value={summary?.overstocked_count ?? stockSummary.overStock} />
      <StatCard label="Pending Orders" tone="violet" icon={<Truck className="w-5 h-5" />} value={pendingProcurement} />
    </div>
  );
}
