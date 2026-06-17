import { InventoryItem, InventorySummary, CategoryData, InventoryAlert, ProcurementItem } from './types';

/** Demo-safe fallback data — used when the API returns empty so no screen is ever blank. */
export function generateMockInventory(): InventoryItem[] {
  const categories = ['Dairy', 'Beverages', 'Bakery', 'Fruits', 'Vegetables', 'Meat', 'Frozen Foods', 'Household'];
  const stores = [
    { id: 1, name: 'Al Barsha' },
    { id: 2, name: 'Deira City Centre' },
    { id: 3, name: 'Karama' },
    { id: 4, name: 'Mushrif Mall' },
    { id: 5, name: 'Al Wahda' },
  ];
  const items: InventoryItem[] = [];
  let id = 1;

  const productNames: { [key: string]: string[] } = {
    'Dairy': ['Fresh Milk 1L', 'Greek Yogurt', 'Cheddar Cheese', 'Butter 500g', 'Cream Cheese'],
    'Beverages': ['Mineral Water 1.5L', 'Orange Juice', 'Cola 330ml', 'Green Tea', 'Coffee Beans'],
    'Bakery': ['White Bread', 'Croissants', 'Whole Wheat Bread', 'Bagels', 'Muffins'],
    'Fruits': ['Apples', 'Bananas', 'Oranges', 'Grapes', 'Mangoes'],
    'Vegetables': ['Tomatoes', 'Onions', 'Potatoes', 'Carrots', 'Lettuce'],
    'Meat': ['Chicken Breast', 'Ground Beef', 'Lamb Chops', 'Beef Steak', 'Chicken Wings'],
    'Frozen Foods': ['Frozen Pizza', 'Ice Cream', 'Frozen Vegetables', 'Fish Fingers', 'Frozen Berries'],
    'Household': ['Dish Soap', 'Laundry Detergent', 'Paper Towels', 'Garbage Bags', 'Cleaning Spray'],
  };

  categories.forEach((category, catIdx) => {
    const products = productNames[category] || [];
    products.forEach((productName, prodIdx) => {
      stores.forEach((store) => {
        const quantity = Math.floor(Math.random() * 500);
        const reorder = 50 + Math.floor(Math.random() * 30);
        const maxStock = 400 + Math.floor(Math.random() * 200);

        let status: InventoryItem['status'] = 'in_stock';
        if (quantity <= 0) status = 'out_of_stock';
        else if (quantity <= reorder) status = 'low_stock';
        else if (quantity > maxStock) status = 'overstocked';

        items.push({
          id: id++,
          item_id: catIdx * 100 + prodIdx + 1,
          item_name: productName,
          category,
          store_id: store.id,
          store_name: store.name,
          quantity,
          reorder_level: reorder,
          max_stock_level: maxStock,
          unit_cost: 10 + Math.random() * 50,
          last_restocked: new Date(Date.now() - Math.random() * 7 * 24 * 60 * 60 * 1000).toISOString(),
          status,
        });
      });
    });
  });
  return items;
}

export function generateMockSummary(): InventorySummary {
  return {
    total_items: 1250,
    total_value: 2847500,
    low_stock_count: 45,
    out_of_stock_count: 12,
    overstocked_count: 8,
    pending_transfers: 5,
    currency: 'AED',
  };
}

export function generateMockCategories(): CategoryData[] {
  return [
    { category: 'Dairy', item_count: 156, total_quantity: 12500, total_value: 187500, low_stock_count: 8 },
    { category: 'Beverages', item_count: 142, total_quantity: 15800, total_value: 156000, low_stock_count: 5 },
    { category: 'Bakery', item_count: 98, total_quantity: 8200, total_value: 82000, low_stock_count: 12 },
    { category: 'Fruits', item_count: 125, total_quantity: 9500, total_value: 142500, low_stock_count: 6 },
    { category: 'Vegetables', item_count: 180, total_quantity: 14200, total_value: 142000, low_stock_count: 4 },
    { category: 'Meat', item_count: 85, total_quantity: 4200, total_value: 378000, low_stock_count: 3 },
    { category: 'Frozen Foods', item_count: 120, total_quantity: 8800, total_value: 220000, low_stock_count: 2 },
    { category: 'Household', item_count: 95, total_quantity: 11200, total_value: 336000, low_stock_count: 5 },
  ];
}

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
