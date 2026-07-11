import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Skeleton } from '@/components/ui';

const chartLoading = () =>
  createElement(Skeleton, { className: 'h-80 w-full rounded-2xl' });

// Recharts-backed report panels — lazy-loaded so Recharts stays out of the
// reports route's First-Load JS (loaded when each panel mounts).
export const ReportTrendPanel = dynamic(
  () => import('./ReportChartPanels').then((m) => m.ReportTrendPanel),
  { ssr: false, loading: chartLoading },
);
export const ReportCategoryPanel = dynamic(
  () => import('./ReportChartPanels').then((m) => m.ReportCategoryPanel),
  { ssr: false, loading: chartLoading },
);
export const ReportTopItemsPanel = dynamic(
  () => import('./ReportChartPanels').then((m) => m.ReportTopItemsPanel),
  { ssr: false, loading: chartLoading },
);

// Non-chart panels — no Recharts, keep synchronous.
export { ReportKpiCards, ReportStoreTable } from './ReportPanels';
export type {
  SalesReport, ReportKpis, ReportDailyPoint, ReportCategory, ReportStore, ReportTopItem, ReportRange,
} from './types';
export { REPORT_RANGE_DAYS } from './types';
