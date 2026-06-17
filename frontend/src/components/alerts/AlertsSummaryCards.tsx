import { AlertTriangle, AlertCircle, Info, Check, CheckCircle, Bell } from 'lucide-react';
import { StatCard } from '@/components/ui';
import { AlertSummary } from './types';

export interface AlertsSummaryCardsProps {
  summary: AlertSummary | null;
  loading: boolean;
}

export default function AlertsSummaryCards({ summary, loading }: AlertsSummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
      <StatCard loading={loading} label="Critical" tone="coral" icon={<AlertTriangle className="w-5 h-5" />} value={summary?.critical_alerts ?? 0} />
      <StatCard loading={loading} label="Warning" tone="amber" icon={<AlertCircle className="w-5 h-5" />} value={summary?.warning_alerts ?? 0} />
      <StatCard loading={loading} label="Info" tone="violet" icon={<Info className="w-5 h-5" />} value={summary?.info_alerts ?? 0} />
      <StatCard loading={loading} label="Acknowledged" tone="teal" icon={<Check className="w-5 h-5" />} value={summary?.acknowledged ?? 0} />
      <StatCard loading={loading} label="Resolved Today" tone="teal" icon={<CheckCircle className="w-5 h-5" />} value={summary?.resolved_today ?? 0} />
      <StatCard loading={loading} label="Total Active" tone="coral" icon={<Bell className="w-5 h-5" />} value={summary?.total_active ?? 0} />
    </div>
  );
}
