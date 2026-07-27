import { BadgeVariant } from '@/components/ui';

export type AlertSeverity = 'critical' | 'warning' | 'info';
export type AlertStatus = 'active' | 'acknowledged' | 'resolved';
export type AlertCategory = 'inventory' | 'expiry' | 'sales' | 'system';

export interface Alert {
  id: number;
  title: string;
  message: string;
  alert_type: AlertCategory;
  severity: AlertSeverity;
  status: AlertStatus;
  store_id: number | null;
  store_name: string | null;
  item_id: number | null;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: number | null;
  resolved_at: string | null;
  resolved_by: number | null;
  resolution_notes: string | null;
  assigned_to: number | null;
  assigned_to_name: string | null;
  assigned_at: string | null;
}

export interface AlertSummary {
  critical_alerts: number;
  warning_alerts: number;
  info_alerts: number;
  acknowledged: number;
  resolved_today: number;
  total_active: number;
}

export interface AlertDailyStat {
  date: string;
  critical: number;
  warning: number;
  info: number;
  resolved: number;
}

export interface AlertStats {
  period_days: number;
  daily_stats: AlertDailyStat[];
  type_breakdown: Record<string, number>;
  total_alerts: number;
  resolution_rate: number;
}

export interface AlertRule {
  id: number;
  name: string;
  rule_type: string;
  condition: Record<string, unknown>;
  action: string;
  severity: AlertSeverity;
  is_active: boolean;
  last_triggered?: string;
  created_at?: string;
}

export const severityBadgeVariant: Record<AlertSeverity, BadgeVariant> = {
  critical: 'danger',
  warning: 'warning',
  info: 'violet',
};

export const statusBadgeVariant: Record<AlertStatus, BadgeVariant> = {
  active: 'danger',
  acknowledged: 'warning',
  resolved: 'success',
};

export const statusLabels: Record<AlertStatus, string> = {
  active: 'Active',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
};

export const categoryBadgeVariant: Record<AlertCategory, BadgeVariant> = {
  inventory: 'coral',
  expiry: 'amber',
  sales: 'teal',
  system: 'neutral',
};

export const categoryLabels: Record<AlertCategory, string> = {
  inventory: 'Inventory',
  expiry: 'Expiry',
  sales: 'Sales',
  system: 'System',
};
