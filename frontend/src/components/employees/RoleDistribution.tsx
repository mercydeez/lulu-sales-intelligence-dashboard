'use client';

import { Card, SkeletonText, EmptyState } from '@/components/ui';
import { EmployeeSummary } from './types';
import { roleLabel } from './format';

interface RoleDistributionProps {
  summary: EmployeeSummary | null;
  loading: boolean;
}

export function RoleDistribution({ summary, loading }: RoleDistributionProps) {
  const entries = summary?.by_role ? Object.entries(summary.by_role).sort((a, b) => b[1] - a[1]) : [];
  const total = summary?.total_employees || 1;

  return (
    <Card variant="glass" padding="md">
      <h3 className="text-lg font-semibold text-ink mb-4">Role Distribution</h3>
      {loading ? (
        <SkeletonText lines={6} />
      ) : entries.length === 0 ? (
        <EmptyState title="No distribution data" description="Headcount by role is unavailable." />
      ) : (
        <div className="space-y-4">
          {entries.map(([role, count]) => (
            <div key={role}>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-ink-soft">{roleLabel(role)}</span>
                <span className="text-ink font-medium">{count}</span>
              </div>
              <div className="h-2 bg-coral-100 rounded-full overflow-hidden">
                <div className="h-full sunset-gradient rounded-full" style={{ width: `${(count / total) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
