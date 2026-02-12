'use client';

import { useState, useEffect, useCallback } from 'react';
import { Sale, SalesAggregation, DashboardMetrics, Prediction, Store, Item } from '@/types';
import { fetchSales, fetchAggregatedSales, fetchMetrics, fetchPredictions, fetchStores, fetchItems } from '@/lib/api';

export function useSalesData() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [aggregatedSales, setAggregatedSales] = useState<SalesAggregation[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [salesData, aggregatedData, metricsData, predictionsData, storesData, itemsData] = await Promise.all([
        fetchSales({ limit: 50 }),
        fetchAggregatedSales(),
        fetchMetrics(),
        fetchPredictions(30).catch(() => []),
        fetchStores().catch(() => []),
        fetchItems().catch(() => []),
      ]);
      
      setSales(salesData);
      setAggregatedSales(aggregatedData);
      setMetrics(metricsData);
      setPredictions(predictionsData);
      setStores(storesData);
      setItems(itemsData);
      setError(null);
    } catch (e) {
      setError('Failed to load data');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);
  
  useEffect(() => {
    loadData();
    
    // Refresh data every 5 minutes
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadData]);
  
  return { sales, aggregatedSales, metrics, predictions, stores, items, loading, error, refresh: loadData };
}
