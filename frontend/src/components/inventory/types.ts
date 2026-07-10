import { BadgeVariant } from '@/components/ui';
import { SEVERITY_BADGE } from '@/lib/severity';

export interface InventoryItem {
  id: number;
  item_id: number;
  item_name: string;
  category: string;
  store_id: number;
  store_name: string;
  quantity: number;
  reorder_level: number;
  max_stock_level: number;
  unit_cost: number;
  last_restocked: string | null;
  status: 'in_stock' | 'low_stock' | 'out_of_stock' | 'overstocked';
}

export interface InventorySummary {
  total_items: number;
  total_value: number;
  low_stock_count: number;
  out_of_stock_count: number;
  overstocked_count: number;
  pending_transfers: number;
  currency: string;
}

export interface CategoryData {
  category: string;
  item_count: number;
  total_quantity: number;
  total_value: number;
  low_stock_count: number;
}

export interface ProcurementItem {
  id: number;
  item: InventoryItem;
  suggestedQuantity: number;
  status: 'pending' | 'approved' | 'rejected' | 'ordered';
  priority: 'critical' | 'high' | 'medium' | 'low';
  createdAt: string;
  notes?: string;
}

export interface InventoryAlert {
  id: number;
  item_name: string;
  store_name: string;
  type: 'out_of_stock' | 'low_stock' | 'overstocked' | 'reorder';
  message: string;
  severity: 'critical' | 'warning' | 'info';
  timestamp: string;
  acknowledged: boolean;
}

export const statusBadgeVariant: Record<InventoryItem['status'], BadgeVariant> = {
  in_stock: 'success',
  low_stock: 'warning',
  out_of_stock: 'danger',
  overstocked: 'violet',
};

export const statusLabels: Record<InventoryItem['status'], string> = {
  in_stock: 'In Stock',
  low_stock: 'Low Stock',
  out_of_stock: 'Out of Stock',
  overstocked: 'Overstocked',
};

// One severity→color map app-wide (lib/severity) — this is that map.
export const priorityBadgeVariant: Record<ProcurementItem['priority'], BadgeVariant> = SEVERITY_BADGE;

export const severityBadgeVariant: Record<InventoryAlert['severity'], BadgeVariant> = {
  critical: 'danger',
  warning: 'warning',
  info: 'violet',
};

export const procurementStatusBadgeVariant: Record<ProcurementItem['status'], BadgeVariant> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  ordered: 'violet',
};
