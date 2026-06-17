'use client';

import { useAuth } from '@/contexts/AuthContext';
import { Card, Badge } from '@/components/ui';

export default function FinancialOverview() {
  const { hasPermission } = useAuth();
  if (!hasPermission('can_view_financials')) return null;

  return (
    <section>
      <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
        <span className="w-1.5 h-8 sunset-warm rounded-full" />
        Financial Overview
        <Badge variant="warning" size="md">Restricted Access</Badge>
      </h2>
      <Card variant="glass" padding="lg">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="text-center">
            <p className="text-ink-muted text-sm mb-1">Monthly Revenue</p>
            <p className="text-3xl font-bold text-ink">AED 2.4M</p>
            <p className="text-teal-600 text-sm font-medium">+12.5% vs last month</p>
          </div>
          <div className="text-center">
            <p className="text-ink-muted text-sm mb-1">Gross Margin</p>
            <p className="text-3xl font-bold text-ink">24.8%</p>
            <p className="text-violet-600 text-sm font-medium">Target: 25%</p>
          </div>
          <div className="text-center">
            <p className="text-ink-muted text-sm mb-1">Operating Costs</p>
            <p className="text-3xl font-bold text-ink">AED 580K</p>
            <p className="text-coral-600 text-sm font-medium">-3.2% optimized</p>
          </div>
        </div>
      </Card>
    </section>
  );
}
