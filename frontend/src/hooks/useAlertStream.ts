'use client';

import { useState, useCallback, useMemo } from 'react';
import { useEventStream } from './useEventStream';

export interface LiveAlert {
  id: number;
  title: string;
  message: string;
  type: 'out_of_stock' | 'low_stock' | 'overstocked' | 'reorder' | 'high_sales' | 'price_change';
  severity: 'critical' | 'warning' | 'info' | 'success';
  category: 'inventory' | 'sales' | 'system' | 'promotion';
  item_id?: number;
  item_name?: string;
  item_category?: string;
  store_id?: number;
  store_name?: string;
  quantity?: number;
  timestamp: string;
  read: boolean;
}

export interface InventoryUpdate {
  id: number;
  item_id: number;
  item_name: string;
  category: string;
  store_id: number;
  store_name: string;
  quantity: number;
  reorder_level: number;
  max_stock: number;
  status: 'in_stock' | 'low_stock' | 'out_of_stock' | 'overstocked';
  unit_cost: number;
  timestamp: string;
}

export function useAlertStream(maxAlerts: number = 50) {
  const [alerts, setAlerts] = useState<LiveAlert[]>([]);

  const eventHandlers = useMemo(() => ({
    alert: (alert: LiveAlert) => {
      setAlerts((prev) => {
        // Avoid duplicates
        const exists = prev.some(a => a.id === alert.id);
        if (exists) return prev;
        return [alert, ...prev].slice(0, maxAlerts);
      });
    }
  }), [maxAlerts]);

  const { isConnected, error } = useEventStream('/stream/alerts', { eventHandlers });

  const markAsRead = useCallback((alertId: number) => {
    setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, read: true } : a));
  }, []);

  const markAllAsRead = useCallback(() => {
    setAlerts(prev => prev.map(a => ({ ...a, read: true })));
  }, []);

  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);

  const unreadCount = alerts.filter(a => !a.read).length;
  const criticalCount = alerts.filter(a => a.severity === 'critical' && !a.read).length;
  const warningCount = alerts.filter(a => a.severity === 'warning' && !a.read).length;
  
  return { 
    alerts, 
    isConnected, 
    error,
    unreadCount,
    criticalCount,
    warningCount,
    markAsRead,
    markAllAsRead,
    clearAlerts,
  };
}

export function useInventoryStream(maxUpdates: number = 100) {
  const [updates, setUpdates] = useState<InventoryUpdate[]>([]);

  const eventHandlers = useMemo(() => ({
    inventory_update: (update: InventoryUpdate) => {
      setUpdates((prev) => {
        // Replace if same item+store, otherwise add
        const existingIndex = prev.findIndex(
          u => u.item_id === update.item_id && u.store_id === update.store_id
        );
        if (existingIndex >= 0) {
          const newUpdates = [...prev];
          newUpdates[existingIndex] = update;
          return newUpdates;
        }
        return [update, ...prev].slice(0, maxUpdates);
      });
    }
  }), [maxUpdates]);

  const { isConnected, error } = useEventStream('/stream/inventory', { eventHandlers });

  // Computed stats
  const outOfStockCount = updates.filter(u => u.status === 'out_of_stock').length;
  const lowStockCount = updates.filter(u => u.status === 'low_stock').length;
  const overstockedCount = updates.filter(u => u.status === 'overstocked').length;
  const inStockCount = updates.filter(u => u.status === 'in_stock').length;
  
  return { 
    updates, 
    isConnected, 
    error,
    outOfStockCount,
    lowStockCount,
    overstockedCount,
    inStockCount,
  };
}
