import { AlertTriangle, AlertCircle, TrendingUp, Building2, Check, CheckCircle, ChevronLeft, ChevronRight, User } from 'lucide-react';
import { Badge, Button, Card, EmptyState, Skeleton } from '@/components/ui';
import { Alert, AlertSeverity, categoryBadgeVariant, categoryLabels, statusBadgeVariant, statusLabels } from './types';
import { formatDateTime, formatRelativeTime } from './format';

const severityConfig: Record<AlertSeverity, { icon: typeof AlertTriangle; iconColor: string; iconBg: string; border: string }> = {
  critical: { icon: AlertTriangle, iconColor: 'text-rose-600', iconBg: 'bg-rose-100', border: 'border-rose-400' },
  warning: { icon: AlertCircle, iconColor: 'text-amber-600', iconBg: 'bg-amber-100', border: 'border-amber-400' },
  info: { icon: TrendingUp, iconColor: 'text-violet-600', iconBg: 'bg-violet-100', border: 'border-violet-400' },
};

export interface AlertsListProps {
  alerts: Alert[];
  loading: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  onAcknowledge: (alert: Alert) => void;
  onResolve: (alert: Alert) => void;
  pagination?: {
    page: number;
    pages: number;
    onPageChange: (page: number) => void;
  };
}

export default function AlertsList({
  alerts,
  loading,
  emptyTitle = 'All Clear!',
  emptyDescription = 'No alerts to show right now.',
  onAcknowledge,
  onResolve,
  pagination,
}: AlertsListProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => (
          <Card key={i} variant="glass" padding="md">
            <Skeleton height="3.5rem" />
          </Card>
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <Card variant="glass" padding="lg">
        <EmptyState icon={<CheckCircle className="w-7 h-7 text-emerald-500" />} title={emptyTitle} description={emptyDescription} />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {alerts.map((alert) => {
        const config = severityConfig[alert.severity];
        const Icon = config.icon;
        return (
          <Card key={alert.id} variant="glass" padding="md" className={`border-l-4 ${config.border} ${alert.status === 'resolved' ? 'opacity-70' : ''}`}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <div className={`p-2 rounded-lg shrink-0 ${config.iconBg}`}>
                  <Icon className={`w-5 h-5 ${config.iconColor}`} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-ink font-medium">{alert.title}</p>
                    <Badge variant={categoryBadgeVariant[alert.alert_type]} size="sm">{categoryLabels[alert.alert_type]}</Badge>
                    <Badge variant={statusBadgeVariant[alert.status]} size="sm">{statusLabels[alert.status]}</Badge>
                  </div>
                  <p className="text-sm text-ink-muted mt-1">{alert.message}</p>
                  <div className="flex items-center gap-4 mt-2 text-xs text-ink-muted flex-wrap">
                    {alert.store_name && (
                      <span className="flex items-center gap-1">
                        <Building2 className="w-3.5 h-3.5" />
                        {alert.store_name}
                      </span>
                    )}
                    <span title={formatDateTime(alert.created_at)}>{formatRelativeTime(alert.created_at)}</span>
                    {alert.assigned_to_name && (
                      <span className="flex items-center gap-1">
                        <User className="w-3.5 h-3.5" />
                        {alert.assigned_to_name}
                      </span>
                    )}
                  </div>
                  {alert.status === 'resolved' && alert.resolution_notes && (
                    <p className="text-xs text-ink-muted mt-2 italic">&ldquo;{alert.resolution_notes}&rdquo;</p>
                  )}
                </div>
              </div>

              {alert.status !== 'resolved' && (
                <div className="flex items-center gap-2 shrink-0">
                  {alert.status === 'active' && (
                    <button
                      onClick={() => onAcknowledge(alert)}
                      className="p-2 rounded-lg bg-coral-50 text-ink-soft hover:bg-coral-100 transition-colors"
                      title="Acknowledge"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                  )}
                  <Button size="sm" onClick={() => onResolve(alert)}>Resolve</Button>
                </div>
              )}
            </div>
          </Card>
        );
      })}

      {pagination && pagination.pages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={pagination.page <= 1}
            onClick={() => pagination.onPageChange(pagination.page - 1)}
          >
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <span className="text-sm text-ink-muted">Page {pagination.page} of {pagination.pages}</span>
          <Button
            variant="secondary"
            size="sm"
            disabled={pagination.page >= pagination.pages}
            onClick={() => pagination.onPageChange(pagination.page + 1)}
          >
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
