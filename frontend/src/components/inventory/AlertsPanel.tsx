import { Bell, AlertTriangle, AlertCircle, TrendingUp, Building2, Check, CheckCircle } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/components/ui';
import { InventoryAlert } from './types';
import { formatTime } from './format';

const severityConfig: Record<InventoryAlert['severity'], { icon: typeof AlertTriangle; iconColor: string; iconBg: string; border: string; textColor: string }> = {
  critical: { icon: AlertTriangle, iconColor: 'text-rose-600', iconBg: 'bg-rose-100', border: 'border-rose-400', textColor: 'text-rose-600' },
  warning: { icon: AlertCircle, iconColor: 'text-amber-600', iconBg: 'bg-amber-100', border: 'border-amber-400', textColor: 'text-amber-600' },
  info: { icon: TrendingUp, iconColor: 'text-violet-600', iconBg: 'bg-violet-100', border: 'border-violet-400', textColor: 'text-violet-600' },
};

export interface AlertsPanelProps {
  alerts: InventoryAlert[];
  unacknowledgedAlerts: number;
  canManageInventory: boolean;
  onAcknowledge: (alertId: number) => void;
  onMarkAllRead: () => void;
  onCreateOrder: (alert: InventoryAlert) => void;
}

export default function AlertsPanel({
  alerts,
  unacknowledgedAlerts,
  canManageInventory,
  onAcknowledge,
  onMarkAllRead,
  onCreateOrder,
}: AlertsPanelProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-ink flex items-center gap-2">
          <Bell className="w-6 h-6 text-coral-500" />
          Inventory Alerts
          <Badge variant="danger" size="sm">{unacknowledgedAlerts} unread</Badge>
        </h2>
        <Button variant="secondary" size="sm" onClick={onMarkAllRead}>Mark All Read</Button>
      </div>

      {alerts.length === 0 ? (
        <Card variant="glass" padding="lg">
          <EmptyState
            icon={<CheckCircle className="w-7 h-7 text-emerald-500" />}
            title="All Clear!"
            description="No inventory alerts at this time"
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => {
            const config = severityConfig[alert.severity];
            const Icon = config.icon;
            return (
              <Card
                key={alert.id}
                variant="glass"
                padding="md"
                className={`border-l-4 ${config.border} ${alert.acknowledged ? 'opacity-60' : ''}`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <div className={`p-2 rounded-lg ${config.iconBg}`}>
                      <Icon className={`w-5 h-5 ${config.iconColor}`} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-semibold ${config.textColor}`}>
                          {alert.type.replace('_', ' ').toUpperCase()}
                        </span>
                        <span className="text-xs text-ink-muted">{formatTime(alert.timestamp)}</span>
                        {!alert.acknowledged && (
                          <span className="w-2 h-2 rounded-full bg-coral-400 animate-pulse" />
                        )}
                      </div>
                      <p className="text-ink font-medium mt-1">{alert.item_name}</p>
                      <p className="text-sm text-ink-muted mt-1">{alert.message}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <Building2 className="w-4 h-4 text-ink-muted" />
                        <span className="text-xs text-ink-muted">{alert.store_name}</span>
                      </div>
                    </div>
                  </div>
                  {!alert.acknowledged && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onAcknowledge(alert.id)}
                        className="p-2 rounded-lg bg-coral-50 text-ink-soft hover:bg-coral-100 transition-colors"
                        title="Acknowledge"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                      {canManageInventory && alert.type !== 'overstocked' && (
                        <Button size="sm" onClick={() => onCreateOrder(alert)}>Create Order</Button>
                      )}
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
