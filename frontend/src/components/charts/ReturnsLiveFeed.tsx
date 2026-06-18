'use client';

import { useEffect, useState, useMemo } from 'react';
import { RotateCcw, Package, Store, Clock, TrendingDown, AlertTriangle, RefreshCw } from 'lucide-react';
import { useEventStream } from '@/hooks/useEventStream';
import { authFetch } from '@/contexts/AuthContext';

interface ReturnItem {
  id: number;
  store_name: string;
  item_name: string;
  category: string;
  quantity: number;
  timestamp: string;
  isNew?: boolean;
}

interface ReturnStats {
  today_count: number;
  today_value: number;
  all_time_count: number;
  all_time_value: number;
  by_store: Array<{ store: string; count: number; value: number }>;
  by_category: Array<{ category: string; count: number; value: number }>;
  recent_items: ReturnItem[];
}

export default function ReturnsLiveFeed() {
  const [stats, setStats] = useState<ReturnStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [liveReturns, setLiveReturns] = useState<ReturnItem[]>([]);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch returns data using authFetch
  const fetchReturns = async () => {
    try {
      const response = await authFetch('/api/analytics/returns-summary');
      if (!response.ok) throw new Error('Failed to fetch returns');
      const data = await response.json();
      setStats(data);

      // Initialize live returns with recent items
      if (data.recent_items && liveReturns.length === 0) {
        setLiveReturns(data.recent_items.slice(0, 10));
      }
    } catch (error) {
      console.error('Error fetching returns:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReturns();
    const interval = setInterval(fetchReturns, 15000); // Refresh every 15 seconds
    return () => clearInterval(interval);
  }, []);

  // Connect to SSE for real-time return updates using useEventStream hook
  const eventHandlers = useMemo(() => ({
    sales: (sale: any) => {
      // Only process returns (negative sales)
      if (sale.sales < 0) {
        const newReturn: ReturnItem = {
          id: sale.id,
          store_name: sale.store_name || `Store ${sale.store_id}`,
          item_name: sale.item_name || `Item ${sale.item_id}`,
          category: sale.category || 'General',
          quantity: Math.abs(sale.sales),
          timestamp: sale.created_at || new Date().toISOString(),
          isNew: true
        };

        setLiveReturns((prev: ReturnItem[]) => {
          const updated = [newReturn, ...prev.slice(0, 9)];
          // Remove highlight after animation
          setTimeout(() => {
            setLiveReturns((current: ReturnItem[]) =>
              current.map((r: ReturnItem) => r.id === newReturn.id ? { ...r, isNew: false } : r)
            );
          }, 3000);
          return updated;
        });

        // Update stats
        setStats((prev: ReturnStats | null) => prev ? {
          ...prev,
          today_count: prev.today_count + 1,
          today_value: prev.today_value + Math.abs(sale.sales)
        } : prev);
      }
    }
  }), []);

  useEventStream('/stream/sales', { eventHandlers });

  const getTimeAgo = (timestamp: string) => {
    if (!mounted) return 'just now';
    try {
      const date = new Date(timestamp);
      const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
      if (seconds < 60) return `${seconds}s ago`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
      return `${Math.floor(seconds / 3600)}h ago`;
    } catch {
      return 'just now';
    }
  };

  if (loading) {
    return (
      <div className="glass rounded-xl p-6 h-full flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center">
          <div className="w-12 h-12 rounded-full bg-coral-100 mb-3"></div>
          <div className="h-4 bg-coral-100 rounded w-32"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl p-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-rose-100 rounded-lg relative">
            <RotateCcw className="w-5 h-5 text-rose-600" />
            <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500"></span>
            </span>
          </div>
          <div>
            <h3 className="text-ink font-semibold">Live Returns Feed</h3>
            <p className="text-ink-muted text-xs">Real-time return tracking</p>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-rose-600">{stats?.today_count || 0}</div>
          <div className="text-xs text-ink-muted">Today&apos;s Returns</div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <div className="bg-coral-50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <TrendingDown className="w-4 h-4 text-rose-600" />
            <span className="text-xs text-ink-muted">Today&apos;s Value</span>
          </div>
          <div className="text-lg font-bold text-rose-600">
            {(stats?.today_value || 0).toLocaleString()} <span className="text-xs font-normal">Units</span>
          </div>
        </div>
        <div className="bg-coral-50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span className="text-xs text-ink-muted">All-Time</span>
          </div>
          <div className="text-lg font-bold text-amber-600">
            {stats?.all_time_count || 0} <span className="text-xs font-normal">Returns</span>
          </div>
        </div>
      </div>

      {/* Live Returns List */}
      <div className="flex-1 overflow-hidden">
        <div className="flex items-center gap-2 mb-2">
          <RefreshCw className="w-3 h-3 text-rose-600 animate-spin" style={{ animationDuration: '3s' }} />
          <span className="text-xs text-ink-muted">Live Updates</span>
        </div>

        <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1 custom-scrollbar">
          {liveReturns.length === 0 ? (
            <div className="text-center py-8 text-ink-muted">
              <RotateCcw className="w-8 h-8 mx-auto mb-2 text-coral-200" />
              <p className="text-sm">No returns yet today</p>
              <p className="text-xs text-ink-muted/70 mt-1">Returns will appear here in real-time</p>
            </div>
          ) : (
            liveReturns.map((item: ReturnItem, index: number) => (
              <div
                key={`${item.id}-${index}`}
                className={`p-3 rounded-lg border transition-all duration-500 ${
                  item.isNew
                    ? 'bg-rose-50 border-rose-200 animate-pulse shadow-lg shadow-rose-500/10'
                    : 'bg-coral-50/40 border-coral-100 hover:bg-coral-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                      item.isNew ? 'bg-rose-100' : 'bg-coral-100'
                    }`}>
                      <Package className={`w-4 h-4 ${item.isNew ? 'text-rose-600' : 'text-ink-muted'}`} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-ink">{item.item_name}</span>
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-rose-100 text-rose-700 font-semibold">
                          RETURN
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-ink-muted">
                        <Store className="w-3 h-3" />
                        <span>{item.store_name}</span>
                        <span className="text-ink-muted/50">•</span>
                        <Clock className="w-3 h-3" />
                        <span>{getTimeAgo(item.timestamp)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-rose-600 flex items-center gap-1">
                      <TrendingDown className="w-4 h-4" />
                      {item.quantity}
                    </div>
                    <div className="text-xs text-ink-muted">Qty</div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Top Return Categories */}
      {stats?.by_category && stats.by_category.length > 0 && (
        <div className="mt-4 pt-3 border-t border-coral-100">
          <div className="text-xs text-ink-muted mb-2">Top Return Categories</div>
          <div className="flex flex-wrap gap-2">
            {stats.by_category.slice(0, 4).map((cat: { category: string; count: number; value: number }) => (
              <span
                key={cat.category}
                className="px-2 py-1 text-xs rounded-full bg-coral-50 text-ink-soft"
              >
                {cat.category}: {cat.count}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
