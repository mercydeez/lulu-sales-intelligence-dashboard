'use client';

import { ShoppingCart, Receipt, Package, TrendingUp, Store } from 'lucide-react';
import {
  Card, StatCard, Table, TableHead, TableBody, TableRow, Th, Td, SkeletonText, EmptyState,
} from '@/components/ui';
import { formatCompact } from '@/components/analytics/format';
import { ReportKpis, ReportStore } from './types';

// Recharts-backed panels (ReportTrendPanel / ReportCategoryPanel /
// ReportTopItemsPanel) live in ./ReportChartPanels and are lazy-loaded via the
// barrel — kept out of this module so the KPI cards + store table below (which
// need no charting lib) stay in the route's synchronous First-Load JS.

export function ReportKpiCards({ kpis, loading }: { kpis: ReportKpis | null; loading: boolean }) {
  // Coerce defensively — cached API responses can deliver numbers as strings.
  const growth = Number(kpis?.sales_growth ?? 0);
  const avgBasket = Number(kpis?.avg_basket_size ?? 0);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard variant="gradient" tone="coral" label="Units Sold" value={loading ? '—' : formatCompact(kpis?.total_sales ?? 0)} icon={<ShoppingCart className="w-5 h-5" />} footnote="Selected period" loading={loading} />
      <StatCard tone="teal" label="Transactions" value={loading ? '—' : formatCompact(kpis?.total_transactions ?? 0)} icon={<Receipt className="w-5 h-5" />} loading={loading} />
      <StatCard tone="violet" label="Avg Basket" value={loading ? '—' : `${avgBasket.toFixed(1)} u`} icon={<Package className="w-5 h-5" />} footnote="Units per transaction" loading={loading} />
      <StatCard tone="amber" label="Period Growth" value={loading ? '—' : `${growth >= 0 ? '+' : ''}${growth.toFixed(1)}%`} icon={<TrendingUp className="w-5 h-5" />} trend={growth >= 0 ? 'up' : 'down'} trendLabel="vs prev" loading={loading} />
    </div>
  );
}

export function ReportStoreTable({ data, loading }: { data: ReportStore[]; loading: boolean }) {
  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-line flex items-center gap-2">
        <Store className="w-5 h-5 text-violet-500" />
        <div>
          <h3 className="text-lg font-semibold text-ink">Store Performance</h3>
          <p className="text-sm text-ink-muted mt-0.5">Units and transactions per store</p>
        </div>
      </div>
      {loading ? (
        <div className="p-5"><SkeletonText lines={5} /></div>
      ) : data.length === 0 ? (
        <EmptyState title="No store data" description="No store performance for this selection." />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>#</Th><Th>Store</Th><Th>Location</Th><Th className="text-end">Units</Th><Th className="text-end">Transactions</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.map((s, i) => (
              <TableRow key={s.store_id}>
                <Td><span className="inline-flex w-7 h-7 items-center justify-center rounded-lg sunset-gradient text-white text-xs font-bold">{i + 1}</span></Td>
                <Td className="font-medium">{s.store_name}</Td>
                <Td className="text-ink-soft">{s.location}</Td>
                <Td className="text-end font-semibold">{formatCompact(s.sales)}</Td>
                <Td className="text-end text-ink-soft">{formatCompact(s.transactions)}</Td>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
