'use client';

import { Info } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { Card, Badge } from '@/components/ui';

/**
 * Financial Overview — illustrative P&L summary.
 *
 * These figures are static placeholders: there is no margin/operating-cost
 * data source yet (only /api/kpis, which carries revenue/units, not P&L). The
 * block is labelled "Sample data" so it is never mistaken for the tenant's real
 * financials. When a financials endpoint exists, replace the hardcoded values
 * and drop the sample badge/footnote — the layout can stay.
 */
export default function FinancialOverview() {
  const { hasPermission } = useAuth();
  if (!hasPermission('can_view_financials')) return null;

  return (
    <section>
      <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
        <span className="w-1.5 h-8 sunset-warm rounded-full" />
        Financial Overview
        <Badge variant="neutral" size="md">Sample data</Badge>
      </h2>
      <Card variant="glass" padding="lg">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="text-center">
            <p className="font-mono text-[11px] uppercase tracking-wide text-ink-muted mb-1">Monthly Revenue</p>
            <p className="text-3xl font-bold text-ink tabular-nums">AED 2.4M</p>
            <p className="text-teal-600 text-sm font-medium">+12.5% vs last month</p>
          </div>
          <div className="text-center">
            <p className="font-mono text-[11px] uppercase tracking-wide text-ink-muted mb-1">Gross Margin</p>
            <p className="text-3xl font-bold text-ink tabular-nums">24.8%</p>
            <p className="text-violet-600 text-sm font-medium">Target: 25%</p>
          </div>
          <div className="text-center">
            <p className="font-mono text-[11px] uppercase tracking-wide text-ink-muted mb-1">Operating Costs</p>
            <p className="text-3xl font-bold text-ink tabular-nums">AED 580K</p>
            <p className="text-coral-600 text-sm font-medium">-3.2% optimized</p>
          </div>
        </div>
        <p className="mt-5 pt-4 border-t border-line flex items-center gap-1.5 text-xs text-ink-muted">
          <Info className="w-3.5 h-3.5 shrink-0" />
          Illustrative figures — connect a financials source to see live P&amp;L.
        </p>
      </Card>
    </section>
  );
}
