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

export interface Briefing {
  date: string;
  tenant_name: string;
  greeting: string;
  tldr: string;
  headline: BriefingHeadline;
  changes: Array<{ title: string; detail?: string; severity: string; entity?: string; href?: string }>;
  decisions: Array<{ title: string; why: string; action: string; urgency: string; href?: string }>;
  win: { title: string; detail: string } | null;
  watch: { season: unknown | null; forecast: unknown | null; summary: string };
  leak: { dead_stock_aed: number; stockout_loss_aed: number; total_aed: number; note: string };
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
