import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Skeleton } from '@/components/ui';

// Recharts-backed charts are client-only and heavy — load them through
// `next/dynamic({ ssr: false })` so Recharts lands in an async chunk fetched
// only when the chart mounts, not in every consumer's First-Load JS.
const chartLoading = () =>
  createElement(Skeleton, { className: 'h-64 w-full rounded-2xl' });

export const SalesTrendChart = dynamic(() => import('./SalesTrendChart'), {
  ssr: false,
  loading: chartLoading,
});
export const ForecastAccuracyChart = dynamic(() => import('./ForecastAccuracyChart'), {
  ssr: false,
  loading: chartLoading,
});
export const LiveStreamChart = dynamic(() => import('./LiveStreamChart'), {
  ssr: false,
  loading: chartLoading,
});
export const ReturnsByCategoryChart = dynamic(() => import('./ReturnsByCategoryChart'), {
  ssr: false,
  loading: chartLoading,
});

// Live feed (no Recharts) — keep static.
export { default as ReturnsLiveFeed } from './ReturnsLiveFeed';
