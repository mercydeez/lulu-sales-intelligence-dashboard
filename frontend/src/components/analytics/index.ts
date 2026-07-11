import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Skeleton } from '@/components/ui';

// Recharts is heavy (~200 kB) and only ever runs client-side. Loading these
// chart panels through `next/dynamic({ ssr: false })` splits Recharts + the
// panel body into an async chunk that a route pulls only when the panel
// actually mounts — keeping it out of every consumer's First-Load JS. The
// panels already render their own internal skeletons once mounted; this
// `loading` fallback only covers the brief chunk-fetch gap. Non-chart exports
// below (KPI cards, tables, utils, types) stay static.
const chartLoading = () =>
  createElement(Skeleton, { className: 'h-72 w-full rounded-2xl' });

export const SalesTrendPanel = dynamic(
  () => import('./SalesTrendPanel').then((m) => m.SalesTrendPanel),
  { ssr: false, loading: chartLoading },
);
export const CategoryDonut = dynamic(
  () => import('./CategoryDonut').then((m) => m.CategoryDonut),
  { ssr: false, loading: chartLoading },
);
export const StoreDistributionPanel = dynamic(
  () => import('./StoreDistributionPanel').then((m) => m.StoreDistributionPanel),
  { ssr: false, loading: chartLoading },
);
export const TopItemsPanel = dynamic(
  () => import('./TopItemsPanel').then((m) => m.TopItemsPanel),
  { ssr: false, loading: chartLoading },
);
export const ForecastPanel = dynamic(
  () => import('./ForecastPanel').then((m) => m.ForecastPanel),
  { ssr: false, loading: chartLoading },
);

// Non-chart exports — no Recharts, keep them synchronous.
export { AnalyticsKpiCards } from './AnalyticsKpiCards';
export { StorePerformanceTable } from './StorePerformanceTable';
export type { AnalyticsKpis, DateRange } from './types';
export { RANGE_DAYS } from './types';
export { formatCurrency, formatCompact, formatDateShort } from './format';
