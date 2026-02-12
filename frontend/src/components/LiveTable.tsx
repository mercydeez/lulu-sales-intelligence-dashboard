'use client';

import { useEffect, useState, useRef } from 'react';
import { Wifi, WifiOff, Clock, Timer, Zap } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextStreamIn, setNextStreamIn] = useState(10);
  const [currentTime, setCurrentTime] = useState<Date | null>(null);
  const [mounted, setMounted] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      const response = await fetch(`${API_URL}/stream/latest?limit=20`);
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

  // Connect to SSE
  const connectSSE = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const eventSource = new EventSource(`${API_URL}/stream/sales`);
    eventSourceRef.current = eventSource;

    eventSource.addEventListener('connected', () => {
      setConnected(true);
      setError(null);
    });

    eventSource.addEventListener('sales', (event) => {
      try {
        const rawSale = JSON.parse(event.data);
        // Normalize: use created_at as timestamp if timestamp is missing
        const sale = {
          ...rawSale,
          timestamp: rawSale.timestamp || rawSale.created_at || new Date().toISOString(),
          store_name: rawSale.store_name || `Store ${rawSale.store_id}`,
          item_name: rawSale.item_name || `Item ${rawSale.item_id}`
        };
        setNextStreamIn(10); // Reset countdown - faster interval
        setSales((prev) => {
          const newSale = { ...sale, isNew: true };
          const updated = [newSale, ...prev.slice(0, 19)];
          
          // Remove highlight after 2 seconds for faster feel
          setTimeout(() => {
            setSales((current) => 
              current.map((s) => 
                s.id === sale.id ? { ...s, isNew: false } : s
              )
            );
          }, 2000);
          
          return updated;
        });
      } catch (e) {
        console.error('Failed to parse SSE data:', e);
      }
    });

    eventSource.onerror = () => {
      setConnected(false);
      setError('Connection lost. Reconnecting...');
      eventSource.close();

      // Reconnect after 1 second for faster recovery
      reconnectTimeoutRef.current = setTimeout(() => {
        connectSSE();
      }, 1000);
    };
  };

  useEffect(() => {
    fetchLatest();
    connectSSE();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  return (
    <div className="glass rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between bg-slate-800/50">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-cyan-500/20">
            <Zap className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Live Sales Feed</h3>
            <p className="text-xs text-slate-400">Real-time streaming data</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Next stream countdown */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-700/50">
            <Timer className="w-4 h-4 text-amber-400" />
            <span className="text-sm text-slate-300">
              Next: <span className="font-mono text-amber-400">{nextStreamIn}s</span>
            </span>
          </div>
          
          {/* Connection status */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${
            connected ? 'bg-emerald-500/20' : 'bg-rose-500/20'
          }`}>
            {connected ? (
              <>
                <Wifi className="w-4 h-4 text-emerald-400" />
                <span className="text-sm text-emerald-400">Connected</span>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-rose-400" />
                <span className="text-sm text-rose-400">Disconnected</span>
              </>
            )}
          </div>

          {/* Live indicator */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/20">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-500 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500"></span>
            </span>
            <span className="text-sm font-bold text-rose-400">LIVE</span>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-6 py-3 bg-amber-500/10 border-b border-amber-500/30 text-amber-400 text-sm flex items-center gap-2">
          <Clock className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-slate-800/80">
            <tr>
              <th className="px-6 py-4 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  Timestamp
                </div>
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Store
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Item
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Sales
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/30">
            {sales.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                  <div className="flex flex-col items-center gap-2">
                    <Zap className="w-8 h-8 text-slate-600" />
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
                        ? 'animate-glow bg-rose-500/10' 
                        : 'animate-glow bg-cyan-500/10'
                      : index % 2 === 0 
                        ? 'bg-slate-800/30' 
                        : 'bg-slate-900/30'
                  } hover:bg-slate-700/30`}
                >
                  {/* Timestamp Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-white">
                        {mounted ? formatTimestamp(sale.timestamp) : '--'}
                      </span>
                      <span className={`text-xs ${
                        sale.isNew 
                          ? sale.sales < 0 
                            ? 'text-rose-400 font-semibold'
                            : 'text-cyan-400 font-semibold' 
                          : 'text-slate-500'
                      }`}>
                        {mounted ? getTimeAgo(sale.timestamp) : '--'}
                      </span>
                    </div>
                  </td>
                  
                  {/* Store Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        sale.sales < 0 ? 'bg-rose-500/20' : 'bg-purple-500/20'
                      }`}>
                        <span className={`text-xs font-bold ${
                          sale.sales < 0 ? 'text-rose-400' : 'text-purple-400'
                        }`}>{sale.store_id}</span>
                      </div>
                      <div className="text-sm font-medium text-white">
                        {sale.store_name || `Store ${sale.store_id}`}
                      </div>
                    </div>
                  </td>
                  
                  {/* Item Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-slate-300">
                      {sale.item_name || `Item ${sale.item_id}`}
                    </div>
                  </td>
                  
                  {/* Sales Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-3 py-1.5 text-sm font-bold rounded-lg ${
                      sale.sales < 0
                        ? 'bg-rose-500/30 text-rose-300'
                        : sale.isNew 
                          ? 'bg-cyan-500/30 text-cyan-300' 
                          : 'bg-slate-700/50 text-white'
                    }`}>
                      {sale.sales < 0 ? sale.sales : `+${sale.sales}`}
                    </span>
                  </td>
                  
                  {/* Status Column */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    {sale.sales < 0 ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-rose-500/20 text-rose-400 rounded-full">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-rose-500"></span>
                        </span>
                        Return
                      </span>
                    ) : sale.is_streaming ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-emerald-500/20 text-emerald-400 rounded-full">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                        </span>
                        Live
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold bg-slate-600/30 text-slate-400 rounded-full">
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
      <div className="px-6 py-3 border-t border-slate-700/50 bg-slate-800/30 flex items-center justify-between text-sm text-slate-500">
        <span>Showing latest {sales.length} records</span>
        <span className="flex items-center gap-2">
          <Clock className="w-4 h-4" />
          {mounted && currentTime ? currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }) : '--:--:--'}
        </span>
      </div>
    </div>
  );
}
