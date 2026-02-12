'use client';

import { useState, useEffect, useCallback, useRef } from 'react';

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

const ALERTS_SSE_URL = process.env.NEXT_PUBLIC_ALERTS_SSE_URL || 'http://localhost:8000/stream/alerts';
const INVENTORY_SSE_URL = process.env.NEXT_PUBLIC_INVENTORY_SSE_URL || 'http://localhost:8000/stream/inventory';

export function useAlertStream(maxAlerts: number = 50) {
  const [alerts, setAlerts] = useState<LiveAlert[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    
    const eventSource = new EventSource(ALERTS_SSE_URL);
    eventSourceRef.current = eventSource;
    
    eventSource.addEventListener('connected', () => {
      setIsConnected(true);
      setError(null);
    });
    
    eventSource.addEventListener('alert', (event) => {
      try {
        const alert: LiveAlert = JSON.parse(event.data);
        setAlerts((prev) => {
          // Avoid duplicates
          const exists = prev.some(a => a.id === alert.id);
          if (exists) return prev;
          return [alert, ...prev].slice(0, maxAlerts);
        });
      } catch (e) {
        console.error('Failed to parse alert SSE data:', e);
      }
    });
    
    eventSource.onerror = () => {
      setIsConnected(false);
      setError('Connection lost. Reconnecting...');
      eventSource.close();
      
      // Reconnect after 5 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 5000);
    };
  }, [maxAlerts]);
  
  useEffect(() => {
    connect();
    
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

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
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    
    const eventSource = new EventSource(INVENTORY_SSE_URL);
    eventSourceRef.current = eventSource;
    
    eventSource.addEventListener('connected', () => {
      setIsConnected(true);
      setError(null);
    });
    
    eventSource.addEventListener('inventory_update', (event) => {
      try {
        const update: InventoryUpdate = JSON.parse(event.data);
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
      } catch (e) {
        console.error('Failed to parse inventory SSE data:', e);
      }
    });
    
    eventSource.onerror = () => {
      setIsConnected(false);
      setError('Connection lost. Reconnecting...');
      eventSource.close();
      
      // Reconnect after 5 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 5000);
    };
  }, [maxUpdates]);
  
  useEffect(() => {
    connect();
    
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

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
