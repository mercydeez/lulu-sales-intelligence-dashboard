import { InventoryItem, InventoryAlert, ProcurementItem } from './types';

// Derived demo helpers: the inventory page builds alerts + a suggested procurement
// list from the real inventory rows it already fetched. (The unused mock-inventory /
// summary / category generators were removed — the page serves only real endpoints.)

export function generateAlerts(inventoryItems: InventoryItem[]): InventoryAlert[] {
  const alerts: InventoryAlert[] = [];
  let alertId = 1;

  inventoryItems.forEach(item => {
    if (item.status === 'out_of_stock') {
      alerts.push({
        id: alertId++,
        item_name: item.item_name,
        store_name: item.store_name,
        type: 'out_of_stock',
        message: `${item.item_name} is out of stock at ${item.store_name}. Immediate reorder required!`,
        severity: 'critical',
        timestamp: new Date(Date.now() - Math.random() * 3600000).toISOString(),
        acknowledged: false,
      });
    } else if (item.status === 'low_stock') {
      alerts.push({
        id: alertId++,
        item_name: item.item_name,
        store_name: item.store_name,
        type: 'low_stock',
        message: `${item.item_name} is running low at ${item.store_name}. Current stock: ${item.quantity} (Reorder level: ${item.reorder_level})`,
        severity: 'warning',
        timestamp: new Date(Date.now() - Math.random() * 7200000).toISOString(),
        acknowledged: false,
      });
    } else if (item.status === 'overstocked') {
      alerts.push({
        id: alertId++,
        item_name: item.item_name,
        store_name: item.store_name,
        type: 'overstocked',
        message: `${item.item_name} is overstocked at ${item.store_name}. Current: ${item.quantity} (Max: ${item.max_stock_level})`,
        severity: 'info',
        timestamp: new Date(Date.now() - Math.random() * 14400000).toISOString(),
        acknowledged: false,
      });
    }
  });

  return alerts.sort((a, b) => {
    const severityOrder = { critical: 0, warning: 1, info: 2 };
    return severityOrder[a.severity] - severityOrder[b.severity];
  }).slice(0, 50);
}

export function generateProcurementList(inventoryItems: InventoryItem[]): ProcurementItem[] {
  const procurement: ProcurementItem[] = [];
  let procId = 1;

  inventoryItems
    .filter(item => item.status === 'out_of_stock' || item.status === 'low_stock')
    .forEach(item => {
      const suggestedQty = item.status === 'out_of_stock'
        ? item.max_stock_level
        : item.reorder_level * 2 - item.quantity;

      procurement.push({
        id: procId++,
        item,
        suggestedQuantity: Math.max(suggestedQty, item.reorder_level),
        status: 'pending',
        priority: item.status === 'out_of_stock' ? 'critical' :
                 item.quantity < item.reorder_level / 2 ? 'high' : 'medium',
        createdAt: new Date().toISOString(),
      });
    });

  return procurement.sort((a, b) => {
    const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    return priorityOrder[a.priority] - priorityOrder[b.priority];
  });
}
