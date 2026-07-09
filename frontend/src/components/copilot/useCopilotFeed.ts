'use client';

/**
 * Shared fetch for the Sage Copilot feed (`GET /api/ai/copilot/feed`).
 *
 * LOAD-BEARING, not polish: `lib/apiClient` caches responses but not in-flight
 * promises, so four feed widgets mounting together would fire four concurrent
 * requests — each racing ahead of the server's Redis set and triggering a full
 * five-engine composition. This hook dedupes to ONE request per page via a
 * module-scoped in-flight promise + a short staleness window.
 *
 * Deliberately built on `apiGet` (not the `lib/api.ts` facade): the facade adds
 * only a TTL this hook supersedes, and direct `apiGet` is the convention every
 * `/today` zone already uses.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiGet } from '@/lib/apiClient';

/* ── Feed payload types (mirror services/sage_copilot.build_feed) ──
   Widget-name ↔ feed-key mapping (the doc's §3.2 names vs the payload):
     zone `business_health`            → feed.business_health
     zone `risks`                      → feed.risks
     zone `opportunities` (alias `growth`) → feed.opportunities
     zone `recommendations`            → feed.recommended_actions */

export interface EvidenceFact { label: string; value: string }

export interface FeedImpact { aed: number | null; units: number | null; per: string | null }

/** Decision-shaped (decision_center.build_decision) — risks reuse it verbatim. */
export interface FeedRisk {
  id: number | null;
  severity: 'critical' | 'high' | 'medium' | 'low' | string;
  problem: string;
  detail?: string;
  impact: FeedImpact;
  recommended_action?: string | null;
  href?: string | null;
  confidence?: { score: number | null; level: string } | null;
  kind?: string;
}

export interface FeedOpportunity {
  title: string;
  reason: string;
  evidence: EvidenceFact[];
  confidence: number | null;
  deep_link: string;
}

export interface FeedAction extends FeedOpportunity {
  priority: 'urgent' | 'high' | 'normal' | 'low';
}

export interface BusinessHealth {
  overall: 'strong' | 'steady' | 'attention' | 'critical';
  score: number; // 0..1
  factors: string[];
  components: {
    revenue_trend: string;
    revenue_change_pct: number | null;
    open_actions: number;
    at_stake_aed_per_week: number;
    critical_risks: number;
    inventory_pressure: { below_reorder_count: number; total_skus: number };
    forecast_status: string;
  };
}

export interface CopilotFeed {
  version: number;
  generated_at: string;
  fresh_until: string;
  briefing: Record<string, unknown>;
  business_health: BusinessHealth;
  decisions: FeedRisk[];
  risks: FeedRisk[];
  opportunities: FeedOpportunity[];
  forecast: Record<string, unknown>;
  roi: Record<string, unknown>;
  recommended_actions: FeedAction[];
  alerts: FeedRisk[];
  metadata: {
    confidence: number | null;
    sections_included: string[];
    more_strategic_count: number;
  };
}

export type FeedStatus = 'loading' | 'ok' | 'error';

const STALE_MS = 60_000; // client staleness; the server's own cache is 5 min

let cached: { data: CopilotFeed; ts: number } | null = null;
let inflight: Promise<CopilotFeed> | null = null;

function fetchFeed(force = false): Promise<CopilotFeed> {
  if (!force && cached && Date.now() - cached.ts < STALE_MS) {
    return Promise.resolve(cached.data);
  }
  if (!inflight) {
    inflight = apiGet<CopilotFeed>('/api/ai/copilot/feed')
      .then((d) => {
        cached = { data: d, ts: Date.now() };
        return d;
      })
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function useCopilotFeed(): { feed: CopilotFeed | null; status: FeedStatus; refresh: () => void } {
  const [feed, setFeed] = useState<CopilotFeed | null>(cached?.data ?? null);
  const [status, setStatus] = useState<FeedStatus>(cached ? 'ok' : 'loading');
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    if (!cached) setStatus('loading');
    fetchFeed(tick > 0)
      .then((d) => { if (active) { setFeed(d); setStatus('ok'); } })
      .catch(() => { if (active) setStatus('error'); });
    return () => { active = false; };
  }, [tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { feed, status, refresh };
}
