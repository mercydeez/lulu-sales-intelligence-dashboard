'use client';

/**
 * Revenue Projection card (B1.7) — surfaces the forecasting engine's forward
 * revenue projection on the dashboard. Self-contained: fetches its own data so
 * it can be dropped anywhere without threading props through the page.
 */
import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, Badge } from '@/components/ui';
import { fetchRevenueProjection } from '@/lib/api';
import type { RevenueProjection } from '@/types';
import { TrendingUp } from 'lucide-react';

const HORIZON = 14;

export default function RevenueProjectionCard() {
  const [data, setData] = useState<RevenueProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchRevenueProjection(HORIZON)
      .then((d) => { if (active) { setData(d); setLoading(false); } })
      .catch(() => { if (active) { setFailed(true); setLoading(false); } });
    return () => { active = false; };
  }, []);

  if (failed) return null; // stay invisible rather than show a broken card

  const ready = data?.status === 'ready';
  const fmt = (n: number) =>
    new Intl.NumberFormat('en-AE', { maximumFractionDigits: 0 }).format(n);

  return (
    <Card padding="lg" className="mb-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-teal-100 text-teal-700">
            <TrendingUp className="h-4 w-4" aria-hidden />
          </span>
          {HORIZON}-Day Revenue Projection
        </CardTitle>
        {data?.model_version && (
          <Badge variant="teal">{data.model_version}</Badge>
        )}
      </CardHeader>

      {loading ? (
        <div className="h-16 animate-pulse rounded-lg bg-ink/5" />
      ) : !ready ? (
        <p className="text-sm text-ink-muted">
          Not enough history yet to project — the model needs more days of sales.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div>
            <p className="text-sm text-ink-muted">Projected revenue</p>
            <p className="text-2xl font-bold text-ink">
              AED {fmt(data!.projected_revenue)}
            </p>
          </div>
          <div>
            <p className="text-sm text-ink-muted">Projected units</p>
            <p className="text-2xl font-bold text-ink">{fmt(data!.projected_units)}</p>
          </div>
          <div>
            <p className="text-sm text-ink-muted">Avg / day</p>
            <p className="text-2xl font-bold text-ink">
              AED {fmt(data!.avg_daily_revenue)}
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}
