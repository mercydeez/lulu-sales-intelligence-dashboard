'use client';

/**
 * Plan usage meters (CX money loop — docs/product/CX_LOOPS_PLAN.md Y2).
 * Surfaces the backend's existing metering (`/api/tenants/usage/period`,
 * Track 5/Phase 3) that until now had no UI: per-dimension progress against
 * plan limits, with the limit-hit moment turning into an upgrade prompt.
 *
 * Admin-scoped like the API (403 for non-admins → renders nothing). Read-only
 * and honest: shows `enforced` state rather than pretending soft limits block.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, Badge, Button, Skeleton } from '@/components/ui';
import { useLanguage } from '@/contexts/LanguageContext';
import { apiGet } from '@/lib/apiClient';
import { track } from '@/lib/telemetry';
import { Gauge, ArrowUpRight } from 'lucide-react';

interface Meter {
  used: number;
  limit: number | null;
  remaining: number | null;
  over_quota: boolean;
  pct: number;
}

interface PeriodUsage {
  plan: string;
  window: string;
  usage: Record<string, Meter>;
  any_over_quota: boolean;
  enforced?: boolean;
}

/** Human labels for known metered dimensions; unknown dims fall back to the key. */
const DIM_LABELS: Record<string, string> = {
  api_requests: 'API requests',
  api_keys: 'API keys',
  users: 'Team members',
  sage_messages: 'Sage messages',
  forecast_jobs: 'Forecast jobs',
  exports: 'Exports',
  imports: 'Imports',
};

const labelFor = (dim: string) => DIM_LABELS[dim] ?? dim.replace(/_/g, ' ');

function meterTone(m: Meter): { bar: string; text: string } {
  if (m.over_quota) return { bar: 'bg-coral-500', text: 'text-coral-600 dark:text-coral-300' };
  if (m.limit !== null && m.pct >= 80) return { bar: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-300' };
  return { bar: 'bg-teal-600', text: 'text-ink-muted' };
}

export default function UsageMeters() {
  const { t } = useLanguage();
  const [data, setData] = useState<PeriodUsage | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'hidden'>('loading');

  useEffect(() => {
    let active = true;
    // Period meters are the primary read; lifetime meters are the fallback for
    // deployments predating the period endpoint.
    apiGet<PeriodUsage>('/api/tenants/usage/period')
      .catch(() => apiGet<PeriodUsage>('/api/tenants/usage'))
      .then((d) => {
        if (!active) return;
        setData(d);
        setState('ready');
        track('usage_meters_viewed', { plan: d.plan, over_quota: d.any_over_quota });
      })
      .catch(() => { if (active) setState('hidden'); }); // non-admin / older backend
    return () => { active = false; };
  }, []);

  if (state === 'hidden') return null;

  if (state === 'loading') {
    return (
      <Card padding="lg">
        <Skeleton width="40%" height="0.9rem" className="mb-4" />
        <Skeleton width="100%" height="0.5rem" className="mb-3" />
        <Skeleton width="100%" height="0.5rem" />
      </Card>
    );
  }

  const meters = Object.entries(data!.usage);

  return (
    <Card padding="lg">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          <Gauge className="w-4 h-4 text-teal-600" />
          <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">{t('usage.title')}</h3>
          <Badge variant="teal" size="sm">{data!.plan}</Badge>
        </div>
        <span className="text-xs text-ink-muted">{data!.window}</span>
      </div>
      <p className="text-xs text-ink-muted mb-4">
        {data!.enforced ? t('usage.enforced') : t('usage.advisory')}
      </p>

      <ul className="space-y-3">
        {meters.map(([dim, m]) => {
          const tone = meterTone(m);
          const width = m.limit === null ? 0 : Math.min(100, m.pct);
          return (
            <li key={dim}>
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="text-sm text-ink">{labelFor(dim)}</span>
                <span className={`text-xs tabular-nums ${tone.text}`}>
                  {m.limit === null
                    ? `${m.used.toLocaleString()} · ${t('usage.unlimited')}`
                    : `${m.used.toLocaleString()} / ${m.limit.toLocaleString()}`}
                </span>
              </div>
              {m.limit !== null && (
                <div className="h-1.5 w-full rounded-full bg-ink/5 overflow-hidden">
                  <div className={`h-full rounded-full transition-all ${tone.bar}`} style={{ width: `${width}%` }} />
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {data!.any_over_quota && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-coral-200 bg-coral-50 dark:bg-coral-500/10 px-4 py-3">
          <p className="text-sm text-coral-700 dark:text-coral-300">{t('usage.overQuota')}</p>
          <Link href="/pricing" onClick={() => track('upgrade_cta_clicked', { source: 'usage_meters', plan: data!.plan })}>
            <Button size="sm">
              {t('usage.upgrade')} <ArrowUpRight className="w-4 h-4 ms-1" />
            </Button>
          </Link>
        </div>
      )}
    </Card>
  );
}
