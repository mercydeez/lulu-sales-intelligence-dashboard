'use client';

import { useEffect, useState, useRef } from 'react';
import { RotateCcw, Package, Store, Clock, TrendingDown, AlertTriangle, RefreshCw } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch returns data
  const fetchReturns = async () => {
    try {
      const response = await fetch(`${API_URL}/api/analytics/returns-summary`);
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

  // Connect to SSE for real-time return updates
  useEffect(() => {
    const connectSSE = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const eventSource = new EventSource(`${API_URL}/stream/sales`);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('sales', (event) => {
        try {
          const sale = JSON.parse(event.data);
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
        } catch (e) {
          console.error('Error parsing SSE:', e);
        }
      });

      eventSource.onerror = () => {
        eventSource.close();
        setTimeout(connectSSE, 5000);
      };
    };

    connectSSE();
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  const formatTime = (timestamp: string) => {
    if (!mounted) return '--:--';
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      });
    } catch {
      return '--:--';
    }
  };

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
          <div className="w-12 h-12 rounded-full bg-slate-700 mb-3"></div>
          <div className="h-4 bg-slate-700 rounded w-32"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl p-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-rose-500/20 rounded-lg relative">
            <RotateCcw className="w-5 h-5 text-rose-400" />
            <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500"></span>
            </span>
          </div>
          <div>
            <h3 className="text-white font-semibold">Live Returns Feed</h3>
            <p className="text-slate-400 text-xs">Real-time return tracking</p>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-rose-400">{stats?.today_count || 0}</div>
          <div className="text-xs text-slate-400">Today&apos;s Returns</div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <TrendingDown className="w-4 h-4 text-rose-400" />
            <span className="text-xs text-slate-400">Today&apos;s Value</span>
          </div>
          <div className="text-lg font-bold text-rose-400">
            {(stats?.today_value || 0).toLocaleString()} <span className="text-xs font-normal">Units</span>
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span className="text-xs text-slate-400">All-Time</span>
          </div>
          <div className="text-lg font-bold text-amber-400">
            {stats?.all_time_count || 0} <span className="text-xs font-normal">Returns</span>
          </div>
        </div>
      </div>

      {/* Live Returns List */}
      <div className="flex-1 overflow-hidden">
        <div className="flex items-center gap-2 mb-2">
          <RefreshCw className="w-3 h-3 text-rose-400 animate-spin" style={{ animationDuration: '3s' }} />
          <span className="text-xs text-slate-400">Live Updates</span>
        </div>
        
        <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1 custom-scrollbar">
          {liveReturns.length === 0 ? (
            <div className="text-center py-8 text-slate-500">
              <RotateCcw className="w-8 h-8 mx-auto mb-2 text-slate-600" />
              <p className="text-sm">No returns yet today</p>
              <p className="text-xs text-slate-600 mt-1">Returns will appear here in real-time</p>
            </div>
          ) : (
            liveReturns.map((item: ReturnItem, index: number) => (
              <div
                key={`${item.id}-${index}`}
                className={`p-3 rounded-lg border transition-all duration-500 ${
                  item.isNew
                    ? 'bg-rose-500/20 border-rose-500/50 animate-pulse shadow-lg shadow-rose-500/20'
                    : 'bg-slate-800/30 border-slate-700/30 hover:bg-slate-800/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                      item.isNew ? 'bg-rose-500/30' : 'bg-slate-700/50'
                    }`}>
                      <Package className={`w-4 h-4 ${item.isNew ? 'text-rose-400' : 'text-slate-400'}`} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white">{item.item_name}</span>
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-rose-500/20 text-rose-400 font-semibold">
                          RETURN
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        <Store className="w-3 h-3" />
                        <span>{item.store_name}</span>
                        <span className="text-slate-600">•</span>
                        <Clock className="w-3 h-3" />
                        <span>{getTimeAgo(item.timestamp)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-rose-400 flex items-center gap-1">
                      <TrendingDown className="w-4 h-4" />
                      {item.quantity}
                    </div>
                    <div className="text-xs text-slate-500">Qty</div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Top Return Categories */}
      {stats?.by_category && stats.by_category.length > 0 && (
        <div className="mt-4 pt-3 border-t border-slate-700/50">
          <div className="text-xs text-slate-400 mb-2">Top Return Categories</div>
          <div className="flex flex-wrap gap-2">
            {stats.by_category.slice(0, 4).map((cat: { category: string; count: number; value: number }) => (
              <span
                key={cat.category}
                className="px-2 py-1 text-xs rounded-full bg-slate-800/50 text-slate-300"
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
