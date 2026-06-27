import { Clock, AlertTriangle, AlertCircle, TrendingUp, CheckCircle } from 'lucide-react';
import { Badge, Card, EmptyState, Skeleton } from '@/components/ui';
import { Alert, AlertSeverity, severityBadgeVariant } from './types';
import { formatRelativeTime } from './format';

const severityIcon: Record<AlertSeverity, typeof AlertTriangle> = {
  critical: AlertTriangle,
  warning: AlertCircle,
  info: TrendingUp,
};

export interface RecentAlertsPanelProps {
  alerts: Alert[];
  loading: boolean;
}

export default function RecentAlertsPanel({ alerts, loading }: RecentAlertsPanelProps) {
  return (
    <Card variant="glass" padding="none" className="overflow-hidden">
      <div className="p-4 border-b border-line">
        <h2 className="text-lg font-semibold text-ink flex items-center gap-2">
          <Clock className="w-5 h-5 text-coral-500" />
          Recent Alerts
        </h2>
      </div>

      {loading ? (
        <div className="p-4 space-y-3">
          {[...Array(3)].map((_, i) => <Skeleton key={i} height="2.5rem" />)}
        </div>
      ) : alerts.length === 0 ? (
        <EmptyState icon={<CheckCircle className="w-6 h-6 text-emerald-500" />} title="No recent alerts" />
      ) : (
        <div className="divide-y divide-line">
          {alerts.map((alert) => {
            const Icon = severityIcon[alert.severity];
            return (
              <div key={alert.id} className="p-4 hover:bg-surface-2/60 transition-colors">
                <div className="flex items-start gap-3">
                  <div className="p-1.5 rounded-lg bg-coral-50">
                    <Icon className="w-4 h-4 text-coral-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-ink text-sm truncate">{alert.title}</p>
                    <p className="text-xs text-ink-muted mt-0.5">
                      {alert.store_name || 'System'} · {formatRelativeTime(alert.created_at)}
                    </p>
                  </div>
                  <Badge variant={severityBadgeVariant[alert.severity]} size="sm">{alert.severity}</Badge>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
