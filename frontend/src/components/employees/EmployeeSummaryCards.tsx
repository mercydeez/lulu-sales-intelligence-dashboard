'use client';

import { Users, TrendingUp, Star, Clock } from 'lucide-react';
import { StatCard } from '@/components/ui';
import { EmployeeSummary } from './types';

interface EmployeeSummaryCardsProps {
  summary: EmployeeSummary | null;
  loading: boolean;
}

export function EmployeeSummaryCards({ summary, loading }: EmployeeSummaryCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard
        variant="gradient"
        tone="coral"
        label="Total Employees"
        value={loading ? '—' : summary?.total_employees ?? 0}
        icon={<Users className="w-5 h-5" />}
        footnote={summary ? `+${summary.new_hires_this_month} this month` : undefined}
        loading={loading}
      />
      <StatCard
        tone="teal"
        label="Avg Performance"
        value={loading ? '—' : `${(summary?.avg_performance_score ?? 0).toFixed(1)}%`}
        icon={<TrendingUp className="w-5 h-5" />}
        footnote="Across all employees"
        loading={loading}
      />
      <StatCard
        tone="amber"
        label="Customer Rating"
        value={loading ? '—' : (summary?.avg_customer_rating ?? 0).toFixed(2)}
        icon={<Star className="w-5 h-5" />}
        footnote="Out of 5.0"
        loading={loading}
      />
      <StatCard
        tone="violet"
        label="Avg Attendance"
        value={loading ? '—' : `${(summary?.avg_attendance ?? 0).toFixed(1)}%`}
        icon={<Clock className="w-5 h-5" />}
        footnote="Monthly average"
        loading={loading}
      />
    </div>
  );
}
