'use client';

import { useEffect, useState, useMemo } from 'react';
import { Wifi, WifiOff, Clock, Timer, Zap } from 'lucide-react';
import { LiveIndicator } from '@/components/ui';
import { useEventStream } from '@/hooks/useEventStream';
import { authFetch } from '@/contexts/AuthContext';

interface StreamSale {
  id: number;
  event_id: string | null;
  timestamp: string;
  store_id: number;
  store_name: string | null;
  item_id: number;
  item_name: string | null;
  sales: number;
  is_streaming: boolean;
  isNew?: boolean;
}

// Parse timestamp safely - handles various formats
function parseTimestamp(timestamp: string | undefined | null): Date | null {
  if (!timestamp) return null;
  try {
    let dateStr = timestamp;
    // If it doesn't have timezone info, assume UTC
    if (!dateStr.includes('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
      dateStr = dateStr + 'Z';
    }
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return null;
    return date;
  } catch {
    return null;
  }
}

// Format timestamp to readable format
function formatTimestamp(timestamp: string | undefined | null): string {
  const date = parseTimestamp(timestamp);
  if (!date) return 'Just now';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true
  });
}

// Calculate time ago
function getTimeAgo(timestamp: string | undefined | null): string {
  const then = parseTimestamp(timestamp);
  if (!then) return 'just now';

  const now = new Date();
  const diffMs = now.getTime() - then.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);

  if (diffSecs < 0) return 'just now';
  if (diffSecs < 5) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return then.toLocaleDateString();
}

export default function LiveTable() {
  const [sales, setSales] = useState<StreamSale[]>([]);
  const [nextStreamIn, setNextStreamIn] = useState(10);
  const [currentTime, setCurrentTime] = useState<Date | null>(null);
  const [mounted, setMounted] = useState(false);

  // Update current time every second for "time ago" updates
  useEffect(() => {
    setMounted(true);
    setCurrentTime(new Date());
    const timer = setInterval(() => {
      setCurrentTime(new Date());
      setNextStreamIn(prev => (prev > 0 ? prev - 1 : 10));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch initial data
  const fetchLatest = async () => {
    try {
      const response = await authFetch('/stream/latest?limit=20');
      if (!response.ok) throw new Error('Failed to fetch latest data');
      const data = await response.json();
      // Normalize timestamp field - API returns 'timestamp' but SSE might use 'created_at'
      const normalized = data.map((sale: any) => ({
        ...sale,
        timestamp: sale.timestamp || sale.created_at || new Date().toISOString()
      }));
      setSales(normalized);
    } catch (err) {
      console.error('Error fetching latest:', err);
    }
  };

  // Connect to SSE using useEventStream hook
  const eventHandlers = useMemo(() => ({
    sales: (rawSale: any) => {
      // Normalize: use created_at as timestamp if timestamp is missing
      const sale = {
        ...rawSale,
        timestamp: rawSale.timestamp || rawSale.created_at || new Date().toISOString(),
        store_name: rawSale.store_name || `Store ${rawSale.store_id}`,
        item_name: rawSale.item_name || `Item ${rawSale.item_id}`
      };
      setNextStreamIn(10); // Reset countdown
      setSales((prev) => {
        const newSale = { ...sale, isNew: true };
        const updated = [newSale, ...prev.slice(0, 19)];

        // Remove highlight after 2 seconds
        setTimeout(() => {
          setSales((current) =>
            current.map((s) =>
              s.id === sale.id ? { ...s, isNew: false } : s
            )
          );
        }, 2000);

        return updated;
      });
    }
  }), []);

  const { isConnected: connected, error } = useEventStream('/stream/sales', { eventHandlers });

  useEffect(() => {
    fetchLatest();
  }, []);

  return (
    <div className="glass rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-coral-100 flex items-center justify-between bg-coral-50/60">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-100">
            <Zap className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink">Live Sales Feed</h3>
            <p className="text-xs text-ink-muted">Real-time streaming data</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Next stream countdown */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-coral-50">
            <Timer className="w-4 h-4 text-amber-600" />
            <span className="text-sm text-ink-soft">
              Next: <span className="font-mono text-amber-600">{nextStreamIn}s</span>
            </span>
          </div>

          {/* Connection status */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${
            connected ? 'bg-emerald-100' : 'bg-rose-100'
          }`}>
            {connected ? (
              <>
                <Wifi className="w-4 h-4 text-emerald-600" />
                <span className="text-sm text-emerald-700">Connected</span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-rose-600" />
                <span className="text-sm text-rose-700">Disconnected</span>
              </>
            )}
          </div>

          {/* Live indicator — canonical teal pulse (rose = danger, not "live") */}
          <LiveIndicator />
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-6 py-3 bg-amber-50 border-b border-amber-200 text-amber-700 text-sm flex items-center gap-2">
          <Clock className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-coral-50">
            <tr>
              <th className="px-6 py-4 text-start text-xs font-semibold text-ink-muted uppercase tracking-wider">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  Timestamp
                </div>
              </th>
              <th className="px-6 py-4 text-start text-xs font-semibold text-ink-muted uppercase tracking-wider">
                Store
              </th>
              <th className="px-6 py-4 text-start text-xs font-semibold text-ink-muted uppercase tracking-wider">
                Item
              </th>
              <th className="px-6 py-4 text-start text-xs font-semibold text-ink-muted uppercase tracking-wider">
                Sales
              </th>
              <th className="px-6 py-4 text-start text-xs font-semibold text-ink-muted uppercase tracking-wider">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-coral-100">
            {sales.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-ink-muted">
                  <div className="flex flex-col items-center gap-2">
                    <Zap className="w-8 h-8 text-coral-200" />
                    <span>Waiting for streaming data...</span>
                  </div>
                </td>
              </tr>
            ) : (
              sales.map((sale, index) => (
                <tr
                  key={sale.id}
                  className={`transition-all duration-500 ${
                    sale.isNew
                      ? sale.sales < 0
                        ? 'bg-rose-50'
                        : 'bg-teal-50'
                      : index % 2 === 0
                        ? 'bg-coral-50/40'
                        : 'bg-surface'
                  } hover:bg-coral-50`}
                >
                  {/* Timestamp Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-ink">
                        {mounted ? formatTimestamp(sale.timestamp) : '--'}
                      </span>
                      <span className={`text-xs ${
                        sale.isNew
                          ? sale.sales < 0
                            ? 'text-rose-600 font-semibold'
                            : 'text-teal-600 font-semibold'
                          : 'text-ink-muted'
                      }`}>
                        {mounted ? getTimeAgo(sale.timestamp) : '--'}
                      </span>
                    </div>
                  </td>

                  {/* Store Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        sale.sales < 0 ? 'bg-rose-100' : 'bg-violet-100'
                      }`}>
                        <span className={`text-xs font-bold ${
                          sale.sales < 0 ? 'text-rose-600' : 'text-violet-600'
                        }`}>{sale.store_id}</span>
                      </div>
                      <div className="text-sm font-medium text-ink">
                        {sale.store_name || `Store ${sale.store_id}`}
                      </div>
                    </div>
                  </td>

                  {/* Item Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-ink-soft">
                      {sale.item_name || `Item ${sale.item_id}`}
                    </div>
                  </td>

                  {/* Sales Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-3 py-1.5 text-sm font-bold rounded-lg ${
                      sale.sales < 0
                        ? 'bg-rose-100 text-rose-700'
                        : sale.isNew
                          ? 'bg-teal-100 text-teal-700'
                          : 'bg-coral-50 text-ink'
                    }`}>
                      {sale.sales < 0 ? sale.sales : `+${sale.sales}`}
                    </span>
                  </td>

                  {/* Status Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    {sale.sales < 0 ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-rose-100 text-rose-700 rounded-full">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-rose-500"></span>
                        </span>
                        Return
                      </span>
                    ) : sale.is_streaming ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-emerald-100 text-emerald-700 rounded-full">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                        </span>
                        Live
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-coral-50 text-ink-muted rounded-full">
                        Historical
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="px-6 py-3 border-t border-coral-100 bg-coral-50/40 flex items-center justify-between text-sm text-ink-muted">
        <span>Showing latest {sales.length} records</span>
        <span className="flex items-center gap-2">
          <Clock className="w-4 h-4" />
          {mounted && currentTime ? currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }) : '--:--:--'}
        </span>
      </div>
    </div>
  );
}
