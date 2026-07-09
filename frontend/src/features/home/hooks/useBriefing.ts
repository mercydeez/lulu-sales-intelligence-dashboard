'use client';

/**
 * useBriefing — the Executive Briefing data hook (feature: home).
 *
 * Seed for P1: the `/today` verdict zone and `/briefing` page will consume this
 * instead of inlining the fetch. Wraps the existing `/api/briefing` endpoint
 * (backend frozen) and returns the standard `{ data, loading, error, reload }`.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiGet, ApiError } from '@/lib/apiClient';

export interface BriefingHeadline {
  revenue_aed: number;
  revenue_change_pct: number | null;
  units: number;
  units_change_pct: number | null;
  trend: 'up' | 'down' | 'flat' | string;
  period_label: string;
  summary: string;
}

export interface BriefingChange {
  title: string; detail?: string; severity: string; entity?: string; category?: string; href: string;
}
export interface BriefingDecision {
  title: string; why: string; action: string; urgency: string; href: string; kind: string;
}
export interface BriefingWin { title: string; detail: string; kind: string }
export interface BriefingSeason {
  name: string; active: boolean; days_until: number; note: string; approx: boolean;
}
export interface BriefingForecast {
  horizon_days: number; projected_revenue_aed: number; avg_daily_revenue_aed: number;
}
export interface BriefingWatch {
  season: BriefingSeason | null; forecast: BriefingForecast | null; summary: string;
}
export interface BriefingLeak {
  dead_stock_aed: number; stockout_loss_aed: number; total_aed: number; note: string;
}

export interface Briefing {
  date: string;
  generated_at: string | null;
  tenant_name: string;
  greeting: string;
  tldr: string;
  headline: BriefingHeadline;
  changes: BriefingChange[];
  decisions: BriefingDecision[];
  win: BriefingWin | null;
  watch: BriefingWatch;
  leak: BriefingLeak;
  counts: { open_findings: number; decisions: number; reorder_risks: number };
  empty: boolean;
}

export interface UseBriefingResult {
  data: Briefing | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useBriefing(): UseBriefingResult {
  const [data, setData] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiGet<Briefing>('/api/briefing'));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load your briefing');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return { data, loading, error, reload };
}
