'use client';

import { useEffect, useState, useMemo } from 'react';
import { Wifi, WifiOff, Clock, Timer, Zap } from 'lucide-react';
import { Badge, EmptyState, LiveIndicator } from '@/components/ui';
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
      <div className="px-6 py-4 border-b border-line flex items-center justify-between bg-surface-2/70">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-50 ring-1 ring-teal-100">
            <Zap className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink">Live Sales Feed</h3>
            <p className="text-xs text-ink-muted">Real-time streaming data</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Next stream countdown */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-2">
            <Timer className="w-4 h-4 text-ink-muted" />
            <span className="text-sm text-ink-soft">
              Next: <span className="font-mono text-ink tabular-nums">{nextStreamIn}s</span>
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
          <thead className="bg-surface-2/70">
            <tr>
              <th className="px-4 py-3 text-start text-xs font-semibold text-ink-muted uppercase tracking-wide">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  Timestamp
                </div>
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-ink-muted uppercase tracking-wide">
                Store
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-ink-muted uppercase tracking-wide">
                Item
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-ink-muted uppercase tracking-wide">
                Sales
              </th>
              <th className="px-4 py-3 text-start text-xs font-semibold text-ink-muted uppercase tracking-wide">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {sales.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-2">
                  <EmptyState
                    icon={<Zap className="w-7 h-7" />}
                    title="Waiting for streaming data"
                    description="Live sales appear here the moment they happen."
                  />
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
                        ? 'bg-surface-2/40'
                        : 'bg-surface'
                  } hover:bg-teal-50/40`}
                >
                  {/* Timestamp Column */}
                  <td className="px-4 py-3 whitespace-nowrap">
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
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        sale.sales < 0 ? 'bg-rose-100' : 'bg-surface-2'
                      }`}>
                        <span className={`text-xs font-bold tabular-nums ${
                          sale.sales < 0 ? 'text-rose-600' : 'text-ink-soft'
                        }`}>{sale.store_id}</span>
                      </div>
                      <div className="text-sm font-medium text-ink">
                        {sale.store_name || `Store ${sale.store_id}`}
                      </div>
                    </div>
                  </td>

                  {/* Item Column */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-sm text-ink-soft">
                      {sale.item_name || `Item ${sale.item_id}`}
                    </div>
                  </td>

                  {/* Sales Column */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className={`px-3 py-1.5 text-sm font-bold tabular-nums rounded-lg ${
                      sale.sales < 0
                        ? 'bg-rose-100 text-rose-700'
                        : sale.isNew
                          ? 'bg-teal-100 text-teal-700'
                          : 'bg-surface-2 text-ink'
                    }`}>
                      {sale.sales < 0 ? sale.sales : `+${sale.sales}`}
                    </span>
                  </td>

                  {/* Status Column — shared Badge; the header's single LiveIndicator
                      carries the pulse (a ping per row was ambient noise) */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {sale.sales < 0 ? (
                      <Badge variant="danger" size="sm">Return</Badge>
                    ) : sale.is_streaming ? (
                      <Badge variant="teal" size="sm">Live</Badge>
                    ) : (
                      <Badge variant="neutral" size="sm">Historical</Badge>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="px-6 py-3 border-t border-line bg-surface-2/40 flex items-center justify-between text-sm text-ink-muted">
        <span>Showing latest {sales.length} records</span>
        <span className="flex items-center gap-2">
          <Clock className="w-4 h-4" />
          {mounted && currentTime ? currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }) : '--:--:--'}
        </span>
      </div>
    </div>
  );
}
