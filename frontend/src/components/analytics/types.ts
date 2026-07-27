// GET /api/kpis response — canonical definition now lives in @/types; re-exported
// here so existing `@/components/analytics` imports keep resolving.
export type { AnalyticsKpis } from '@/types';

export type DateRange = '7d' | '30d' | '90d';

export const RANGE_DAYS: Record<DateRange, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};
