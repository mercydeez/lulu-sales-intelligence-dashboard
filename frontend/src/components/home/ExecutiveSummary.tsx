'use client';

/**
 * Executive mode hero number (E4-6): ONE value — AED revenue this week —
 * with the honesty footnote carried. The trend and anomaly slots are the
 * SalesTrendChart and ActionCenter rendered alongside by the dashboard;
 * everything else is drill-down.
 */
import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { StatCard } from '@/components/ui';
import { formatCurrencyCompact } from '@/lib/formatters';

interface Kpis {
  total_revenue_week: number;
  average_daily_revenue: number;
  unique_stores: number;
}

export default function ExecutiveSummary() {
  const { authFetch } = useAuth();
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    authFetch('/api/kpis')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (active) setKpis(d); })
      .catch(() => {})
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [authFetch]);

  return (
    <StatCard
      variant="gradient"
      tone="teal"
      label="Revenue · last 7 days"
      value={kpis ? formatCurrencyCompact(kpis.total_revenue_week) : '—'}
      footnote={
        kpis
          ? `${formatCurrencyCompact(kpis.average_daily_revenue)}/day across ${kpis.unique_stores} stores · AED, derived units × unit price`
          : undefined
      }
      loading={loading}
    />
  );
}
